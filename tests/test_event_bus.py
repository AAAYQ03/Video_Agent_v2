# tests/test_event_bus.py
"""
Step 0.2 验证 — 事件总线 + JSONL 日志 单元测试

覆盖：
- EventBus: emit/subscribe, 多 subscriber, close, 队列满处理
- AgentLogger: log/replay, 增量回放, clear, 损坏行容错
- AgentEvent: 序列化, SSE 格式
"""

import json
import asyncio
import tempfile
from pathlib import Path

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.event_bus import EventBus, AgentLogger, AgentEvent


# ============================================================
# AgentEvent
# ============================================================

class TestAgentEvent:

    def test_auto_timestamp(self):
        e = AgentEvent(type="test", data={"key": "val"})
        assert e.timestamp.endswith("Z")
        assert len(e.timestamp) > 10

    def test_to_dict(self):
        e = AgentEvent(type="node_started", data={"nodeId": "n1"})
        d = e.to_dict()
        assert d["event"] == "node_started"
        assert d["data"] == {"nodeId": "n1"}
        assert "ts" in d

    def test_from_dict(self):
        d = {"event": "node_completed", "data": {"nodeId": "n2"}, "ts": "2026-03-19T10:00:00Z"}
        e = AgentEvent.from_dict(d)
        assert e.type == "node_completed"
        assert e.data == {"nodeId": "n2"}
        assert e.timestamp == "2026-03-19T10:00:00Z"

    def test_roundtrip(self):
        e1 = AgentEvent(type="test", data={"x": 42})
        d = e1.to_dict()
        e2 = AgentEvent.from_dict(d)
        assert e2.type == e1.type
        assert e2.data == e1.data
        assert e2.timestamp == e1.timestamp

    def test_to_sse(self):
        e = AgentEvent(type="test", data={"a": 1})
        sse = e.to_sse()
        parsed = json.loads(sse)
        assert parsed["event"] == "test"
        assert parsed["data"] == {"a": 1}


# ============================================================
# EventBus
# ============================================================

class TestEventBus:

    @pytest.mark.asyncio
    async def test_emit_and_subscribe(self):
        """emit 后 subscriber 能收到事件"""
        bus = EventBus()
        received = []

        async def consumer():
            async for event in bus.subscribe("job1"):
                received.append(event)
                if len(received) >= 2:
                    break

        # 启动消费者
        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)  # 让消费者注册

        # 发送 2 个事件
        await bus.emit("job1", AgentEvent(type="ev1", data={"n": 1}))
        await bus.emit("job1", AgentEvent(type="ev2", data={"n": 2}))

        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 2
        assert received[0].type == "ev1"
        assert received[1].type == "ev2"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """多个 subscriber 各自收到完整事件流"""
        bus = EventBus()
        received_a = []
        received_b = []

        async def consumer_a():
            async for event in bus.subscribe("job1"):
                received_a.append(event)
                if len(received_a) >= 1:
                    break

        async def consumer_b():
            async for event in bus.subscribe("job1"):
                received_b.append(event)
                if len(received_b) >= 1:
                    break

        task_a = asyncio.create_task(consumer_a())
        task_b = asyncio.create_task(consumer_b())
        await asyncio.sleep(0.01)

        await bus.emit("job1", AgentEvent(type="shared_event", data={}))

        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)
        assert len(received_a) == 1
        assert len(received_b) == 1
        assert received_a[0].type == "shared_event"
        assert received_b[0].type == "shared_event"

    @pytest.mark.asyncio
    async def test_different_jobs_isolated(self):
        """不同 job 的事件互不干扰"""
        bus = EventBus()
        received = []

        async def consumer():
            async for event in bus.subscribe("job_A"):
                received.append(event)
                if len(received) >= 1:
                    break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)

        # 发到 job_B，不应该被 job_A 的 subscriber 收到
        await bus.emit("job_B", AgentEvent(type="wrong_job", data={}))
        await asyncio.sleep(0.05)
        assert len(received) == 0

        # 发到 job_A
        await bus.emit("job_A", AgentEvent(type="right_job", data={}))
        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 1
        assert received[0].type == "right_job"

    @pytest.mark.asyncio
    async def test_close_terminates_subscribers(self):
        """close 后 subscriber 退出循环"""
        bus = EventBus()
        received = []

        async def consumer():
            async for event in bus.subscribe("job1"):
                received.append(event)

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)

        await bus.emit("job1", AgentEvent(type="before_close", data={}))
        await asyncio.sleep(0.01)
        await bus.close("job1")

        await asyncio.wait_for(task, timeout=1.0)
        assert len(received) == 1
        assert received[0].type == "before_close"

    @pytest.mark.asyncio
    async def test_subscriber_count(self):
        bus = EventBus()
        assert bus.subscriber_count("job1") == 0

        async def consumer():
            async for _ in bus.subscribe("job1"):
                break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        assert bus.subscriber_count("job1") == 1

        # 发一个事件让消费者退出
        await bus.emit("job1", AgentEvent(type="x", data={}))
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.sleep(0.01)
        assert bus.subscriber_count("job1") == 0

    @pytest.mark.asyncio
    async def test_emit_no_subscribers(self):
        """没有 subscriber 时 emit 不报错"""
        bus = EventBus()
        await bus.emit("nobody", AgentEvent(type="test", data={}))
        # 不抛异常即通过

    @pytest.mark.asyncio
    async def test_active_jobs(self):
        bus = EventBus()
        assert bus.active_jobs() == []

        async def consumer():
            async for _ in bus.subscribe("job_x"):
                break

        task = asyncio.create_task(consumer())
        await asyncio.sleep(0.01)
        assert "job_x" in bus.active_jobs()

        await bus.emit("job_x", AgentEvent(type="x", data={}))
        await asyncio.wait_for(task, timeout=1.0)


