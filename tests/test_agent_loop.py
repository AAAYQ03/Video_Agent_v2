# tests/test_agent_loop.py
"""
Step 0.4 验证 — Agent Loop 单元测试

使用 mock 执行器测试 Agent Loop 的核心逻辑：
- 线性 DAG 自动执行
- 并行节点同时就绪
- Gate 暂停/恢复
- 节点失败 + 自动重试
- 暂停/停止控制
- 事件发送完整性
- DAG 持久化
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.graph_model import (
    WorkflowGraph, Node, Edge, NodeType, NodeStatus,
)
from core.node_executors import NODE_EXECUTORS, ExecutionContext
from core.event_bus import EventBus, AgentLogger, AgentEvent
from core.agent_loop import agent_loop, get_agent_state, AgentState


# ============================================================
# 辅助：Mock 执行器
# ============================================================

def _mock_success(ctx: ExecutionContext) -> dict:
    """立即成功的 mock 执行器"""
    return {"status": "success", "duration_ms": 1}


def _mock_fail_once_then_success(ctx: ExecutionContext) -> dict:
    """第一次失败，之后成功（模拟重试）"""
    # 用 retry_count 判断：0 = 第一次执行（失败），1+ = 重试（成功）
    if ctx.node.retry_count == 0:
        return {"status": "failed", "error": "transient error", "duration_ms": 1}
    return {"status": "success", "duration_ms": 1}


def _mock_always_fail(ctx: ExecutionContext) -> dict:
    """永远失败的 mock 执行器"""
    return {"status": "failed", "error": "permanent error", "duration_ms": 1}


def _make_simple_graph() -> WorkflowGraph:
    """3 节点线性图：INPUT → ANALYZE → OUTPUT（用于快速测试）"""
    nodes = [
        Node(id="n1", type=NodeType.INPUT),
        Node(id="n2", type=NodeType.ANALYZE),
        Node(id="n3", type=NodeType.OUTPUT),
    ]
    edges = [
        Edge(id="e1", source="n1", target="n2"),
        Edge(id="e2", source="n2", target="n3"),
    ]
    return WorkflowGraph(nodes=nodes, edges=edges, user_goal="test")


def _make_parallel_graph() -> WorkflowGraph:
    """
    并行图：
        INPUT
       /     \\
    NODE_A   NODE_B
       \\     /
        OUTPUT
    """
    nodes = [
        Node(id="n_in", type=NodeType.INPUT),
        Node(id="n_a", type=NodeType.WATERMARK_CLEAN),
        Node(id="n_b", type=NodeType.FILM_IR_ANALYSIS),
        Node(id="n_out", type=NodeType.OUTPUT),
    ]
    edges = [
        Edge(id="e1", source="n_in", target="n_a"),
        Edge(id="e2", source="n_in", target="n_b"),
        Edge(id="e3", source="n_a", target="n_out"),
        Edge(id="e4", source="n_b", target="n_out"),
    ]
    return WorkflowGraph(nodes=nodes, edges=edges, user_goal="test")


def _make_gate_graph() -> WorkflowGraph:
    """带 Gate 的图：INPUT → GATE_NODE → OUTPUT"""
    nodes = [
        Node(id="n1", type=NodeType.INPUT),
        Node(id="n2", type=NodeType.STORYBOARD, gate=True),  # Gate
        Node(id="n3", type=NodeType.OUTPUT),
    ]
    edges = [
        Edge(id="e1", source="n1", target="n2"),
        Edge(id="e2", source="n2", target="n3"),
    ]
    return WorkflowGraph(nodes=nodes, edges=edges, user_goal="test")


def _patch_all_executors(mock_fn):
    """用 mock 替换所有执行器"""
    return {nt: mock_fn for nt in NODE_EXECUTORS}


# ============================================================
# 测试
# ============================================================

class TestAgentLoopLinear:
    """线性 DAG 自动执行"""

    @pytest.mark.asyncio
    async def test_runs_to_completion(self):
        """简单线性图全部执行成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            assert result.is_complete()
            assert result.status in ("COMPLETED", "COMPLETED_WITH_ERRORS")
            for node in result.nodes:
                assert node.status == NodeStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_events_emitted(self):
        """执行过程中发出正确的事件序列"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            # 收集事件
            received = []

            async def collector():
                async for event in bus.subscribe("test_job"):
                    received.append(event)

            collector_task = asyncio.create_task(collector())
            await asyncio.sleep(0.01)

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            await asyncio.sleep(0.05)
            collector_task.cancel()
            try:
                await collector_task
            except asyncio.CancelledError:
                pass

            event_types = [e.type for e in received]
            # 应包含: graph_created/resumed, node_started x3, node_completed x3, workflow_complete
            assert "node_started" in event_types
            assert "node_completed" in event_types
            assert "workflow_complete" in event_types

    @pytest.mark.asyncio
    async def test_log_persisted(self):
        """事件日志写入 JSONL"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            events = logger.replay("test_job")
            assert len(events) > 0
            event_types = [e.type for e in events]
            assert "node_started" in event_types
            assert "workflow_complete" in event_types


