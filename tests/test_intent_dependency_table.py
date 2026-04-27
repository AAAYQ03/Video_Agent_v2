"""
意图分类 + 依赖表的单元测试

覆盖：
  - 表结构完整性（所有 IntentType 都有规则、字段一致）
  - lookup() 的查询语义（枚举/字符串/未知）
  - 每个意图的核心规则（防回归——这些规则改了说明业务语义在变）
"""
from __future__ import annotations

import pytest

from core.graph_model import NodeType
from core.intent_dependency_table import (
    DEPENDENCY_TABLE,
    DependencyRule,
    IntentType,
    all_known_node_types_in_table,
    lookup,
)


# ============================================================
# 表结构完整性
# ============================================================


class TestTableStructure:
    def test_all_intents_have_rules(self):
        """每种 IntentType 都必须在表里有对应规则。"""
        for intent in IntentType:
            assert intent in DEPENDENCY_TABLE, f"{intent} 缺规则"

    def test_no_node_in_both_must_run_and_reuse(self):
        """同一节点不能同时是必跑和可复用——逻辑矛盾。"""
        for intent, rule in DEPENDENCY_TABLE.items():
            overlap = rule.must_run_set & rule.reuse_set
            assert not overlap, f"{intent} 的 must_run 与 reuse 重叠: {overlap}"

    def test_each_rule_has_input_and_output(self):
        """每个意图的执行计划都必须包含起点 INPUT 和终点 OUTPUT。"""
        for intent, rule in DEPENDENCY_TABLE.items():
            all_nodes = rule.must_run_set | rule.reuse_set
            assert NodeType.INPUT in all_nodes, f"{intent} 缺 INPUT"
            assert NodeType.OUTPUT in all_nodes, f"{intent} 缺 OUTPUT"

    def test_each_rule_has_description(self):
        for intent, rule in DEPENDENCY_TABLE.items():
            assert rule.description and len(rule.description) > 5, (
                f"{intent} description 过短"
            )

    def test_must_run_not_empty(self):
        """每个意图必须至少跑一个节点（否则不叫'修改'）。"""
        for intent, rule in DEPENDENCY_TABLE.items():
            assert len(rule.must_run) > 0, f"{intent} must_run 为空"

    def test_must_run_includes_output(self):
        """OUTPUT 节点必须在 must_run（最终产物总要落盘）。"""
        for intent, rule in DEPENDENCY_TABLE.items():
            assert NodeType.OUTPUT in rule.must_run_set, (
                f"{intent} 必须重跑 OUTPUT"
            )


# ============================================================
# lookup() 查询语义
# ============================================================


class TestLookup:
    def test_by_enum(self):
        rule = lookup(IntentType.STYLE_CHANGE)
        assert isinstance(rule, DependencyRule)
        assert NodeType.ASSET_GENERATION in rule.must_run_set

    def test_by_string(self):
        """支持字符串以便从 LLM JSON 直接查表。"""
        rule = lookup("STYLE_CHANGE")
        assert NodeType.ASSET_GENERATION in rule.must_run_set

    def test_unknown_string_raises(self):
        with pytest.raises(ValueError):
            lookup("FAKE_INTENT_TYPE")

    def test_lookup_returns_same_object_consistently(self):
        """两次查同一意图返回相同规则对象（frozen dataclass 可哈希）。"""
        a = lookup(IntentType.STYLE_CHANGE)
        b = lookup(IntentType.STYLE_CHANGE)
        assert a == b


# ============================================================
# 每个意图的具体规则（防回归 — 改这些测试 = 业务语义在变）
# ============================================================


class TestStyleChange:
    def test_does_not_rerun_film_ir(self):
        """改风格不应重跑剧情分析——这是 Mode 2 性能的核心保证。"""
        rule = lookup(IntentType.STYLE_CHANGE)
        assert NodeType.FILM_IR_ANALYSIS in rule.reuse_set
        assert NodeType.FILM_IR_ANALYSIS not in rule.must_run_set

    def test_reruns_intent_injection(self):
        """改风格必须重写 INTENT_INJECTION（风格 prompt 变了）。"""
        rule = lookup(IntentType.STYLE_CHANGE)
        assert NodeType.INTENT_INJECTION in rule.must_run_set

    def test_reuses_character_ledger(self):
        """改风格不动角色身份。"""
        rule = lookup(IntentType.STYLE_CHANGE)
        assert NodeType.CHARACTER_LEDGER in rule.reuse_set


class TestCharacterReplace:
    def test_reruns_character_ledger(self):
        rule = lookup(IntentType.CHARACTER_REPLACE)
        assert NodeType.CHARACTER_LEDGER in rule.must_run_set

    def test_reuses_intent_injection(self):
        """换角色不动风格意图。"""
        rule = lookup(IntentType.CHARACTER_REPLACE)
        assert NodeType.INTENT_INJECTION in rule.reuse_set

    def test_reuses_film_ir(self):
        """剧情骨架可复用。"""
        rule = lookup(IntentType.CHARACTER_REPLACE)
        assert NodeType.FILM_IR_ANALYSIS in rule.reuse_set


class TestPlotRewrite:
    def test_reruns_film_ir(self):
        """改剧情必须重跑 Film IR。"""
        rule = lookup(IntentType.PLOT_REWRITE)
        assert NodeType.FILM_IR_ANALYSIS in rule.must_run_set

    def test_reruns_all_downstream(self):
        """改剧情后所有依赖 Film IR 的节点都要重跑。"""
        rule = lookup(IntentType.PLOT_REWRITE)
        for n in [
            NodeType.ABSTRACTION,
            NodeType.INTENT_INJECTION,
            NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
        ]:
            assert n in rule.must_run_set, f"{n} 应在 PLOT_REWRITE 的 must_run"

    def test_still_reuses_raw_analyze(self):
        """改剧情不需要重新分析原视频——原视频没变。"""
        rule = lookup(IntentType.PLOT_REWRITE)
        assert NodeType.ANALYZE in rule.reuse_set


class TestCutAdjust:
    def test_only_reruns_merge_and_output(self):
        """调剪辑只重合并——其他全复用。"""
        rule = lookup(IntentType.CUT_ADJUST)
        assert rule.must_run_set == {NodeType.MERGE, NodeType.OUTPUT}

    def test_reuses_video_generation(self):
        """调剪辑不重新生成视频。"""
        rule = lookup(IntentType.CUT_ADJUST)
        assert NodeType.VIDEO_GENERATION in rule.reuse_set


# ============================================================
# 跨意图覆盖性
# ============================================================


class TestCoverage:
    def test_table_covers_main_pipeline_nodes(self):
        """所有主流水线节点至少在某个意图里出现过——避免漏 NodeType。"""
        seen = all_known_node_types_in_table()
        main_pipeline = {
            NodeType.INPUT,
            NodeType.ANALYZE,
            NodeType.FILM_IR_ANALYSIS,
            NodeType.ABSTRACTION,
            NodeType.INTENT_INJECTION,
            NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
            NodeType.MERGE,
            NodeType.OUTPUT,
            NodeType.CHARACTER_LEDGER,
            NodeType.WATERMARK_CLEAN,
        }
        missing = main_pipeline - seen
        assert not missing, f"主流水线节点未覆盖: {missing}"
