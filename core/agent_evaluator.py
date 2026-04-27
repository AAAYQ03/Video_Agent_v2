"""
LLM-as-Judge 在线评估器 — Phase 3.4

职责：
  1. 视觉生成节点（STORYBOARD / VIDEO_GENERATION 等）产出后入评估器
  2. Vision LLM 多维 rubric 打分（character_consistency / style 等 5 维）
  3. 加权分数 < 阈值 → 触发"换策略重试"（不是原 prompt 重跑）
  4. 重试历史持久化到节点 state，下次重试时作为 prompt 上下文

⚠️ 概念区分（计划文档 Phase 3.4 强调）：
  - 这是 ONLINE RUNTIME 评估——节点产物当场打分，决定要不要重跑
  - **不是** ADK eval / pytest 这种离线测试集评估
  - 走 core.safety.llm_gateway，不直调 Gemini

⚠️ 幻觉防御：
  - LLM-as-judge 自身会 hallucinate（特别"创意性"这种模糊维度）
  - 缓解：每个维度给 0-10 量化标尺 + 具体描述锚定打分（在 prompt 里）
  - 长期：高方差维度引入第二个评估器投票（暂未实现）
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.graph_model import Node, NodeType
from core.safety.llm_gateway import GatewayRequest, llm_gateway

logger = logging.getLogger(__name__)


# ============================================================
# 多维 rubric — 评估器的"标尺"
# ============================================================


@dataclass(frozen=True)
class RubricDim:
    weight: float       # 加权占比，所有维度之和应为 1.0
    threshold: float    # 单维阈值（0-10）；任一维度低于此值视为"该维不达标"
    description: str    # 维度描述，会注入 prompt 里给评估器看


# 视觉生成类节点的 rubric（STORYBOARD / VIDEO_GENERATION）
EVAL_RUBRIC_VISUAL: Dict[str, RubricDim] = {
    "character_consistency": RubricDim(
        weight=0.30, threshold=7.0,
        description="生成画面里的角色形象是否与 character ledger 三视图一致（脸部、发型、服饰）",
    ),
    "style_consistency": RubricDim(
        weight=0.25, threshold=7.0,
        description="画面整体风格（色调、光影、质感）与目标风格描述的吻合度",
    ),
    "residual_artifacts": RubricDim(
        weight=0.20, threshold=8.0,
        description="原始视频中的水印/logo/字幕是否还残留——分数高=没残留，分数低=明显残留",
    ),
    "anatomical_quality": RubricDim(
        weight=0.15, threshold=7.0,
        description="面部、手部、肢体是否变形扭曲（典型 AI 生成失误）",
    ),
    "lighting_coherence": RubricDim(
        weight=0.10, threshold=6.0,
        description="光照方向、阴影、色温是否与场景描述一致",
    ),
}


# 节点类型 → 使用的 rubric。其他类型不评估。
NODE_RUBRIC: Dict[NodeType, Dict[str, RubricDim]] = {
    NodeType.STORYBOARD: EVAL_RUBRIC_VISUAL,
    NodeType.VIDEO_GENERATION: EVAL_RUBRIC_VISUAL,
    NodeType.SINGLE_SHOT_STYLIZE: EVAL_RUBRIC_VISUAL,
    NodeType.SINGLE_SHOT_VIDEO: EVAL_RUBRIC_VISUAL,
}


def is_evaluatable(node: Node) -> bool:
    """节点类型是否需要评估器跑——agent_loop 在 PostExecute 钩子位调用。"""
    return node.type in NODE_RUBRIC


# ============================================================
# 数据结构
# ============================================================


@dataclass
class EvaluationResult:
    scores: Dict[str, float]      # 各维度原始分数 0-10
    issues: List[str]              # 阈值未过的维度名清单
    weighted_score: float          # 加权总分 0-10
    passed: bool                   # 没有 issues 视为通过
    feedback: str                  # 评估器给的人话解释（用于审计/调试）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "issues": list(self.issues),
            "weighted_score": self.weighted_score,
            "passed": self.passed,
            "feedback": self.feedback,
        }


@dataclass
class RetryStrategy:
    """换策略重试时的具体改进方案（写入节点 config 供下次执行用）。"""

    name: str                      # 策略名（用于审计/UI）
    prompt_modifier: str           # 给原 prompt 追加的修饰内容
    extra_config: Dict[str, Any] = field(default_factory=dict)
    triggered_by: List[str] = field(default_factory=list)  # 触发此策略的 issue 维度

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "prompt_modifier": self.prompt_modifier,
            "extra_config": dict(self.extra_config),
            "triggered_by": list(self.triggered_by),
        }


# ============================================================
# 提示词模板
# ============================================================


EVAL_PROMPT_TEMPLATE = """\
你是 Video Agent 的视觉质量评估器（LLM-as-Judge）。

