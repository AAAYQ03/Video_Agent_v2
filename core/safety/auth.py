"""
身份验证底座

支持两种身份来源（按优先级）：
  1. 反向代理注入的 header（公司上了 SSO 网关之后）
     - header 名在 .env 的 SAFETY_TRUSTED_PROXY_HEADER 配置
     - 该 header 只在反代之后受信；直连本服务时应被网络层剥离
  2. Bearer Token（MVP 默认方式）
     - 前端登录时保存 token，每请求带 Authorization: Bearer <token>
     - token -> user 映射从 config/users.json 查

本模块只负责识别身份；授权（谁能做什么）由调用方根据 role 自己判断。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from core.safety.config import (
    auth_enabled,
    get_users,
    trusted_proxy_header,
)


@dataclass(frozen=True)
class User:
    email: str
    role: str  # admin / creator / viewer

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_write(self) -> bool:
        return self.role in ("admin", "creator")


# 不需要认证的路径前缀（健康检查、首页、静态资源的 OPTIONS 预检等）
# 注意：/assets 也要放行认证检查——它走独立的 signed URL 校验
PUBLIC_PATH_PREFIXES = (
    "/",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/health",
    "/api/auth/whoami",
)


def _is_public_path(path: str) -> bool:
    # 根路径严格匹配
    if path == "/":
        return True
    for p in PUBLIC_PATH_PREFIXES:
        if p == "/":
            continue
        if path == p or path.startswith(p + "/"):
            return True
    return False


def resolve_user_from_request(request: Request) -> Optional[User]:
    """
    从请求中解析身份。优先级：反代 header > Bearer Token。
    未认证返回 None；调用方决定是否拒绝。
    """
    users = get_users()
    by_email = {u["email"]: u for u in users}
    by_token = {u["token"]: u for u in users}

    # 1. 反代 header（优先）
    proxy_header = trusted_proxy_header()
    if proxy_header:
        email = request.headers.get(proxy_header, "").strip().lower()
        if email and email in by_email:
            u = by_email[email]
            return User(email=u["email"], role=u.get("role", "viewer"))

    # 2. Bearer Token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):].strip()
        if token and token in by_token:
            u = by_token[token]
            return User(email=u["email"], role=u.get("role", "viewer"))

    return None


async def auth_middleware(request: Request, call_next):
    """
    FastAPI 中间件：统一认证拦截 + 把 user 挂到 request.state.user。

    OPTIONS 预检一律放行；公共路径放行；其他路径必须认证。
    """
    if not auth_enabled():
        # 开发模式兜底：挂一个默认 admin，便于本地调试
        request.state.user = User(email="dev@local", role="admin")
        return await call_next(request)

    # CORS 预检
    if request.method == "OPTIONS":
        request.state.user = None
        return await call_next(request)

    # 公共路径放行（不要求 user，但如果带了 token 也解析出来方便日志）
    if _is_public_path(request.url.path):
        request.state.user = resolve_user_from_request(request)
        return await call_next(request)

    user = resolve_user_from_request(request)
    if user is None:
        # 审计：延迟到这里避免循环依赖（audit_log 也用 config）
        from core.safety.audit_log import audit_log

        audit_log().emit(
            "auth_failure",
            user="anonymous",
            resource=request.url.path,
            outcome="denied",
            details={"method": request.method},
        )
        return JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "message": "缺少或无效的身份凭证。请在请求 Header 中提供 Authorization: Bearer <token>",
            },
        )

    request.state.user = user
    return await call_next(request)


def require_user(request: Request) -> User:
    """FastAPI 依赖注入 / 手动调用：从 request.state 取 user，没有则抛 401。"""
    from fastapi import HTTPException

    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    return user


def require_admin(request: Request) -> User:
    u = require_user(request)
    if not u.is_admin:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="admin role required")
    return u
