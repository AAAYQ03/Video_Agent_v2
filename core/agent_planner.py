"""
LLM 规划器 — Phase 1.5.2

两阶段调用：
  1. classify_intent  — 用户自然语言 → 结构化 IntentType + target/scope
  2. build_minimal_dag — 查依赖表 → WorkflowGraph（must_run 节点 PENDING，
                         reuse 节点直接 SUCCESS 标记为已复用产物）

走 core.safety.llm_gateway，不直调 Gemini，享受限流+审计+脱敏。
失败重试 1 次（用更严格的提示词）。

这是 Mode 2 真正"长出 Agent 脑子"的入口：agent_loop 启动时用 plan_workflow()
替代 WorkflowGraph.create_default()，让 DAG 由"意图分类 + 硬编码依赖表"
共同决定，而不是写死流水线。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.graph_model import NodeStatus, WorkflowGraph
from core.intent_dependency_table import IntentType, lookup
from core.safety.llm_gateway import GatewayRequest, llm_gateway

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================


@dataclass
class IntentClassification:
    """Stage 1 输出。"""

    type: IntentType
    target: str        # 简短目标描述，如 "日系清新风格"
    scope: str         # "global" | "per_shot" | "partial"
    rationale: str     # 模型给的归类理由（用于审计/调试）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "target": self.target,
            "scope": self.scope,
            "rationale": self.rationale,
        }


# ============================================================
# 提示词模板
# ============================================================


CLASSIFY_PROMPT_TEMPLATE = """\
你是 Video Agent 的意图分类器。把用户的修改需求严格归类到以下四类之一：

- STYLE_CHANGE       — 改风格（不动剧情、角色），如调色、滤镜、画面质感
- CHARACTER_REPLACE  — 换角色（不动剧情、风格），如替换主角形象
- PLOT_REWRITE       — 改剧情（重写故事/场景/情节）
- CUT_ADJUST         — 仅调剪辑（节奏、时长），不改内容本身

[用户需求]
{user_goal}

[已有任务上下文]
{job_context}

[输出格式]
严格 JSON 对象，不要前后说明文字，不要 ``` 代码块包装：
{{
  "type": "STYLE_CHANGE | CHARACTER_REPLACE | PLOT_REWRITE | CUT_ADJUST",
  "target": "简短目标描述（10 字以内），如 '日系清新风格'",
  "scope": "global | per_shot | partial",
  "rationale": "一句话说明归类依据"
}}
"""


CLASSIFY_RETRY_PROMPT_TEMPLATE = """\
上一次输出无法解析或字段不完整，请严格按照 JSON 模板重出。

[用户需求]
{user_goal}

[强制约束]
1. 仅输出一个 JSON 对象，不要 ``` 代码块标记
2. type 必须是 STYLE_CHANGE / CHARACTER_REPLACE / PLOT_REWRITE / CUT_ADJUST 之一
3. 四个字段（type / target / scope / rationale）都必填，不能缺

[输出]
"""


# ============================================================
# 真正的 LLM 调用（测试用 monkey-patch 替换）
# ============================================================


def _invoke_classifier_llm(
    prompt: str,
    *,
    user_email: str,
    material_tag: str,
    job_id: Optional[str],
) -> str:
    """
    调 Gemini 出意图分类，走 llm_gateway 享受限流+审计+脱敏。

    单测中应 monkey-patch 此函数避开真实 API 调用：
        monkeypatch.setattr(agent_planner, "_invoke_classifier_llm", fake)
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
            task="intent_classify",
            material_tag=material_tag,
            job_id=job_id,
            model_name="gemini-2.5-pro",
            prompt=prompt,
            call=call,
        )
    )


# ============================================================
# Stage 1: 意图分类
# ============================================================


