"""
agent_planner 的单元测试

策略：用 monkey-patch 替换 _invoke_classifier_llm，避开真实 Gemini 调用。
覆盖：
  - JSON 解析/校验（合法、代码块包装、缺字段、非法 type）
  - classify_intent 失败重试逻辑
  - build_minimal_dag 的节点状态正确性（reuse → SUCCESS, must_run → PENDING）
  - plan_workflow 端到端拼装
"""
from __future__ import annotations

import json

import pytest

import core.agent_planner as planner
from core.graph_model import NodeStatus, NodeType
from core.intent_dependency_table import IntentType


# ============================================================
# JSON 解析与 schema 校验
# ============================================================


class TestParseIntentJson:
    def test_valid_json(self):
        raw = (
            '{"type":"STYLE_CHANGE","target":"日系清新",'
            '"scope":"global","rationale":"用户说改成日系"}'
        )
        result = planner._parse_intent_json(raw)
        assert result.type == IntentType.STYLE_CHANGE
        assert result.target == "日系清新"
        assert result.scope == "global"

    def test_with_code_fence(self):
        """LLM 经常会包 ``` 代码块，必须能容错。"""
        raw = (
            "```json\n"
            '{"type":"STYLE_CHANGE","target":"x","scope":"global","rationale":"y"}\n'
            "```"
        )
        result = planner._parse_intent_json(raw)
        assert result.type == IntentType.STYLE_CHANGE

    def test_with_leading_whitespace(self):
        raw = (
            '   \n  {"type":"PLOT_REWRITE","target":"x",'
            '"scope":"global","rationale":"y"}  '
        )
        result = planner._parse_intent_json(raw)
        assert result.type == IntentType.PLOT_REWRITE

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="非合法 JSON"):
            planner._parse_intent_json("this is not json")

    def test_non_object_raises(self):
        with pytest.raises(ValueError, match="不是对象"):
            planner._parse_intent_json("[1, 2, 3]")

    def test_missing_field_raises(self):
        raw = '{"type":"STYLE_CHANGE","target":"x"}'  # 缺 scope, rationale
        with pytest.raises(ValueError, match="缺字段"):
            planner._parse_intent_json(raw)

    def test_invalid_type_value_raises(self):
        raw = (
            '{"type":"FAKE_TYPE","target":"x","scope":"global","rationale":"y"}'
        )
        with pytest.raises(ValueError, match="不在 IntentType 枚举"):
            planner._parse_intent_json(raw)


# ============================================================
# classify_intent: 重试逻辑
# ============================================================


class TestClassifyIntent:
    def _patch_llm(self, monkeypatch, responses_or_func):
        """工具：把 _invoke_classifier_llm 替换成给定回调或固定响应序列。"""
        if callable(responses_or_func):
            monkeypatch.setattr(planner, "_invoke_classifier_llm", responses_or_func)
        else:
            iter_resp = iter(responses_or_func)
            monkeypatch.setattr(
                planner,
                "_invoke_classifier_llm",
                lambda prompt, **kw: next(iter_resp),
            )

    def test_first_attempt_success(self, monkeypatch):
        canned = (
            '{"type":"STYLE_CHANGE","target":"日系清新",'
            '"scope":"global","rationale":"用户说改成日系"}'
        )
        calls = []

        def fake(prompt, **kwargs):
            calls.append(prompt)
            return canned

        self._patch_llm(monkeypatch, fake)

        result = planner.classify_intent("把视频改成日系清新风")
        assert result.type == IntentType.STYLE_CHANGE
        assert result.target == "日系清新"
        assert len(calls) == 1, "成功就不应重试"

    def test_retry_on_bad_json(self, monkeypatch):
        responses = [
            "this is not json at all",  # 第 1 次：失败
            '{"type":"CHARACTER_REPLACE","target":"女战士","scope":"global","rationale":"用户要换主角"}',
        ]
        self._patch_llm(monkeypatch, responses)

        result = planner.classify_intent("把主角换成女战士")
        assert result.type == IntentType.CHARACTER_REPLACE
        assert result.target == "女战士"

    def test_retry_on_missing_field(self, monkeypatch):
        responses = [
            '{"type":"STYLE_CHANGE"}',  # 缺字段
            '{"type":"STYLE_CHANGE","target":"x","scope":"global","rationale":"y"}',
        ]
        self._patch_llm(monkeypatch, responses)

        result = planner.classify_intent("test")
        assert result.type == IntentType.STYLE_CHANGE

    def test_two_failures_raise(self, monkeypatch):
        self._patch_llm(monkeypatch, ["broken", "still broken"])
        with pytest.raises(ValueError):
            planner.classify_intent("test")

    def test_passes_audit_context_through(self, monkeypatch):
        """user_email / material_tag / job_id 应透传到底层 LLM 调用。"""
        captured = {}

        def fake(prompt, *, user_email, material_tag, job_id):
            captured["user_email"] = user_email
            captured["material_tag"] = material_tag
            captured["job_id"] = job_id
            return '{"type":"STYLE_CHANGE","target":"x","scope":"global","rationale":"y"}'

        monkeypatch.setattr(planner, "_invoke_classifier_llm", fake)

        planner.classify_intent(
            "test",
            user_email="alice@x.com",
            material_tag="VIRAL_REF",
            job_id="job_abc",
        )
        assert captured == {
            "user_email": "alice@x.com",
            "material_tag": "VIRAL_REF",
            "job_id": "job_abc",
        }


