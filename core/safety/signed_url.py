"""
HMAC 签名资源链接

URL 格式：
    /assets/{job_id}/{path}?exp={unix_ts}&u={user_email_b64}&sig={hmac_hex}

sig = HMAC-SHA256(
    secret,
    f"{job_id}|{path}|{exp}|{user_email}"
)

- exp 是 UTC unix 时间戳（秒），到期后服务端拒绝
- u 绑定签发时的用户 email（base64url 编码避开特殊字符），校验时比对当前请求身份
- secret 从 .env 的 SAFETY_SECRET 读取，48+ 位随机

不用 JWT 的原因：MVP 不需要嵌复杂 claims；自实现更薄更可控、零依赖。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Optional

from core.safety.config import get_config, safety_secret


def _b64url(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> str:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad).decode("utf-8")


def _canonical(job_id: str, path: str, exp: int, user_email: str) -> str:
    return f"{job_id}|{path}|{exp}|{user_email}"


def sign_asset_url(
    job_id: str,
    path: str,
    user_email: str,
    *,
    ttl_seconds: Optional[int] = None,
    base_url: str = "",
) -> str:
    """
    生成签名链接（相对路径或完整 URL）。

    Args:
        job_id: 任务 id
        path: job 目录下的相对路径（如 "assets/shot_01.png"）
        user_email: 获取链接的用户——签名里绑定此人
        ttl_seconds: 链接有效期，None 走默认配置
        base_url: 要前缀的 domain；空字符串则返回相对路径
    """
    cfg = get_config()["signed_url"]
    ttl = ttl_seconds if ttl_seconds is not None else cfg["default_ttl_seconds"]
    ttl = min(ttl, cfg["max_ttl_seconds"])
    exp = int(time.time()) + ttl

    canonical = _canonical(job_id, path, exp, user_email)
    sig = hmac.new(
        safety_secret().encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # path 里不带前导斜杠
    path = path.lstrip("/")
    u_enc = _b64url(user_email)
    query = f"exp={exp}&u={u_enc}&sig={sig}"
    rel = f"/assets/{job_id}/{path}?{query}"
    return f"{base_url.rstrip('/')}{rel}" if base_url else rel


def verify_asset_url(
    job_id: str,
    path: str,
    exp_str: str,
    u_str: str,
    sig: str,
    *,
    current_user_email: Optional[str] = None,
) -> None:
    """
    校验签名。失败抛 ValueError；成功静默返回。

    current_user_email:
        - 传入则强制"签名绑定用户 == 当前请求身份"。MVP 推荐开启。
        - 传 None 时跳过身份绑定校验（用于公开分享链接场景；目前不启用）。
    """
    try:
        exp = int(exp_str)
    except (TypeError, ValueError):
        raise ValueError("签名参数 exp 非法")

    if exp <= int(time.time()):
        raise ValueError("签名链接已过期")

    try:
        signed_user = _b64url_decode(u_str)
    except Exception:
        raise ValueError("签名参数 u 解码失败")

    if current_user_email is not None and signed_user != current_user_email:
        raise ValueError("签名链接与当前身份不匹配")

    canonical = _canonical(job_id, path, exp, signed_user)
    expected = hmac.new(
        safety_secret().encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # 常数时间比较，防时序侧信道
    if not hmac.compare_digest(expected, sig or ""):
        raise ValueError("签名校验失败")
