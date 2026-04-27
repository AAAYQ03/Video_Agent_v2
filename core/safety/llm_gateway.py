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


# 服务端临时错误（值得退避重试）
_RETRYABLE_PATTERNS = (
    "503", "unavailable",      # 模型过载
    "500", "internal",          # Google 内部错误
    "504", "deadline_exceeded", # 超时
    "429", "resource_exhausted", "quota",  # 限流（RPM 退避后可能恢复）
)


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(p in msg for p in _RETRYABLE_PATTERNS)


class LLMGateway:
    # 自动重试配置
    MAX_RETRIES = 3
    BACKOFF_BASE = 1.0  # 第 N 次重试前等 BACKOFF_BASE * 2^N 秒（1s / 2s / 4s）

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

        # 4. 真正调用——带指数退避自动重试
        start = time.time()
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                result = req.call(prompt)
                break  # 成功跳出
            except Exception as exc:
                last_exc = exc
                # 不可重试错误（4xx 我们的 bug）→ 立即抛
                if not _is_retryable(exc):
                    audit.emit(
                        "llm_call",
                        user=req.user_email, job_id=req.job_id,
                        resource=req.model_name or req.task,
                        outcome="error",
                        details={
                            "task": req.task,
                            "elapsed_ms": int((time.time() - start) * 1000),
                            "error": str(exc)[:500],
                            "retryable": False,
                        },
                    )
                    raise
                # 最后一次还是失败 → 抛
                if attempt == self.MAX_RETRIES - 1:
                    audit.emit(
                        "llm_call",
                        user=req.user_email, job_id=req.job_id,
                        resource=req.model_name or req.task,
                        outcome="error",
                        details={
                            "task": req.task,
                            "elapsed_ms": int((time.time() - start) * 1000),
                            "error": str(exc)[:500],
                            "retryable": True,
                            "attempts": self.MAX_RETRIES,
                        },
                    )
                    raise
                # 中间次失败 → 退避后重试
                wait = self.BACKOFF_BASE * (2 ** attempt)
                audit.emit(
                    "llm_call",
                    user=req.user_email, job_id=req.job_id,
                    resource=req.model_name or req.task,
                    outcome="retry_backoff",
                    details={
                        "task": req.task,
                        "attempt": attempt + 1,
                        "wait_seconds": wait,
                        "error": str(exc)[:300],
                    },
                )
                print(f"⏳ [llm_gateway] {req.task} 第 {attempt+1} 次失败 ({type(exc).__name__})，{wait}s 后重试")
                time.sleep(wait)

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


# ============================================================
# 透明代理：让现有 client.models.generate_content(...) 走网关
# ============================================================
#
# Batch 2 迁移用：把 `genai.Client(api_key=...)` 替换成
# `gateway_client(task=..., job_id=...)` 后，**业务代码不用改**——
# `client.files.upload(...)`、`client.models.generate_content(...)`
# 等用法保持不变，只是 generate_content 自动走 LLMGateway 做限流+审计+脱敏。


class _ModelsProxy:
    """models 子对象的代理：generate_content 走网关，其他方法透传。"""

    def __init__(self, owner: "GatewayClient"):
        # 用 __dict__ 直写避免触发 __getattr__ 递归
        self.__dict__["_owner"] = owner

    def generate_content(self, *args, **kwargs) -> Any:
        owner = self._owner
        underlying_models = owner._underlying.models

        # 抽取 prompt 用于审计（只取字符串部分，跳过 file/image 对象）
        prompt_for_audit = _extract_audit_prompt(args, kwargs)

        return llm_gateway().call(
            GatewayRequest(
                user_email=owner._user_email,
                task=owner._task,
                material_tag=owner._material_tag,
                job_id=owner._job_id,
                model_name=kwargs.get("model"),
                prompt=prompt_for_audit,
                # 闭包保留原始 args/kwargs，prompt 在 gateway 内只用于审计/脱敏
                # 不实际替换 generate_content 的入参
                call=lambda _redacted: underlying_models.generate_content(*args, **kwargs),
            )
        )

    def __getattr__(self, name: str) -> Any:
        # 其他 models 方法（如 list_models）原样透传
        return getattr(self.__dict__["_owner"]._underlying.models, name)


class GatewayClient:
    """
    genai.Client 的透明包装。

    与原 Client 接口 100% 兼容：
      - client.models.generate_content(...) → 走网关（限流/审计/脱敏）
      - client.files.upload / client.files.get / 其他 → 透传到原 client
    """

    def __init__(
        self,
        underlying: Any,
        user_email: str,
        task: str,
        material_tag: str,
        job_id: Optional[str],
    ):
        self.__dict__["_underlying"] = underlying
        self.__dict__["_user_email"] = user_email
        self.__dict__["_task"] = task
        self.__dict__["_material_tag"] = material_tag
        self.__dict__["_job_id"] = job_id
        self.__dict__["_models_proxy"] = _ModelsProxy(self)

    @property
    def models(self):
        return self._models_proxy

    def __getattr__(self, name: str) -> Any:
        # files / aio / 其他属性透传到底层 client
        return getattr(self.__dict__["_underlying"], name)


def gateway_client(
    *,
    task: str,
    user_email: str = "system",
    material_tag: str = "INTERNAL",
    job_id: Optional[str] = None,
    api_key: Optional[str] = None,
    **client_kwargs: Any,
) -> GatewayClient:
    """
    创建受网关管控的 Gemini 客户端。Batch 2 迁移点统一用这个替代 genai.Client(...)。

    Args:
        task:         本次客户端的业务用途（如 "film_ir_build", "agent_intent_parse"）。
                      会进入审计日志便于追踪。
        user_email:   触发用户。后台任务无 request context 时用 "system" 占位。
        material_tag: 素材分级，用于脱敏决策。后台默认 "INTERNAL"，前台从
                      jobs/{id}/material_metadata.json 读取。
        job_id:       关联任务 ID，便于审计。
        api_key:      可选；不传则从 gemini_keys 池取一个。
        **client_kwargs: 透传给底层 genai.Client（如 http_options）。
    """
    from google import genai  # 局部 import 避免循环依赖与启动开销

    if api_key is None:
        from core.utils import gemini_keys

        api_key = gemini_keys.get()

    underlying = genai.Client(api_key=api_key, **client_kwargs)
    return GatewayClient(
        underlying=underlying,
        user_email=user_email,
        task=task,
        material_tag=material_tag,
        job_id=job_id,
    )


def _extract_audit_prompt(args: tuple, kwargs: dict) -> str:
    """
    从 generate_content 的入参里抽出文本部分用于审计/脱敏。
    Gemini API 的 contents 可能是 str / List[Part] / List[mixed]，需要稳健处理。
    """
    contents = kwargs.get("contents")
    if contents is None and args:
        # 位置参数兜底（虽然官方推荐 kwargs）
        for a in args:
            if isinstance(a, (str, list)):
                contents = a
                break

    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents[:8000]  # 截断防爆炸

    # list 形态：把字符串部分拼起来，跳过 file/image 等非文本
    if isinstance(contents, list):
        parts: List[str] = []
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "text") and isinstance(item.text, str):
                parts.append(item.text)
            # else: 文件/图片对象等，跳过
        return "\n".join(parts)[:8000]

    return str(contents)[:8000]