# ============================================================
# AgentLogger
# ============================================================

class TestAgentLogger:

    def test_log_and_replay(self):
        """写入日志后能完整回放"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            # 写入 3 条事件
            logger.log("job1", AgentEvent(type="ev1", data={"a": 1}))
            logger.log("job1", AgentEvent(type="ev2", data={"b": 2}))
            logger.log("job1", AgentEvent(type="ev3", data={"c": 3}))

            # 回放
            events = logger.replay("job1")
            assert len(events) == 3
            assert events[0].type == "ev1"
            assert events[1].type == "ev2"
            assert events[2].type == "ev3"
            assert events[0].data == {"a": 1}

    def test_replay_nonexistent(self):
        """回放不存在的 job 返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            logger = AgentLogger(project_root=Path(tmpdir))
            events = logger.replay("nonexistent")
            assert events == []

    def test_replay_with_after_filter(self):
        """增量回放：只返回指定时间戳之后的事件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            e1 = AgentEvent(type="old", data={}, timestamp="2026-03-19T10:00:00Z")
            e2 = AgentEvent(type="new1", data={}, timestamp="2026-03-19T11:00:00Z")
            e3 = AgentEvent(type="new2", data={}, timestamp="2026-03-19T12:00:00Z")
            logger.log("job1", e1)
            logger.log("job1", e2)
            logger.log("job1", e3)

            # 只回放 10:00 之后的
            events = logger.replay("job1", after="2026-03-19T10:00:00Z")
            assert len(events) == 2
            assert events[0].type == "new1"
            assert events[1].type == "new2"

    def test_replay_corrupted_lines(self):
        """损坏的行被跳过，不影响其他事件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            log_dir = root / "jobs" / "job1"
            log_dir.mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            # 写入正常事件
            logger.log("job1", AgentEvent(type="good1", data={}))
            # 手动写入损坏行
            with open(log_dir / "agent_log.jsonl", "a") as f:
                f.write("THIS IS NOT JSON\n")
                f.write("\n")  # 空行
            # 再写一条正常事件
            logger.log("job1", AgentEvent(type="good2", data={}))

            events = logger.replay("job1")
            assert len(events) == 2
            assert events[0].type == "good1"
            assert events[1].type == "good2"

    def test_clear(self):
        """清除日志后回放为空"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            logger.log("job1", AgentEvent(type="ev", data={}))
            assert logger.event_count("job1") == 1

            logger.clear("job1")
            assert logger.event_count("job1") == 0
            assert logger.replay("job1") == []

    def test_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            assert logger.exists("job1") is False
            logger.log("job1", AgentEvent(type="ev", data={}))
            assert logger.exists("job1") is True

    def test_event_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            assert logger.event_count("job1") == 0
            logger.log("job1", AgentEvent(type="a", data={}))
            logger.log("job1", AgentEvent(type="b", data={}))
            assert logger.event_count("job1") == 2

    def test_jsonl_format(self):
        """验证文件是合法的 JSONL 格式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "jobs" / "job1").mkdir(parents=True)
            logger = AgentLogger(project_root=root)

            logger.log("job1", AgentEvent(type="ev1", data={"key": "val"}))
            logger.log("job1", AgentEvent(type="ev2", data={"num": 42}))

            path = root / "jobs" / "job1" / "agent_log.jsonl"
            lines = path.read_text().strip().split("\n")
            assert len(lines) == 2

            # 每行都是合法 JSON
            for line in lines:
                parsed = json.loads(line)
                assert "event" in parsed
                assert "data" in parsed
                assert "ts" in parsed