# ============================================================
# build_minimal_dag: 节点状态正确性
# ============================================================


class TestBuildMinimalDag:
    def _make_intent(self, intent_type: IntentType, target="测试", scope="global"):
        return planner.IntentClassification(
            type=intent_type,
            target=target,
            scope=scope,
            rationale="单测",
        )

    def test_style_change_marks_film_ir_reused(self):
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.STYLE_CHANGE), "改风格"
        )
        film_ir = next(n for n in graph.nodes if n.type == NodeType.FILM_IR_ANALYSIS)
        assert film_ir.status == NodeStatus.SUCCESS
        assert film_ir.result.get("reused") is True

    def test_style_change_keeps_intent_injection_pending(self):
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.STYLE_CHANGE), "改风格"
        )
        intent_node = next(
            n for n in graph.nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert intent_node.status == NodeStatus.PENDING

    def test_intent_target_lands_in_intent_node_config(self):
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.STYLE_CHANGE, target="赛博朋克"),
            "改成赛博朋克",
        )
        intent_node = next(
            n for n in graph.nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert intent_node.config.get("intent") == "赛博朋克"
        assert intent_node.config.get("intent_type") == "STYLE_CHANGE"

    def test_cut_adjust_only_merge_and_output_pending(self):
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.CUT_ADJUST, target="缩短"), "缩短到 20 秒"
        )
        pending_types = {
            n.type for n in graph.nodes if n.status == NodeStatus.PENDING
        }
        assert pending_types == {NodeType.MERGE, NodeType.OUTPUT}

    def test_character_replace_keeps_asset_generation_pending(self):
        """CHARACTER_LEDGER 当前不在 create_default 拓扑里（是 FILM_IR 子步骤），
        所以验证 CHARACTER_REPLACE 改写下游节点 ASSET_GENERATION 处于 PENDING。"""
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.CHARACTER_REPLACE, target="女战士"),
            "换主角",
        )
        asset_node = next(
            n for n in graph.nodes if n.type == NodeType.ASSET_GENERATION
        )
        assert asset_node.status == NodeStatus.PENDING

    def test_character_replace_keeps_intent_injection_reused(self):
        """换角色不动风格意图 → INTENT_INJECTION 应复用。"""
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.CHARACTER_REPLACE), "换主角"
        )
        intent_node = next(
            n for n in graph.nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert intent_node.status == NodeStatus.SUCCESS

    def test_plot_rewrite_reruns_film_ir(self):
        graph = planner.build_minimal_dag(
            self._make_intent(IntentType.PLOT_REWRITE, target="新剧情"), "改剧情"
        )
        film_ir = next(n for n in graph.nodes if n.type == NodeType.FILM_IR_ANALYSIS)
        assert film_ir.status == NodeStatus.PENDING


# ============================================================
# plan_workflow: 端到端
# ============================================================


class TestPlanWorkflow:
    def test_e2e_with_mocked_llm(self, monkeypatch):
        canned = (
            '{"type":"CHARACTER_REPLACE","target":"女战士",'
            '"scope":"global","rationale":"用户要换主角形象"}'
        )
        monkeypatch.setattr(
            planner,
            "_invoke_classifier_llm",
            lambda prompt, **kw: canned,
        )

        graph = planner.plan_workflow(
            "把主角换成一个女战士",
            user_email="creator1@example.com",
            job_id="job_abc",
        )

        # ASSET_GENERATION 必跑（生成新角色资产）
        asset_node = next(
            n for n in graph.nodes if n.type == NodeType.ASSET_GENERATION
        )
        assert asset_node.status == NodeStatus.PENDING

        # INTENT_INJECTION 复用（风格意图不变）
        intent_node = next(
            n for n in graph.nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert intent_node.status == NodeStatus.SUCCESS

        # user_goal 正确传给 graph
        assert graph.user_goal == "把主角换成一个女战士"

    def test_e2e_intent_target_propagates(self, monkeypatch):
        canned = (
            '{"type":"STYLE_CHANGE","target":"复古胶片",'
            '"scope":"global","rationale":"复古风格"}'
        )
        monkeypatch.setattr(
            planner,
            "_invoke_classifier_llm",
            lambda prompt, **kw: canned,
        )

        graph = planner.plan_workflow("改成复古胶片质感")

        intent_node = next(
            n for n in graph.nodes if n.type == NodeType.INTENT_INJECTION
        )
        assert intent_node.config.get("intent") == "复古胶片"