def _parse_intent_json(raw: str) -> IntentClassification:
    """解析 LLM 输出 + schema 校验。失败抛 ValueError。"""
    raw = (raw or "").strip()

    # 容错：剥掉 ``` 代码块标记
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 2:
            # 去掉首行 ```xxx 和（如果存在的）末行 ```
            tail = lines[1:-1] if lines[-1].startswith("```") else lines[1:]
            raw = "\n".join(tail).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"分类器输出非合法 JSON: {e}; 原始首 200 字: {raw[:200]}")

    if not isinstance(parsed, dict):
        raise ValueError(f"分类器输出不是对象: {type(parsed).__name__}")

    required = ["type", "target", "scope", "rationale"]
    missing = [k for k in required if k not in parsed]
    if missing:
        raise ValueError(
            f"分类器输出缺字段: {missing}; 实际字段: {list(parsed.keys())}"
        )

    try:
        intent_type = IntentType(parsed["type"])
    except ValueError as e:
        raise ValueError(
            f"分类器输出 type='{parsed['type']}' 不在 IntentType 枚举: {e}"
        )

    return IntentClassification(
        type=intent_type,
        target=str(parsed["target"]),
        scope=str(parsed["scope"]),
        rationale=str(parsed["rationale"]),
    )


def classify_intent(
    user_goal: str,
    *,
    job_context: Optional[Dict[str, Any]] = None,
    user_email: str = "system",
    material_tag: str = "INTERNAL",
    job_id: Optional[str] = None,
) -> IntentClassification:
    """
    Stage 1：用户自然语言 → 结构化意图分类。

    失败时用更严格的提示词重试 1 次。两次都失败抛 ValueError。
    """
    job_context = job_context or {}
    prompt = CLASSIFY_PROMPT_TEMPLATE.format(
        user_goal=user_goal,
        job_context=json.dumps(job_context, ensure_ascii=False, indent=2),
    )

    # 第一次尝试
    try:
        raw = _invoke_classifier_llm(
            prompt,
            user_email=user_email,
            material_tag=material_tag,
            job_id=job_id,
        )
        return _parse_intent_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"intent_classify first attempt failed: {e}; retrying")

    # 第二次尝试：严格提示词
    retry_prompt = CLASSIFY_RETRY_PROMPT_TEMPLATE.format(user_goal=user_goal)
    raw = _invoke_classifier_llm(
        retry_prompt,
        user_email=user_email,
        material_tag=material_tag,
        job_id=job_id,
    )
    return _parse_intent_json(raw)


# ============================================================
# Stage 2: 构造最小 DAG
# ============================================================


def build_minimal_dag(
    intent: IntentClassification,
    user_goal: str,
) -> WorkflowGraph:
    """
    Stage 2：基于意图查依赖表，构造"最小 DAG"。

    实现方式（与 Mode 1 拓扑保持一致，避免改动 agent_loop）：
      1. 用 WorkflowGraph.create_default() 拿到完整拓扑
      2. 把 reuse 节点的 status 直接置为 SUCCESS（已复用产物）
      3. must_run 节点保持 PENDING

    agent_loop 跳过 SUCCESS 节点 → 实际只跑 must_run → 自然实现
    "意图驱动最小 DAG" 语义。
    """
    rule = lookup(intent.type)

    intent_config = {
        "intent": intent.target,
        "scope": intent.scope,
        "intent_type": intent.type.value,
    }
    graph = WorkflowGraph.create_default(
        user_goal=user_goal,
        intent_config=intent_config,
    )

    for node in graph.nodes:
        if node.type in rule.reuse_set:
            node.status = NodeStatus.SUCCESS
            node.result = {
                "reused": True,
                "reason": f"intent={intent.type.value} 复用现有产物",
            }

    return graph


# ============================================================
# 协调器
# ============================================================


def plan_workflow(
    user_goal: str,
    *,
    job_context: Optional[Dict[str, Any]] = None,
    user_email: str = "system",
    material_tag: str = "INTERNAL",
    job_id: Optional[str] = None,
) -> WorkflowGraph:
    """
    完整规划：分类意图 → 构造最小 DAG。

    替代 agent_loop 里的 WorkflowGraph.create_default()——这是 Mode 2
    真正长出 Agent 脑子的入口。
    """
    intent = classify_intent(
        user_goal,
        job_context=job_context,
        user_email=user_email,
        material_tag=material_tag,
        job_id=job_id,
    )
    logger.info(f"classified intent: {intent.to_dict()}")
    return build_minimal_dag(intent, user_goal)