[节点信息]
- 节点类型: {node_type}
- 节点意图: {intent}

[执行结果摘要]
{result_summary}

[评估维度 — 0 到 10 整数打分，5 是中位数水平]
{rubric_table}

[输出格式]
严格 JSON 对象，**仅这一个对象**，不要 ``` 包装也不要前后说明：
{{
{score_fields}
  "feedback": "用一两句话解释整体观感（中文）"
}}
"""


# ============================================================
# 真正的 LLM 调用（测试用 monkey-patch 替换）
# ============================================================


def _invoke_evaluator_llm(
    prompt: str,
    *,
    user_email: str,
    material_tag: str,
    job_id: Optional[str],
) -> str:
    """
    调 Gemini Vision 给视觉产物打分。走 llm_gateway 享受限流+审计。

    单测 monkey-patch 此函数避开真实 API。
    """
    def call(redacted_prompt: str) -> str:
        from google import genai
        from google.genai import types

        from core.utils import gemini_keys

        client = genai.Client(api_key=gemini_keys.get())
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=[redacted_prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        return response.text or ""

    return llm_gateway().call(
        GatewayRequest(
            user_email=user_email,
            task="quality_eval",
            material_tag=material_tag,
            job_id=job_id,
            model_name="gemini-2.5-pro",
            prompt=prompt,
            call=call,
        )
    )


# ============================================================
# 主函数：evaluate_output
# ============================================================


def _build_eval_prompt(node: Node, execution_result: Dict[str, Any], rubric: Dict[str, RubricDim]) -> str:
    rubric_lines = []
    score_fields = []
    for name, dim in rubric.items():
        rubric_lines.append(f"  - {name} (权重 {dim.weight}, 阈值 {dim.threshold}): {dim.description}")
        score_fields.append(f'  "{name}": <0-10 整数分>,')

    intent = (node.config or {}).get("intent", "")

    # 重试历史用于让评估器知道"上次问题在哪，这次有没有改善"
    history = (node.config or {}).get("_retry_history", [])
    history_block = ""
    if history:
        history_block = "\n[之前重试的失败维度]\n"
        for h in history[-2:]:
            issues = ", ".join(h.get("issues", []))
            strategy = h.get("strategy_name", "")
            history_block += f"  - 第 {h.get('attempt', '?')} 次: {issues}（应用策略: {strategy}）\n"

    # result_summary 只取关键字段，避免 prompt 爆炸
    summary = {
        k: v for k, v in (execution_result or {}).items()
        if k in ("output_path", "video", "frames_count", "shots_count", "duration_ms")
    }

    return EVAL_PROMPT_TEMPLATE.format(
        node_type=node.type.value,
        intent=intent or "（未指定）",
        result_summary=json.dumps(summary, ensure_ascii=False, indent=2) + history_block,
        rubric_table="\n".join(rubric_lines),
        score_fields="\n".join(score_fields),
    )


def _parse_eval_json(raw: str, rubric: Dict[str, RubricDim]) -> EvaluationResult:
    """解析评估器输出 + schema 校验 + 计算加权。"""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2:
            raw = "\n".join(
                lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            ).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"评估器输出非合法 JSON: {e}; 原始首 200 字: {raw[:200]}")

    if not isinstance(parsed, dict):
        raise ValueError("评估器输出不是对象")

    scores: Dict[str, float] = {}
    for dim_name in rubric.keys():
        v = parsed.get(dim_name)
        if v is None:
            raise ValueError(f"评估器输出缺维度 '{dim_name}'")
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"维度 '{dim_name}' 的值非数字: {v!r}")
        if not (0.0 <= f <= 10.0):
            raise ValueError(f"维度 '{dim_name}' 分数 {f} 越界（应 0-10）")
        scores[dim_name] = f

    issues = [
        name for name, v in scores.items()
        if v < rubric[name].threshold
    ]

    weighted = sum(scores[name] * rubric[name].weight for name in scores)

    return EvaluationResult(
        scores=scores,
        issues=issues,
        weighted_score=weighted,
        passed=(len(issues) == 0),
        feedback=str(parsed.get("feedback", "")),
    )


def evaluate_output(
    node: Node,
    execution_result: Dict[str, Any],
    *,
    user_email: str = "system",
    material_tag: str = "INTERNAL",
    job_id: Optional[str] = None,
) -> EvaluationResult:
    """
    入口：给节点产物打分。

    Returns:
        EvaluationResult，包含各维分数、是否通过、issues 清单

    Raises:
        ValueError: 节点不可评估，或两次 LLM 调用都失败
    """
    rubric = NODE_RUBRIC.get(node.type)
    if rubric is None:
        raise ValueError(
            f"节点类型 {node.type.value} 不可评估；evaluatable: "
            f"{[t.value for t in NODE_RUBRIC]}"
        )

    prompt = _build_eval_prompt(node, execution_result, rubric)

    # 第一次尝试
    try:
        raw = _invoke_evaluator_llm(
            prompt,
            user_email=user_email,
            material_tag=material_tag,
            job_id=job_id,
        )
        return _parse_eval_json(raw, rubric)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"evaluator first attempt failed: {e}; retrying once")

    # 第二次尝试 — 简化提示词强调格式
    retry_prompt = (
        prompt
        + "\n\n[严格要求] 上次输出无法解析。请只输出一个 JSON 对象，"
        "不要任何代码块标记，所有维度字段都不能缺。"
    )
    raw = _invoke_evaluator_llm(
        retry_prompt,
        user_email=user_email,
        material_tag=material_tag,
        job_id=job_id,
    )
    return _parse_eval_json(raw, rubric)


# ============================================================
# 换策略重试：根据 issue → 选改进策略
# ============================================================


# 维度 → 当该维不达标时应用的策略
_DIMENSION_STRATEGIES: Dict[str, RetryStrategy] = {
    "character_consistency": RetryStrategy(
        name="strengthen_character_anchor",
        prompt_modifier=(
            "【角色一致性强化】严格按 character ledger 三视图渲染："
            "脸型、发色、服饰细节必须 1:1 还原；不要凭空发挥角色样貌。"
        ),
    ),
    "style_consistency": RetryStrategy(
        name="reinforce_style_keywords",
        prompt_modifier=(
            "【风格强化】把目标风格关键词放在 prompt 最前；"
            "明确写出风格的色调/光照/质感三类约束。"
        ),
    ),
    "residual_artifacts": RetryStrategy(
        name="add_negative_watermark_prompt",
        prompt_modifier=(
            "【去残留】negative prompt 增加："
            "watermark, logo, subtitle, text overlay, channel bug。"
        ),
        extra_config={"emphasize_clean_output": True},
    ),
    "anatomical_quality": RetryStrategy(
        name="emphasize_proper_anatomy",
        prompt_modifier=(
            "【解剖正确】negative prompt 增加："
            "deformed face, extra fingers, distorted limbs, bad anatomy。"
        ),
    ),
    "lighting_coherence": RetryStrategy(
        name="match_scene_lighting",
        prompt_modifier=(
            "【光照对齐】明确光源方向（如：左上 45° 暖色顶光），"
            "shadow 与场景描述一致。"
        ),
    ),
}


def decide_retry_strategy(
    node: Node, eval_result: EvaluationResult,
) -> RetryStrategy:
    """
    不是原 prompt 重跑——根据 issue 维度组合出新策略。

    多个维度同时不达标时合并 prompt_modifier。
    """
    if not eval_result.issues:
        return RetryStrategy(
            name="noop",
            prompt_modifier="",
            triggered_by=[],
        )

    # 按权重降序排（先解决权重大的维度问题）
    rubric = NODE_RUBRIC[node.type]
    sorted_issues = sorted(
        eval_result.issues,
        key=lambda d: rubric[d].weight,
        reverse=True,
    )

    parts: List[str] = []
    extra_config: Dict[str, Any] = {}
    names: List[str] = []

    for dim in sorted_issues:
        strat = _DIMENSION_STRATEGIES.get(dim)
        if not strat:
            continue
        parts.append(strat.prompt_modifier)
        extra_config.update(strat.extra_config)
        names.append(strat.name)

    return RetryStrategy(
        name="+".join(names) if names else "generic_retry",
        prompt_modifier="\n".join(parts),
        extra_config=extra_config,
        triggered_by=list(sorted_issues),
    )


# ============================================================
# 重试历史记录
# ============================================================


def record_retry_attempt(
    node: Node, eval_result: EvaluationResult, strategy: RetryStrategy,
) -> None:
    """
    把这次失败的评估结果 + 应用的策略记进 node.config['_retry_history']。

    下次重试时 _build_eval_prompt 会把历史注入提示词，
    让评估器知道"上次问题在哪，看这次有没有改善"。
    """
    history = list((node.config or {}).get("_retry_history", []))
    history.append({
        "attempt": node.retry_count + 1,
        "scores": dict(eval_result.scores),
        "issues": list(eval_result.issues),
        "weighted_score": eval_result.weighted_score,
        "strategy_name": strategy.name,
        "prompt_modifier": strategy.prompt_modifier,
    })

    # 同时把 last_strategy 单独放出来，方便 node_executor 下次执行时读取
    new_config = dict(node.config or {})
    new_config["_retry_history"] = history
    new_config["_last_retry_strategy"] = strategy.to_dict()
    node.config = new_config
