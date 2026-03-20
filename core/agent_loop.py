# core/agent_loop.py
"""
Agent Loop
==========
Agent Workflow Canvas (Mode 2) 的核心执行循环。

职责：
1. 接收用户目标 → 创建默认 DAG
2. 按拓扑顺序驱动节点执行（支持并行）
3. 处理 Gate 暂停/恢复
4. 失败自动重试
5. 通过 EventBus 实时推送状态
6. 持久化 graph + 日志

Phase 0 简化：
- 不调 LLM 规划 DAG（使用 create_default 硬编码模板）
- Gate 逻辑已实现（但可通过 skip_gates=True 跳过）
- 不做自评估（Phase 3 加入）
- 不处理分支（Phase 2 加入）
"""

import asyncio
import traceback
from pathlib import Path
from typing import Optional, Dict, Any

from core.graph_model import (
    WorkflowGraph, Node, NodeType, NodeStatus,
)
from core.node_executors import ExecutionContext, execute_node
from core.event_bus import EventBus, AgentLogger, AgentEvent


# ============================================================
# Agent 状态
# ============================================================

class AgentState:
    """
    管理单个 job 的 Agent 执行状态

    提供暂停/恢复/停止控制，以及 Gate 审批信号。
    """

    def __init__(self):
        self.paused: bool = False
        self.stopped: bool = False
        # Gate 等待信号：node_id → asyncio.Event
        self._gate_events: Dict[str, asyncio.Event] = {}
        # 已审批过的 Gate（防止重复触发）
        self._approved_gates: set = set()
        # 暂停恢复信号
        self._pause_event: asyncio.Event = asyncio.Event()
        self._pause_event.set()  # 初始非暂停

    def request_pause(self):
        self.paused = True
        self._pause_event.clear()

    def request_resume(self):
        self.paused = False
        self._pause_event.set()

    def request_stop(self):
        self.stopped = True
        self._pause_event.set()  # 解除暂停阻塞以便退出

    async def wait_if_paused(self):
        """如果处于暂停状态，阻塞直到恢复"""
        await self._pause_event.wait()

    def create_gate_event(self, node_id: str) -> asyncio.Event:
        """为 Gate 节点创建等待信号"""
        event = asyncio.Event()
        self._gate_events[node_id] = event
        return event

    def approve_gate(self, node_id: str):
        """审批通过 Gate 节点"""
        self._approved_gates.add(node_id)
        event = self._gate_events.get(node_id)
        if event:
            event.set()

    def is_gate_approved(self, node_id: str) -> bool:
        """检查 Gate 是否已被审批过"""
        return node_id in self._approved_gates

    def has_pending_gate(self, node_id: str) -> bool:
        event = self._gate_events.get(node_id)
        return event is not None and not event.is_set()


# 全局 Agent 状态注册表：job_id → AgentState
_agent_states: Dict[str, AgentState] = {}


def get_agent_state(job_id: str) -> AgentState:
    """获取或创建 job 的 Agent 状态"""
    if job_id not in _agent_states:
        _agent_states[job_id] = AgentState()
    return _agent_states[job_id]


def remove_agent_state(job_id: str):
    """清理 job 的 Agent 状态"""
    _agent_states.pop(job_id, None)


# ============================================================
# 核心循环
# ============================================================

