"""
大模型统一网关（Batch 1 轻量实现 / Batch 2 强制全面迁移）

本次 Batch 1 的目标是把基础设施搭起来：
  - 进程内滑动窗口限流（每用户 / 小时 / 天）
  - 统一审计日志点
  - 数据脱敏钩子（基于素材分级）
  - 调用计数——用于成本追溯

不做的事（留给 Batch 2）：
  - 改写 core/agent_engine.py / film_ir_manager.py / workflow_manager.py / asset_generator.py
    里四处 Gemini 直调改走网关
  - Redis 级分布式限流
  - 多 provider 路由（Gemini / Vertex AI / 其他）

使用示例（Batch 2 里各业务模块会这样写）：

    from core.safety.llm_gateway import LLMGateway, GatewayRequest

    gw = LLMGateway()
    resp = gw.call(GatewayRequest(
        user_email="creator1@example.com",
        task="intent_parse",
        material_tag="INTERNAL",
        prompt="...",
        call=lambda prompt: gemini_client.generate_content(prompt),
    ))
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Optional

from core.safety.audit_log import audit_log
from core.safety.config import get_config


class RateLimitExceeded(RuntimeError):
    """超出限流阈值。"""

    def __init__(self, window: str, limit: int):
        super().__init__(f"超出 {window} 限流：{limit} 次")
        self.window = window
        self.limit = limit


# ---------- 脱敏 ----------


_BRAND_PLACEHOLDER_PATTERN = re.compile(
    # 占位：匹配「品牌：XXX」「客户：XXX」这种显式标注；
    # MVP 阶段只做保守脱敏，不瞎替换。
    r"(品牌|客户|Brand|Client)[：:\s]+([A-Za-z0-9\u4e00-\u9fa5]{1,40})",
)


def redact_prompt(text: str, material_tag: str) -> str:
    """
    对 prompt 做保守脱敏。
    策略：
      - INTERNAL：不脱敏（默认信任）
      - VIRAL_REF：不脱敏（参考源已经单独记录）
      - 未来扩展：客户资产类标签 -> 把显式品牌/客户名替换为 [BRAND_X]
    """
    if not text:
        return text
    # MVP 阶段只示范一种脱敏规则；真正按 tag 分流留给后续。
    # 现阶段即便是 INTERNAL，我们也仅做一件事：把显式写出的「品牌: XXX」作为占位
    # 目的不是真的脱敏——而是给未来的规则留一个挂载点。
    return text  # Batch 1：noop；保留 API 形态


# ---------- 限流 ----------


@dataclass
class _Window:
    """滑动窗口计数：deque 存每次调用的时间戳。"""

    capacity: int
    span_seconds: int
    stamps: Deque[float] = field(default_factory=deque)

    def allow(self, now: float) -> bool:
        cutoff = now - self.span_seconds
        while self.stamps and self.stamps[0] < cutoff:
            self.stamps.popleft()
        if len(self.stamps) >= self.capacity:
            return False
        self.stamps.append(now)
        return True


class _InMemoryRateLimiter:
    """单进程限流器。生产多实例部署应替换为 Redis。"""

    def __init__(self, per_hour: int, per_day: int):
        self.per_hour = per_hour
        self.per_day = per_day
        self._by_user: Dict[str, Dict[str, _Window]] = {}
        self._lock = threading.Lock()

    def check(self, user_email: str) -> None:
        now = time.time()
        with self._lock:
            if user_email not in self._by_user:
                self._by_user[user_email] = {
                    "hour": _Window(self.per_hour, 3600),
                    "day": _Window(self.per_day, 86400),
                }
            windows = self._by_user[user_email]
            if not windows["hour"].allow(now):
                raise RateLimitExceeded("per_hour", self.per_hour)
            if not windows["day"].allow(now):
                # 小时命中后退一个回来——day 超限时小时窗口刚加的要回退
                windows["hour"].stamps.pop()
                raise RateLimitExceeded("per_day", self.per_day)


# ---------- 网关 ----------


@dataclass
class GatewayRequest:
    user_email: str
    task: str               # intent_parse / film_ir_build / shot_generate / ...
    material_tag: str       # INTERNAL / VIRAL_REF
    prompt: str
    call: Callable[[str], Any]   # 实际的底层模型调用，闭包里自己持有 client
    job_id: Optional[str] = None
    model_name: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


class LLMGateway:
    def __init__(self, rate_limiter: Optional[_InMemoryRateLimiter] = None):
        cfg = get_config()["rate_limits"]
        self.limiter = rate_limiter or _InMemoryRateLimiter(
            per_hour=cfg["per_user_per_hour"],
            per_day=cfg["per_user_per_day"],
        )

    def call(self, req: GatewayRequest) -> Any:
        """执行受管控的大模型调用。"""
        audit = audit_log()

        # 1. 限流
        try:
            self.limiter.check(req.user_email)
        except RateLimitExceeded as e:
            audit.emit(
                "llm_call",
                user=req.user_email,
                job_id=req.job_id,
                resource=req.model_name or req.task,
                outcome="rate_limited",
                details={"window": e.window, "limit": e.limit, "task": req.task},
            )
            raise

        # 2. 脱敏
        prompt = redact_prompt(req.prompt, req.material_tag)

        # 3. 审计（调用前）
        audit.emit(
            "llm_call",
            user=req.user_email,
            job_id=req.job_id,
            resource=req.model_name or req.task,
            outcome="start",
            details={
                "task": req.task,
                "material_tag": req.material_tag,
                "prompt_chars": len(prompt or ""),
            },
        )

        # 4. 真正调用
        start = time.time()
        try:
            result = req.call(prompt)
        except Exception as exc:
            audit.emit(
                "llm_call",
                user=req.user_email,
                job_id=req.job_id,
                resource=req.model_name or req.task,
                outcome="error",
                details={
                    "task": req.task,
                    "elapsed_ms": int((time.time() - start) * 1000),
                    "error": str(exc)[:500],
                },
            )
            raise

        # 5. 审计（调用后）
        audit.emit(
            "llm_call",
            user=req.user_email,
            job_id=req.job_id,
            resource=req.model_name or req.task,
            outcome="ok",
            details={
                "task": req.task,
                "elapsed_ms": int((time.time() - start) * 1000),
            },
        )
        return result


# 进程级单例
_gateway: Optional[LLMGateway] = None
_gateway_lock = threading.Lock()


def llm_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        with _gateway_lock:
            if _gateway is None:
                _gateway = LLMGateway()
    return _gateway
