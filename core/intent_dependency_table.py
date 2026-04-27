"""
意图分类 → 依赖节点查表

Phase 1.5.1 产物。Mode 2 规划器的"硬编码大脑"——回答"用户改这个，
哪些节点必须重跑 / 哪些可以直接复用现有产物"。

核心设计原则：
  1. **硬编码 vs LLM 决策**：哪些节点跑/不跑是确定性逻辑，必须用代码表达，
     不让 LLM 自由发挥。LLM 只负责把用户的自然语言分类到 IntentType，
     具体执行计划由这张表决定。
  2. **可测试**：所有 (intent, node) 组合可枚举，回归测试覆盖。
  3. **可解释**：用户问"为什么改风格不重新分析剧情"能直接给规则解释。

不在本表的二级/扩展节点（SINGLE_SHOT_STYLIZE / QUALITY_CHECK 等）由更细粒度
的子流程处理，不属于"意图驱动主流水线"的范畴。

⚠️ 拓扑精度声明：
本表的 NodeType 集合是"语义层"——表达"修改这个意图涉及到哪些概念节点"。
但 `WorkflowGraph.create_default()` 当前**未把所有 NodeType 都写进拓扑**，
具体说：
  - CHARACTER_LEDGER 当前是 FILM_IR_ANALYSIS 的子步骤，不在主 DAG 里
  - WATERMARK_CLEAN / FILM_IR_ANALYSIS / ABSTRACTION 等都是真实节点

`build_minimal_dag` 只会对**真正出现在 DAG 里**的节点应用 reuse 标记——
表里写了但拓扑里没有的节点（如 CHARACTER_LEDGER），表达的是"将来这个意图要
独立成节点时应归属哪一边"。这是有意为之的"前瞻性表达"，方便日后给拓扑加
节点时直接对应。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Set, Union

from core.graph_model import NodeType


class IntentType(str, Enum):
    """用户修改意图的四类。"""

    STYLE_CHANGE = "STYLE_CHANGE"            # 改风格（不动剧情/角色）
    CHARACTER_REPLACE = "CHARACTER_REPLACE"  # 换角色（不动剧情/风格）
    PLOT_REWRITE = "PLOT_REWRITE"            # 改剧情（重写一切）
    CUT_ADJUST = "CUT_ADJUST"                # 调剪辑（只重合并）


@dataclass(frozen=True)
class DependencyRule:
    """单个意图的依赖规则。"""

    must_run: List[NodeType]      # 必须重跑的节点（按拓扑顺序）
    reuse: List[NodeType]         # 可直接复用已有产物的节点
    description: str               # 一句话说明，用于 UI 展示与日志解释

    @property
    def must_run_set(self) -> Set[NodeType]:
        return set(self.must_run)

    @property
    def reuse_set(self) -> Set[NodeType]:
        return set(self.reuse)


# 主映射表：IntentType → DependencyRule
# 加新意图时这里新增一行；NodeType 增删时这里要同步检查（测试会拦截不一致）
DEPENDENCY_TABLE: Dict[IntentType, DependencyRule] = {
    IntentType.STYLE_CHANGE: DependencyRule(
        must_run=[
            NodeType.INTENT_INJECTION,    # 重写风格意图
            NodeType.ASSET_GENERATION,    # 重新渲染资产（角色/环境的新风格版本）
            NodeType.STORYBOARD,          # 风格变了分镜也要重生成
            NodeType.VIDEO_GENERATION,
            NodeType.MERGE,
            NodeType.OUTPUT,
        ],
        reuse=[
            NodeType.INPUT,
            NodeType.ANALYZE,
            NodeType.WATERMARK_CLEAN,
            NodeType.FILM_IR_ANALYSIS,
            NodeType.ABSTRACTION,
            NodeType.CHARACTER_LEDGER,    # 角色身份不变
        ],
        description="改风格：重跑风格注入与下游产物；分析与角色账本可复用",
    ),

    IntentType.CHARACTER_REPLACE: DependencyRule(
        must_run=[
            NodeType.CHARACTER_LEDGER,    # 重写角色账本
            NodeType.ASSET_GENERATION,    # 新角色的资产
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
            NodeType.MERGE,
            NodeType.OUTPUT,
        ],
        reuse=[
            NodeType.INPUT,
            NodeType.ANALYZE,
            NodeType.WATERMARK_CLEAN,
            NodeType.FILM_IR_ANALYSIS,
            NodeType.ABSTRACTION,
            NodeType.INTENT_INJECTION,    # 风格意图不变
        ],
        description="换角色：重写角色账本与下游产物；剧情与风格意图复用",
    ),

    IntentType.PLOT_REWRITE: DependencyRule(
        must_run=[
            NodeType.FILM_IR_ANALYSIS,    # 剧情变了，IR 重做
            NodeType.ABSTRACTION,
            NodeType.CHARACTER_LEDGER,
            NodeType.INTENT_INJECTION,
            NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
            NodeType.MERGE,
            NodeType.OUTPUT,
        ],
        reuse=[
            NodeType.INPUT,
            NodeType.ANALYZE,             # 原始视频分析仍可用
            NodeType.WATERMARK_CLEAN,
        ],
        description="改剧情：重跑 Film IR 与所有下游；只复用原始视频分析",
    ),

    IntentType.CUT_ADJUST: DependencyRule(
        must_run=[
            NodeType.MERGE,
            NodeType.OUTPUT,
        ],
        reuse=[
            NodeType.INPUT,
            NodeType.ANALYZE,
            NodeType.WATERMARK_CLEAN,
            NodeType.FILM_IR_ANALYSIS,
            NodeType.ABSTRACTION,
            NodeType.CHARACTER_LEDGER,
            NodeType.INTENT_INJECTION,
            NodeType.ASSET_GENERATION,
            NodeType.STORYBOARD,
            NodeType.VIDEO_GENERATION,
        ],
        description="调剪辑：只重新合并；所有上游产物复用",
    ),
}


def lookup(intent_type: Union[IntentType, str]) -> DependencyRule:
    """
    根据意图类型查依赖规则。

    Args:
        intent_type: IntentType 枚举或对应字符串（"STYLE_CHANGE" 等）

    Raises:
        ValueError: 字符串无法转成 IntentType
        KeyError:   IntentType 不在表里（理论上不应发生，被测试拦截）
    """
    if isinstance(intent_type, str):
        intent_type = IntentType(intent_type)  # 抛 ValueError if 字符串非法
    if intent_type not in DEPENDENCY_TABLE:
        raise KeyError(
            f"意图类型 {intent_type} 没有对应规则；"
            f"可用：{[t.value for t in IntentType]}"
        )
    return DEPENDENCY_TABLE[intent_type]


def all_known_node_types_in_table() -> Set[NodeType]:
    """所有出现在依赖表里的 NodeType 并集——测试用。"""
    seen: Set[NodeType] = set()
    for rule in DEPENDENCY_TABLE.values():
        seen.update(rule.must_run_set)
        seen.update(rule.reuse_set)
    return seen