async def agent_loop(
    job_id: str,
    user_goal: str,
    event_bus: EventBus,
    logger: AgentLogger,
    project_root: Path = None,
    graph: WorkflowGraph = None,
    skip_gates: bool = False,
):
    """
    Agent 核心执行循环

    Args:
        job_id: 作业 ID
        user_goal: 用户目标（自然语言）
        event_bus: 事件总线（SSE 推送）
        logger: JSONL 日志器
        project_root: 项目根目录
        graph: 可选的已有 DAG（用于崩溃恢复）
        skip_gates: 是否跳过所有 Gate（纯自动模式）
    """
    project_root = project_root or Path(__file__).parent.parent
    job_dir = project_root / "jobs" / job_id
    state = get_agent_state(job_id)

    # ----------------------------------------------------------
    # Phase 1: 创建或恢复 DAG
    # ----------------------------------------------------------
    if graph is None:
        graph = WorkflowGraph.load(job_dir)

    if graph is None:
        # 创建默认 DAG
        graph = WorkflowGraph.create_default(
            user_goal=user_goal,
            intent_config={"intent": user_goal},
        )
        graph.status = "RUNNING"
        graph.save(job_dir)

        await _emit(event_bus, logger, job_id, "graph_created", {
            "nodeCount": len(graph.nodes),
            "edgeCount": len(graph.edges),
            "userGoal": user_goal,
        })
    else:
        # 恢复：将所有 RUNNING 节点重置为 PENDING
        for node in graph.nodes:
            if node.status == NodeStatus.RUNNING:
                node.status = NodeStatus.PENDING
        graph.status = "RUNNING"
        graph.save(job_dir)

        await _emit(event_bus, logger, job_id, "graph_resumed", {
            "nodeCount": len(graph.nodes),
            "progress": graph.get_progress(),
        })

    # ----------------------------------------------------------
    # Phase 2: 主循环 — 拓扑遍历执行
    # ----------------------------------------------------------
    max_iterations = len(graph.nodes) * 4  # 防止无限循环（含重试）
    iteration = 0

    while not graph.is_complete() and iteration < max_iterations:
        iteration += 1

        # 检查停止信号
        if state.stopped:
            graph.status = "STOPPED"
            graph.save(job_dir)
            await _emit(event_bus, logger, job_id, "workflow_stopped", {})
            break

        # 检查暂停
        if state.paused:
            await _emit(event_bus, logger, job_id, "workflow_paused", {})
            await state.wait_if_paused()
            if state.stopped:
                break
            await _emit(event_bus, logger, job_id, "workflow_resumed", {})

        # 获取就绪节点
        ready_nodes = graph.get_ready_nodes()

        if not ready_nodes:
            # 没有就绪节点 — 要么在等 Gate，要么全部失败
            if graph.has_waiting_gates():
                # 等待任意一个 Gate 被审批
                await _wait_for_any_gate(state, graph)
                continue
            else:
                # 无法继续（所有路径被阻塞或失败）
                break

        # ----------------------------------------------------------
        # 处理 Gate 节点 vs 可执行节点
        # ----------------------------------------------------------
        executable = []
        for node in ready_nodes:
            if node.gate and not skip_gates and not state.is_gate_approved(node.id):
                # Gate 节点（未审批过）：标记为等待审批
                node.status = NodeStatus.WAITING_APPROVAL
                graph.save(job_dir)

                await _emit(event_bus, logger, job_id, "gate_reached", {
                    "nodeId": node.id,
                    "nodeType": node.type.value,
                    "label": node.label,
                })

                # 创建等待信号
                state.create_gate_event(node.id)
            else:
                executable.append(node)

        if not executable:
            # 所有就绪节点都是 Gate，等待审批
            if graph.has_waiting_gates():
                await _wait_for_any_gate(state, graph)
                # Gate 被审批后，节点状态变回 PENDING，下轮循环会执行它
                continue
            else:
                break

        # ----------------------------------------------------------
        # 并行执行所有可执行节点
        # ----------------------------------------------------------
        tasks = []
        for node in executable:
            tasks.append(_execute_and_update(
                node, graph, job_id, job_dir, project_root,
                user_goal, event_bus, logger, state,
            ))

        await asyncio.gather(*tasks)

        # 持久化
        graph.save(job_dir)

    # ----------------------------------------------------------
    # Phase 3: 完成
    # ----------------------------------------------------------
    if graph.is_complete():
        has_failures = graph.has_failures()
        graph.status = "COMPLETED" if not has_failures else "COMPLETED_WITH_ERRORS"
        graph.save(job_dir)

        await _emit(event_bus, logger, job_id, "workflow_complete", {
            "status": graph.status,
            "progress": graph.get_progress(),
        })
    elif not state.stopped:
        graph.status = "BLOCKED"
        graph.save(job_dir)

        await _emit(event_bus, logger, job_id, "workflow_blocked", {
            "progress": graph.get_progress(),
            "failures": [
                {"nodeId": n.id, "label": n.label, "error": n.result.get("error", "")}
                for n in graph.get_nodes_by_status(NodeStatus.FAILED)
            ],
        })

    # 关闭 SSE 流
    await event_bus.close(job_id)
    remove_agent_state(job_id)

    return graph


