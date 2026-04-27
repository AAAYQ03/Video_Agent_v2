"""
Phase 3.4 评估器单测

覆盖：
  1. _parse_eval_json 的 rubric schema 校验（合法/缺维度/分数越界/JSON 坏）
  2. evaluate_output 的失败重试（首次坏 JSON → 第二次成功）
  3. is_evaluatable 节点过滤
  4. decide_retry_strategy 的多 issue 合并 + 权重排序
  5. record_retry_attempt 历史持久化
  6. agent_loop._evaluate_and_maybe_retry 三个分支
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import core.agent_evaluator as evaluator
from core.agent_evaluator import (
    EVAL_RUBRIC_VISUAL,
    EvaluationResult,
    NODE_RUBRIC,
    RetryStrategy,
    decide_retry_strategy,
    evaluate_output,
    is_evaluatable,
    record_retry_attempt,
)
from core.graph_model import Node, NodeStatus, NodeType


# ============================================================
# 工具
# ============================================================


def _make_visual_node(node_type: NodeType = NodeType.VIDEO_GENERATION, **config) -> Node:
    return Node(
        id="node_test",
        type=node_type,
        config=dict(config),
        position={"x": 0.0, "y": 0.0},
    )


def _full_score_response(score: float = 9.0, feedback: str = "ok") -> str:
    """构造一个所有维度都给定相同分数的合法 JSON 响应。"""
    body = {name: score for name in EVAL_RUBRIC_VISUAL}
    body["feedback"] = feedback
    import json
    return json.dumps(body)


# ============================================================
# is_evaluatable
# ============================================================


class TestIsEvaluatable:
    def test_visual_nodes_evaluatable(self):
        for nt in [
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
            NodeType.SINGLE_SHOT_STYLIZE,
            NodeType.SINGLE_SHOT_VIDEO,
        ]:
            assert is_evaluatable(Node(id="x", type=nt))

    def test_non_visual_nodes_not_evaluatable(self):
        for nt in [NodeType.INPUT, NodeType.ANALYZE, NodeType.MERGE, NodeType.OUTPUT]:
            assert not is_evaluatable(Node(id="x", type=nt))


# ============================================================
# _parse_eval_json
# ============================================================


class TestParseEvalJson:
    def test_valid_json(self):
        raw = _full_score_response(score=8.5, feedback="不错")
        r = evaluator._parse_eval_json(raw, EVAL_RUBRIC_VISUAL)
        assert r.passed is True  # 8.5 ≥ 所有阈值
        assert r.feedback == "不错"
        assert all(s == 8.5 for s in r.scores.values())

    def test_with_code_fence(self):
        body = _full_score_response()
        raw = f"```json\n{body}\n```"
        r = evaluator._parse_eval_json(raw, EVAL_RUBRIC_VISUAL)
        assert r.passed is True

    def test_below_threshold_creates_issue(self):
        # character_consistency 阈值 7.0，给 5.0 应触发 issue
        import json
        body = {name: 9.0 for name in EVAL_RUBRIC_VISUAL}
        body["character_consistency"] = 5.0
        body["feedback"] = "x"
        r = evaluator._parse_eval_json(json.dumps(body), EVAL_RUBRIC_VISUAL)
        assert r.passed is False
        assert "character_consistency" in r.issues

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="非合法 JSON"):
            evaluator._parse_eval_json("not json", EVAL_RUBRIC_VISUAL)

    def test_missing_dimension_raises(self):
        import json
        body = {name: 9.0 for name in list(EVAL_RUBRIC_VISUAL.keys())[:-1]}
        body["feedback"] = "x"
        with pytest.raises(ValueError, match="缺维度"):
            evaluator._parse_eval_json(json.dumps(body), EVAL_RUBRIC_VISUAL)

    def test_score_out_of_range_raises(self):
        import json
        body = {name: 9.0 for name in EVAL_RUBRIC_VISUAL}
        body["character_consistency"] = 11.5
        body["feedback"] = "x"
        with pytest.raises(ValueError, match="越界"):
            evaluator._parse_eval_json(json.dumps(body), EVAL_RUBRIC_VISUAL)

    def test_weighted_score_computed(self):
        # 全部 5.0 → 加权应也是 5.0（权重和 = 1.0）
        import json
        body = {name: 5.0 for name in EVAL_RUBRIC_VISUAL}
        body["feedback"] = "x"
        r = evaluator._parse_eval_json(json.dumps(body), EVAL_RUBRIC_VISUAL)
        assert abs(r.weighted_score - 5.0) < 0.001


# ============================================================
# evaluate_output 失败重试
# ============================================================


class TestEvaluateOutputRetry:
    def test_first_attempt_success(self, monkeypatch):
        canned = _full_score_response(score=8.0)
        calls = []

        def fake(prompt, **kwargs):
            calls.append(prompt)
            return canned

        monkeypatch.setattr(evaluator, "_invoke_evaluator_llm", fake)

        node = _make_visual_node()
        r = evaluate_output(node, {"output_path": "x.mp4"})
        assert r.passed is True
        assert len(calls) == 1

    def test_retry_on_bad_json(self, monkeypatch):
        responses = ["broken", _full_score_response(score=8.0)]
        idx = [0]

        def fake(prompt, **kwargs):
            r = responses[idx[0]]
            idx[0] += 1
            return r

        monkeypatch.setattr(evaluator, "_invoke_evaluator_llm", fake)
        node = _make_visual_node()
        r = evaluate_output(node, {})
        assert r.passed is True
        assert idx[0] == 2

    def test_two_failures_raise(self, monkeypatch):
        monkeypatch.setattr(
            evaluator, "_invoke_evaluator_llm",
            lambda p, **kw: "not json"
        )
        with pytest.raises(ValueError):
            evaluate_output(_make_visual_node(), {})

    def test_non_evaluatable_raises(self):
        node = Node(id="x", type=NodeType.MERGE)
        with pytest.raises(ValueError, match="不可评估"):
            evaluate_output(node, {})


# ============================================================
# decide_retry_strategy
# ============================================================


class TestDecideRetryStrategy:
    def _result(self, scores: dict) -> EvaluationResult:
        rubric = EVAL_RUBRIC_VISUAL
        issues = [k for k, v in scores.items() if v < rubric[k].threshold]
        weighted = sum(scores[k] * rubric[k].weight for k in scores)
        return EvaluationResult(
            scores=scores, issues=issues,
            weighted_score=weighted,
            passed=(len(issues) == 0),
            feedback="",
        )

    def test_no_issues_returns_noop(self):
        node = _make_visual_node()
        result = self._result({k: 9.0 for k in EVAL_RUBRIC_VISUAL})
        s = decide_retry_strategy(node, result)
        assert s.name == "noop"

    def test_single_issue_returns_specific_strategy(self):
        node = _make_visual_node()
        scores = {k: 9.0 for k in EVAL_RUBRIC_VISUAL}
        scores["character_consistency"] = 4.0  # 失败
        s = decide_retry_strategy(node, self._result(scores))
        assert "strengthen_character_anchor" in s.name
        assert "character" in s.prompt_modifier or "角色" in s.prompt_modifier
        assert s.triggered_by == ["character_consistency"]

    def test_multiple_issues_combined_by_weight(self):
        """多 issue 时按权重降序合并 prompt_modifier。"""
        node = _make_visual_node()
        scores = {k: 9.0 for k in EVAL_RUBRIC_VISUAL}
        scores["character_consistency"] = 4.0  # weight 0.30
        scores["lighting_coherence"] = 4.0     # weight 0.10
        s = decide_retry_strategy(node, self._result(scores))

        # 两个策略名都应在 + 拼接里
        assert "strengthen_character_anchor" in s.name
        assert "match_scene_lighting" in s.name
        # character (高权重) 应排在前面
        assert s.triggered_by[0] == "character_consistency"

    def test_residual_artifacts_includes_extra_config(self):
        node = _make_visual_node()
        scores = {k: 9.0 for k in EVAL_RUBRIC_VISUAL}
        scores["residual_artifacts"] = 3.0
        s = decide_retry_strategy(node, self._result(scores))
        assert s.extra_config.get("emphasize_clean_output") is True


# ============================================================
# record_retry_attempt
# ============================================================


class TestRecordRetryAttempt:
    def test_history_appends_to_node_config(self):
        node = _make_visual_node()
        eval_r = EvaluationResult(
            scores={"character_consistency": 5.0},
            issues=["character_consistency"],
            weighted_score=5.0, passed=False, feedback="坏",
        )
        strategy = RetryStrategy(name="s1", prompt_modifier="hint")

        record_retry_attempt(node, eval_r, strategy)

        history = node.config["_retry_history"]
        assert len(history) == 1
        assert history[0]["strategy_name"] == "s1"
        assert history[0]["scores"]["character_consistency"] == 5.0
        assert node.config["_last_retry_strategy"]["name"] == "s1"

    def test_multiple_attempts_accumulate(self):
        node = _make_visual_node()
        eval_r = EvaluationResult(
            scores={}, issues=[], weighted_score=5.0, passed=False, feedback="",
        )
        record_retry_attempt(node, eval_r, RetryStrategy(name="s1", prompt_modifier=""))
        node.retry_count = 1
        record_retry_attempt(node, eval_r, RetryStrategy(name="s2", prompt_modifier=""))

        assert len(node.config["_retry_history"]) == 2
        assert node.config["_retry_history"][0]["attempt"] == 1
        assert node.config["_retry_history"][1]["attempt"] == 2
        assert node.config["_last_retry_strategy"]["name"] == "s2"


# ============================================================
# agent_loop._evaluate_and_maybe_retry 集成
# ============================================================


class TestEvaluateAndMaybeRetryIntegration:
    """
    单元粒度测 _evaluate_and_maybe_retry 三个分支：
      1. 评估通过 → 返回 True，发 evaluation_done
      2. 评估不过 + 还有重试预算 → 重置 PENDING + 发 quality_issue, 返回 False
      3. 评估不过 + 用尽预算 → 标 FAILED + 发 node_failed, 返回 False
    """

    @pytest.mark.asyncio
    async def test_passed_returns_true(self, monkeypatch, tmp_path):
        from core.agent_loop import _evaluate_and_maybe_retry
        from core.event_bus import AgentLogger, EventBus
        from core.graph_model import WorkflowGraph

        bus = EventBus()
        logger = AgentLogger(project_root=tmp_path)
        graph = WorkflowGraph(nodes=[], edges=[])

        node = _make_visual_node()
        node.status = NodeStatus.SUCCESS  # 模拟 agent_loop 的真实调用顺序

        # mock evaluator → 直接返回通过的 EvaluationResult
        monkeypatch.setattr(evaluator, "_invoke_evaluator_llm",
                            lambda p, **kw: _full_score_response(score=9.0))

        result = await _evaluate_and_maybe_retry(
            node=node, graph=graph, result={"x": 1},
            main_job_dir=tmp_path, job_id="job_test",
            user_email="u@x.com", material_tag="INTERNAL",
            event_bus=bus, logger=logger,
        )
        assert result is True
        assert node.status == NodeStatus.SUCCESS  # 通过则不重置

    @pytest.mark.asyncio
    async def test_failed_with_budget_resets_to_pending(
        self, monkeypatch, tmp_path,
    ):
        from core.agent_loop import _evaluate_and_maybe_retry
        from core.event_bus import AgentLogger, EventBus
        from core.graph_model import WorkflowGraph

        bus = EventBus()
        logger = AgentLogger(project_root=tmp_path)
        graph = WorkflowGraph(nodes=[], edges=[])

        # 节点：max_retries=2, retry_count=0（还有预算）；先标 SUCCESS（execute 后的状态）
        node = _make_visual_node()
        node.status = NodeStatus.SUCCESS
        node.max_retries = 2
        node.retry_count = 0

        # mock 评估器 → 不通过
        import json
        bad_scores = {k: 9.0 for k in EVAL_RUBRIC_VISUAL}
        bad_scores["character_consistency"] = 3.0
        bad_scores["feedback"] = "角色变形"
        monkeypatch.setattr(
            evaluator, "_invoke_evaluator_llm",
            lambda p, **kw: json.dumps(bad_scores),
        )

        result = await _evaluate_and_maybe_retry(
            node=node, graph=graph, result={},
            main_job_dir=tmp_path, job_id="job_test",
            user_email="u@x.com", material_tag="INTERNAL",
            event_bus=bus, logger=logger,
        )
        assert result is False                 # 返回 False 让调用方不发 node_completed
        assert node.status == NodeStatus.PENDING  # 已重置等待重跑
        assert node.retry_count == 1
        assert "_retry_history" in node.config
        assert "_last_retry_strategy" in node.config

    @pytest.mark.asyncio
    async def test_failed_without_budget_marks_failed(
        self, monkeypatch, tmp_path,
    ):
        from core.agent_loop import _evaluate_and_maybe_retry
        from core.event_bus import AgentLogger, EventBus
        from core.graph_model import WorkflowGraph

        bus = EventBus()
        logger = AgentLogger(project_root=tmp_path)
        graph = WorkflowGraph(nodes=[], edges=[])

        # 节点已经用完 retries
        node = _make_visual_node()
        node.status = NodeStatus.SUCCESS
        node.max_retries = 2
        node.retry_count = 2

        import json
        bad_scores = {k: 9.0 for k in EVAL_RUBRIC_VISUAL}
        bad_scores["style_consistency"] = 3.0
        bad_scores["feedback"] = "风格不对"
        monkeypatch.setattr(
            evaluator, "_invoke_evaluator_llm",
            lambda p, **kw: json.dumps(bad_scores),
        )

        result = await _evaluate_and_maybe_retry(
            node=node, graph=graph, result={},
            main_job_dir=tmp_path, job_id="job_test",
            user_email="u@x.com", material_tag="INTERNAL",
            event_bus=bus, logger=logger,
        )
        assert result is False
        assert node.status == NodeStatus.FAILED  # 熔断
        # 错误信息含"质量评估"中文（agent_loop 里发的中文消息）
        assert "质量" in (node.result.get("error") or "")

    @pytest.mark.asyncio
    async def test_evaluator_exception_degrades_to_pass(
        self, monkeypatch, tmp_path,
    ):
        """评估器自身挂了不能阻塞节点——降级放行 + 发 evaluation_skipped。"""
        from core.agent_loop import _evaluate_and_maybe_retry
        from core.event_bus import AgentLogger, EventBus
        from core.graph_model import WorkflowGraph

        bus = EventBus()
        logger = AgentLogger(project_root=tmp_path)
        graph = WorkflowGraph(nodes=[], edges=[])

        node = _make_visual_node()
        node.status = NodeStatus.SUCCESS

        def boom(*args, **kwargs):
            raise RuntimeError("LLM gateway down")

        monkeypatch.setattr(evaluator, "_invoke_evaluator_llm", boom)

        result = await _evaluate_and_maybe_retry(
            node=node, graph=graph, result={},
            main_job_dir=tmp_path, job_id="job_test",
            user_email="u@x.com", material_tag="INTERNAL",
            event_bus=bus, logger=logger,
        )
        assert result is True  # 降级放行
        assert node.status == NodeStatus.SUCCESS  # 不动
