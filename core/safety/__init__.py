"""
core.safety — MVP 安全合规体系（Batch 1）

四层：
  0. auth          身份验证底座（Bearer + 反代 header + 白名单）
  1. input_guard   输入防护（文件白名单 + 素材分级 + 敏感词）
  2. llm_gateway   执行管控（限流 + 脱敏 + 审计）
  3. signed_url    输出审核（HMAC 签名资源链接）

公共基础设施：
  - audit_log      结构化 JSONL 审计日志
  - config         统一的配置加载（惰性单例）
"""

from core.safety.config import get_config, get_users, get_sensitive_terms

# 注意：不在包级再导出 audit_log / AuditLog，避免同名函数遮蔽 core.safety.audit_log 子模块。
# 调用方统一写：from core.safety.audit_log import audit_log, AuditLog

__all__ = [
    "get_config",
    "get_users",
    "get_sensitive_terms",
]