# ============================================================
# 内部函数
# ============================================================

async def _execute_and_update(
    node: Node,
    graph: WorkflowGraph,
    job_id: str,
    job_dir: Path,
    project_root: Path,
    user_goal: str,
    event_bus: EventBus,
    logger: AgentLogger,
    state: AgentState,
):
    """
    执行单个节点并更新状态

    在 asyncio executor 中运行同步的 execute_node()，
    避免阻塞事件循环。
    """
    # 标记 RUNNING
    node.mark_running()
    graph.save(job_dir)

    await _emit(event_bus, logger, job_id, "node_started", {
        "nodeId": node.id,
        "nodeType": node.type.value,
        "label": node.label,
    })

    # 构造执行上下文
    ctx = ExecutionContext(
        job_id=job_id,
        job_dir=job_dir,
        node=node,
        project_root=project_root,
        user_goal=user_goal,
        video_path=job_dir / "input.mp4",
    )

    # 在线程池中执行（避免阻塞 event loop）
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, execute_node, ctx)

    # 根据结果更新节点状态
    status = result.get("status", "failed")
    if status in ("success", "partial"):
        node.mark_success(result)
        await _emit(event_bus, logger, job_id, "node_completed", {
            "nodeId": node.id,
            "nodeType": node.type.value,
            "label": node.label,
            "result": _safe_summary(result),
            "duration_ms": result.get("duration_ms", 0),
        })
    else:
        node.mark_failed(result.get("error", "Unknown error"))

        if node.can_retry():
            # 自动重试
            node.reset_for_retry()
            await _emit(event_bus, logger, job_id, "node_retrying", {
                "nodeId": node.id,
                "nodeType": node.type.value,
                "attempt": node.retry_count,
                "maxRetries": node.max_retries,
                "error": result.get("error", ""),
            })
        else:
            # 重试用尽
            await _emit(event_bus, logger, job_id, "node_failed", {
                "nodeId": node.id,
                "nodeType": node.type.value,
                "label": node.label,
                "error": result.get("error", ""),
                "retryCount": node.retry_count,
            })


async def _wait_for_any_gate(state: AgentState, graph: WorkflowGraph):
    """等待任意一个 Gate 被审批"""
    waiting_nodes = graph.get_nodes_by_status(NodeStatus.WAITING_APPROVAL)
    if not waiting_nodes:
        return

    # 等待任意一个 gate event 被 set
    events = []
    for node in waiting_nodes:
        event = state._gate_events.get(node.id)
        if event:
            events.append((node, event))

    if not events:
        # 没有对应的 event，短暂等待后重试
        await asyncio.sleep(0.5)
        return

    # 用 asyncio.wait 等待任意一个完成
    wait_tasks = [
        asyncio.create_task(_wait_event(event))
        for _, event in events
    ]

    done, pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

    # 取消未完成的
    for task in pending:
        task.cancel()

    # 将审批通过的 Gate 节点重置为 PENDING
    for node, event in events:
        if event.is_set():
            node.status = NodeStatus.PENDING
            # 清理 gate event
            state._gate_events.pop(node.id, None)


async def _wait_event(event: asyncio.Event):
    """包装 event.wait() 为可取消的 task"""
    await event.wait()


async def _emit(
    event_bus: EventBus,
    logger: AgentLogger,
    job_id: str,
    event_type: str,
    data: Dict[str, Any],
):
    """发送事件到 EventBus + 写入 JSONL 日志"""
    event = AgentEvent(type=event_type, data=data)
    await event_bus.emit(job_id, event)
    logger.log(job_id, event)


def _safe_summary(result: dict) -> dict:
    """
    从执行结果中提取安全的摘要信息（用于 SSE 推送）

    去掉可能很大的 detail 字段，只保留关键数据。
    """
    safe = {}
    for key in ("status", "shots_count", "aspect_ratio", "cleaned", "skipped",
                 "total", "success", "failed", "output", "output_path",
                 "message", "duration_ms"):
        if key in result:
            safe[key] = result[key]
    return safe
