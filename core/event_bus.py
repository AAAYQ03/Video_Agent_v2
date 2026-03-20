# core/event_bus.py
"""
Event Bus + Agent Logger
========================
Agent Workflow Canvas (Mode 2) 的实时事件系统。

EventBus: 基于 asyncio.Queue 的进程内发布/订阅，驱动 SSE 推送。
AgentLogger: Append-only JSONL 日志，支持断线重连后的事件回放。
"""

import json
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, AsyncIterator
from dataclasses import dataclass, field


# ============================================================
# 事件数据类
# ============================================================

@dataclass
class AgentEvent:
    """一个 Agent 事件"""
    type: str               # 事件类型（graph_created, node_started, ...）
    data: Dict[str, Any]    # 事件载荷
    timestamp: str = ""     # ISO 时间戳

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.timestamp,
            "event": self.type,
            "data": self.data,
        }

    def to_sse(self) -> str:
        """格式化为 SSE 数据行"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AgentEvent":
        return cls(
            type=d["event"],
            data=d.get("data", {}),
            timestamp=d.get("ts", ""),
        )


# ============================================================
# EventBus — 进程内发布/订阅
# ============================================================

class EventBus:
    """
    基于 asyncio.Queue 的进程内事件总线

    用法:
        bus = EventBus()
        # 发布
        await bus.emit("job_123", AgentEvent(type="node_started", data={"nodeId": "n1"}))
        # 订阅（SSE endpoint 中使用）
        async for event in bus.subscribe("job_123"):
            yield event
    """

    def __init__(self):
        # job_id → {subscriber_id → asyncio.Queue}
        self._subscribers: Dict[str, Dict[str, asyncio.Queue]] = {}
        self._sub_counter: int = 0

    async def emit(self, job_id: str, event: AgentEvent):
        """
        发布事件到指定 job 的所有订阅者

        非阻塞：如果某个 subscriber 的队列满了，丢弃该事件（不阻塞发布者）
        """
        subs = self._subscribers.get(job_id, {})
        for queue in subs.values():
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 慢消费者，丢弃

    def emit_sync(self, job_id: str, event: AgentEvent):
        """
        同步版本的 emit，用于非 async 上下文

        尝试获取当前 event loop 并调度，如果没有 loop 则静默跳过。
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.emit(job_id, event))
        except RuntimeError:
            # 没有 running loop（纯同步上下文），静默跳过
            pass

    async def subscribe(self, job_id: str, max_queue_size: int = 256) -> AsyncIterator[AgentEvent]:
        """
        订阅指定 job 的事件流

        使用 async for 消费：
            async for event in bus.subscribe("job_123"):
                ...

        subscriber 断开连接后自动清理。
        """
        self._sub_counter += 1
        sub_id = f"sub_{self._sub_counter}"
        queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)

        if job_id not in self._subscribers:
            self._subscribers[job_id] = {}
        self._subscribers[job_id][sub_id] = queue

        try:
            while True:
                event = await queue.get()
                # 收到 None 表示流结束
                if event is None:
                    break
                yield event
        finally:
            # 清理
            subs = self._subscribers.get(job_id, {})
            subs.pop(sub_id, None)
            if not subs and job_id in self._subscribers:
                del self._subscribers[job_id]

    async def close(self, job_id: str):
        """
        关闭指定 job 的所有订阅（向所有 subscriber 发送 None 终止信号）

        在 workflow_complete 或 workflow_failed 时调用。
        """
        subs = self._subscribers.get(job_id, {})
        for queue in subs.values():
            try:
                queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, job_id: str) -> int:
        """返回指定 job 的当前订阅者数量"""
        return len(self._subscribers.get(job_id, {}))

    def active_jobs(self) -> List[str]:
        """返回有活跃订阅者的 job_id 列表"""
        return [jid for jid, subs in self._subscribers.items() if subs]


# ============================================================
# AgentLogger — Append-only JSONL 日志
# ============================================================

class AgentLogger:
    """
    Append-only JSONL 事件日志

    每个 job 一个文件：jobs/{job_id}/agent_log.jsonl
    用于：
    1. 事件溯源 — 完整记录 Agent 的每一步操作
    2. 断线重连 — 客户端重连后回放历史事件恢复状态
    3. 调试 — 精确到毫秒的执行时间线
    """

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or Path(__file__).parent.parent

    def _log_path(self, job_id: str) -> Path:
        return self.project_root / "jobs" / job_id / "agent_log.jsonl"

    def log(self, job_id: str, event: AgentEvent):
        """追加写入一条事件到 JSONL 文件"""
        path = self._log_path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def replay(self, job_id: str, after: Optional[str] = None) -> List[AgentEvent]:
        """
        回放历史事件

        Args:
            job_id: 作业 ID
            after: 可选的时间戳过滤 — 只返回此时间戳之后的事件（用于增量重连）

        Returns:
            事件列表（按时间顺序）
        """
        path = self._log_path(job_id)
        if not path.exists():
            return []

        events = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    event = AgentEvent.from_dict(data)
                    if after and event.timestamp <= after:
                        continue
                    events.append(event)
                except (json.JSONDecodeError, KeyError):
                    continue  # 跳过损坏的行
        return events

    def clear(self, job_id: str):
        """清除指定 job 的日志（用于重新执行）"""
        path = self._log_path(job_id)
        if path.exists():
            path.unlink()

    def exists(self, job_id: str) -> bool:
        """检查日志文件是否存在"""
        return self._log_path(job_id).exists()

    def event_count(self, job_id: str) -> int:
        """返回日志中的事件数量"""
        path = self._log_path(job_id)
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())


# ============================================================
# 全局单例
# ============================================================

# Agent 模式的全局事件总线（整个进程共享一个实例）
agent_event_bus = EventBus()

# Agent 模式的全局日志器
agent_logger = AgentLogger()
