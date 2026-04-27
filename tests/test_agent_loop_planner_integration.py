"""
agent_loop ↔ agent_planner 整合测试 (Phase 1.5 整合 step)

覆盖 _build_initial_graph 的三个场景：
  1. 规划器成功 → 用 LLM 生成的 DAG，发 planner_succeeded 事件
  2. 规划器失败 → fall back 到 create_default，发 planner_failed 事件
  3. use_planner=False → 直接走默认模板，不发 planner 事件

使用 monkey-patch 替换 plan_workflow 避开真实 Gemini 调用。
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

import core.agent_loop as agent_loop_mod
from core.agent_loop import _build_initial_graph
from core.event_bus import AgentLogger, EventBus
from core.graph_model import NodeStatus, NodeType, WorkflowGraph
from core.intent_dependency_table import IntentType


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def env(tmp_path):
    """提供 (event_bus, logger, project_root) 三件套。"""
    bus = EventBus()
    logger = AgentLogger(project_root=tmp_path)
    return bus, logger, tmp_path


async def _collect_events(bus: EventBus, job_id: str, max_count: int = 10, timeout: float = 0.5):
    """订阅事件总线，收集若干事件后返回。"""
    received = []

    async def collector():
        async for event in bus.subscribe(job_id):
            received.append(event)
            if len(received) >= max_count:
                break

    task = asyncio.create_task(collector())
    await asyncio.sleep(timeout)
    task.cancel()
    return received


# ============================================================
# 三个场景
# ============================================================


class TestBuildInitialGraph:
    @pytest.mark.asyncio
    async def test_planner_success_path(self, env, monkeypatch):
        """场景 1：规划器成功 → 用 LLM 生成的 DAG。"""
        bus, logger, _ = env

        # 假规划器：返回一个 STYLE_CHANGE 的最小 DAG
        def fake_plan(user_goal, **kwargs):
            from core.agent_planner import IntentClassification, build_minimal_dag

            return build_minimal_dag(
                IntentClassification(
                    type=IntentType.STYLE_CHANGE,
                    target="日系清新",
                    scope="global",
                    rationale="单测假规划",
                ),
                user_goal,
            )

        monkeypatch.setattr(agent_loop_mod, "plan_workflow", fake_plan)

        # 收集事件
        collector_task = asyncio.create_task(_collect_events(bus, "job_test", 5))
        await asyncio.sleep(0.01)

        graph = await _build_initial_graph(
            user_goal="改成日系清新风",
            user_email="alice@x.com",
            material_tag="INTERNAL",
            job_id="job_test",
            use_planner=True,
            event_bus=bus,
            logger=logger,
        )
        events = await collector_task

        # 验证：FILM_IR_ANALYSIS 是 SUCCESS（reuse），ASSET_GENERATION 是 PENDING（must_run）
        film_ir = next(n for n in graph.nodes if n.type == NodeType.FILM_IR_ANALYSIS)
        assert film_ir.status == NodeStatus.SUCCESS
        assert film_ir.result.get("reused") is True

        asset = next(n for n in graph.nodes if n.type == NodeType.ASSET_GENERATION)
        assert asset.status == NodeStatus.PENDING

        # 验证：发了 planner_succeeded 事件
        event_types = [e.type for e in events]
        assert "planner_succeeded" in event_types

    @pytest.mark.asyncio
    async def test_planner_failure_fallback(self, env, monkeypatch):
        """场景 2：规划器失败 → fall back 到 create_default，发 planner_failed。"""
        bus, logger, _ = env

        def boom(user_goal, **kwargs):
            raise ValueError("LLM 输出格式错乱，重试也失败")

        monkeypatch.setattr(agent_loop_mod, "plan_workflow", boom)

        collector_task = asyncio.create_task(_collect_events(bus, "job_test", 5))
        await asyncio.sleep(0.01)

        graph = await _build_initial_graph(
            user_goal="改成赛博朋克",
            user_email="alice@x.com",
            material_tag="INTERNAL",
            job_id="job_test",
            use_planner=True,
            event_bus=bus,
            logger=logger,
        )
        events = await collector_task

        # 验证：fall back 到默认模板——所有节点都是 PENDING（无 reuse 标记）
        for node in graph.nodes:
            assert node.status == NodeStatus.PENDING, (
                f"fall back 应生成全 PENDING DAG，{node.type} 是 {node.status}"
            )

        # 验证：发了 planner_failed 事件，错误信息可见
        failed_events = [e for e in events if e.type == "planner_failed"]
        assert len(failed_events) == 1
        assert "格式错乱" in failed_events[0].data["error"]
        assert failed_events[0].data["fallback"] == "create_default"

    @pytest.mark.asyncio
    async def test_use_planner_false_skips_llm(self, env, monkeypatch):
        """场景 3：use_planner=False → 直接走默认模板，不调 LLM。"""
        bus, logger, _ = env

        # 让 plan_workflow 调用即抛异常——验证它根本没被调
        def must_not_call(user_goal, **kwargs):
            raise AssertionError("use_planner=False 时不应调用 plan_workflow")

        monkeypatch.setattr(agent_loop_mod, "plan_workflow", must_not_call)

        collector_task = asyncio.create_task(_collect_events(bus, "job_test", 3))
        await asyncio.sleep(0.01)

        graph = await _build_initial_graph(
            user_goal="test",
            user_email="alice@x.com",
            material_tag="INTERNAL",
            job_id="job_test",
            use_planner=False,
            event_bus=bus,
            logger=logger,
        )
        events = await collector_task

        # 默认模板：全 PENDING
        assert all(n.status == NodeStatus.PENDING for n in graph.nodes)

        # 没有 planner 事件
        event_types = [e.type for e in events]
        assert "planner_succeeded" not in event_types
        assert "planner_failed" not in event_types

    @pytest.mark.asyncio
    async def test_planner_audit_context_propagation(self, env, monkeypatch):
        """user_email / material_tag / job_id 应透传给 plan_workflow。"""
        bus, logger, _ = env
        captured = {}

        def fake_plan(user_goal, **kwargs):
            captured.update(kwargs)
            return WorkflowGraph.create_default(user_goal=user_goal)

        monkeypatch.setattr(agent_loop_mod, "plan_workflow", fake_plan)

        await _build_initial_graph(
            user_goal="test",
            user_email="alice@x.com",
            material_tag="VIRAL_REF",
            job_id="job_xyz",
            use_planner=True,
            event_bus=bus,
            logger=logger,
        )

        assert captured.get("user_email") == "alice@x.com"
        assert captured.get("material_tag") == "VIRAL_REF"
        assert captured.get("job_id") == "job_xyz"