class TestAgentLoopParallel:
    """并行节点执行"""

    @pytest.mark.asyncio
    async def test_parallel_nodes_both_execute(self):
        """并行路径的两个节点都执行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_parallel_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            assert result.is_complete()
            for node in result.nodes:
                assert node.status == NodeStatus.SUCCESS


class TestAgentLoopRetry:
    """失败重试"""

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """节点首次失败后自动重试并成功"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_fail_once_then_success)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            # 所有节点最终成功（经过重试）
            assert result.is_complete()
            for node in result.nodes:
                assert node.status == NodeStatus.SUCCESS

            # 检查有 retrying 事件
            events = logger.replay("test_job")
            event_types = [e.type for e in events]
            assert "node_retrying" in event_types

    @pytest.mark.asyncio
    async def test_permanent_failure_blocks(self):
        """永久失败的节点在重试用尽后标记 FAILED，下游不执行"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_always_fail)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            # n1 (INPUT) 失败，n2/n3 应该还是 PENDING（未执行）
            assert result.get_node("n1").status == NodeStatus.FAILED
            assert result.get_node("n2").status == NodeStatus.PENDING
            assert result.get_node("n3").status == NodeStatus.PENDING


class TestAgentLoopGate:
    """Gate 暂停/恢复"""

    @pytest.mark.asyncio
    async def test_gate_pauses_and_resumes(self):
        """Gate 节点暂停 Agent，审批后继续"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_gate_graph()

            # 等待 gate_reached 事件后再审批
            async def auto_approve():
                state = get_agent_state("test_job")
                # 等到 Gate event 被创建
                for _ in range(50):
                    if state.has_pending_gate("n2"):
                        break
                    await asyncio.sleep(0.05)
                state.approve_gate("n2")

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                approve_task = asyncio.create_task(auto_approve())
                result = await asyncio.wait_for(
                    agent_loop(
                        job_id="test_job",
                        user_goal="test",
                        event_bus=bus,
                        logger=logger,
                        project_root=Path(tmpdir),
                        graph=graph,
                        skip_gates=False,  # Gate 生效
                    ),
                    timeout=5.0,
                )
                await approve_task

            assert result.is_complete()
            for node in result.nodes:
                assert node.status == NodeStatus.SUCCESS

            # 检查有 gate_reached 事件
            events = logger.replay("test_job")
            event_types = [e.type for e in events]
            assert "gate_reached" in event_types

    @pytest.mark.asyncio
    async def test_skip_gates(self):
        """skip_gates=True 时 Gate 不生效"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_gate_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            assert result.is_complete()
            # 没有 gate_reached 事件
            events = logger.replay("test_job")
            event_types = [e.type for e in events]
            assert "gate_reached" not in event_types


class TestAgentLoopControl:
    """暂停/停止"""

    @pytest.mark.asyncio
    async def test_stop(self):
        """请求停止后 Agent 退出"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            # 立即请求停止
            state = get_agent_state("test_job")
            state.request_stop()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                result = await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            assert result.status == "STOPPED"


class TestAgentLoopPersistence:
    """DAG 持久化"""

    @pytest.mark.asyncio
    async def test_graph_saved(self):
        """执行完成后 agent_graph.json 存在且状态正确"""
        with tempfile.TemporaryDirectory() as tmpdir:
            job_dir = Path(tmpdir) / "jobs" / "test_job"
            job_dir.mkdir(parents=True)
            (job_dir / "input.mp4").write_bytes(b"fake")
            (job_dir / "final_output.mp4").write_bytes(b"fake")

            bus = EventBus()
            logger = AgentLogger(project_root=Path(tmpdir))
            graph = _make_simple_graph()

            with patch.dict(NODE_EXECUTORS, _patch_all_executors(_mock_success)):
                await agent_loop(
                    job_id="test_job",
                    user_goal="test",
                    event_bus=bus,
                    logger=logger,
                    project_root=Path(tmpdir),
                    graph=graph,
                    skip_gates=True,
                )

            # 从磁盘加载验证
            loaded = WorkflowGraph.load(job_dir)
            assert loaded is not None
            assert loaded.status in ("COMPLETED", "COMPLETED_WITH_ERRORS")
            for node in loaded.nodes:
                assert node.status == NodeStatus.SUCCESS


class TestAgentState:
    """AgentState 单元测试"""

    def test_pause_resume(self):
        s = AgentState()
        assert s.paused is False
        s.request_pause()
        assert s.paused is True
        s.request_resume()
        assert s.paused is False

    def test_stop(self):
        s = AgentState()
        s.request_stop()
        assert s.stopped is True

    @pytest.mark.asyncio
    async def test_gate_approve(self):
        s = AgentState()
        event = s.create_gate_event("n1")
        assert not event.is_set()
        assert s.has_pending_gate("n1")
        s.approve_gate("n1")
        assert event.is_set()
