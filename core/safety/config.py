"""
Safety 模块的统一配置加载器。

设计要点：
- 惰性加载 + 进程级缓存，避免每请求读盘
- 测试里可调用 reload_config() 打破缓存
- 读取 config/safety_config.json + config/users.json + config/sensitive_terms.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_SAFETY_CONFIG_PATH = _PROJECT_ROOT / "config" / "safety_config.json"

_cache: Dict[str, Any] = {}


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """读取 safety_config.json；带进程级缓存。"""
    if "safety" in _cache and path is None:
        return _cache["safety"]
    cfg_path = path or _DEFAULT_SAFETY_CONFIG_PATH
    data = _load_json(cfg_path)
    if path is None:
        _cache["safety"] = data
    return data


def get_users() -> List[Dict[str, Any]]:
    """读取 users.json，返回 active 用户列表。"""
    if "users" in _cache:
        return _cache["users"]
    cfg = get_config()
    users_path = _PROJECT_ROOT / cfg["paths"]["users_file"]
    if not users_path.exists():
        _cache["users"] = []
        return []
    raw = _load_json(users_path).get("users", [])
    active = [u for u in raw if u.get("active", True)]
    _cache["users"] = active
    return active


def get_sensitive_terms() -> List[str]:
    """读取 sensitive_terms.json 并铺平所有分类成单一列表。"""
    if "sensitive_terms" in _cache:
        return _cache["sensitive_terms"]
    cfg = get_config()
    path = _PROJECT_ROOT / cfg["paths"]["sensitive_terms_file"]
    if not path.exists():
        _cache["sensitive_terms"] = []
        return []
    data = _load_json(path)
    terms: List[str] = []
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            terms.extend(str(t) for t in value)
    _cache["sensitive_terms"] = terms
    return terms


def reload_config() -> None:
    """清空进程级缓存——测试与热更新使用。"""
    _cache.clear()


def safety_secret() -> str:
    """返回 HMAC 密钥。未配置则在生产模式下抛错，开发模式下给警告兜底。"""
    secret = os.environ.get("SAFETY_SECRET", "").strip()
    if not secret or secret == "REPLACE_ME_WITH_RANDOM_48_CHAR_SECRET":
        if os.environ.get("SAFETY_AUTH_ENABLED", "true").lower() == "false":
            # 开发模式兜底，仅用于本地跑测试
            return "dev-only-insecure-secret-do-not-use-in-prod"
        raise RuntimeError(
            "SAFETY_SECRET 未配置或仍是占位符。"
            "请在 .env 里填随机密钥（参考 .env.example）"
        )
    return secret


def auth_enabled() -> bool:
    return os.environ.get("SAFETY_AUTH_ENABLED", "true").lower() != "false"


def trusted_proxy_header() -> Optional[str]:
    v = os.environ.get("SAFETY_TRUSTED_PROXY_HEADER", "").strip()
    return v or None
