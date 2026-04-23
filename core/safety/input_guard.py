"""
输入防护

三件事：
  1. 文件校验：扩展名白名单、大小上限、MIME 前缀校验
  2. 素材分级：INTERNAL（默认） / VIRAL_REF（爆款参考必填参考源 + 参考维度）
  3. 敏感词扫描：对自然语言指令 / 参考描述做敏感词命中检测

业务约束（来自产品定义）：
  - INTERNAL 可选 contains_confidential=true，勾选后 admin 才能导出
  - VIRAL_REF 必须提供 reference_url 与至少 1 个 reference_dimensions
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

from core.safety.config import get_config, get_sensitive_terms


# 素材分级枚举（作为字符串常量使用，便于 JSON 序列化）
TAG_INTERNAL = "INTERNAL"
TAG_VIRAL_REF = "VIRAL_REF"
VALID_TAGS: Set[str] = {TAG_INTERNAL, TAG_VIRAL_REF}


class InputGuardError(ValueError):
    """输入校验失败。携带 HTTP 可见的简短 reason。"""

    def __init__(self, reason: str, field: Optional[str] = None):
        super().__init__(reason)
        self.reason = reason
        self.field = field


@dataclass
class MaterialMetadata:
    """校验通过后的素材元数据，写入 job 目录便于后续审计。"""

    tag: str
    contains_confidential: bool = False
    reference_url: Optional[str] = None
    reference_dimensions: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "contains_confidential": self.contains_confidential,
            "reference_url": self.reference_url,
            "reference_dimensions": self.reference_dimensions,
        }


# ---------- 文件校验 ----------


def validate_upload_file(
    filename: str,
    size_bytes: int,
    content_type: Optional[str] = None,
) -> None:
    """校验上传文件的扩展名、大小、MIME。不合法则抛 InputGuardError。"""
    cfg = get_config()["upload"]

    # 扩展名白名单
    ext = Path(filename).suffix.lower()
    allowed_ext = {e.lower() for e in cfg["allowed_extensions"]}
    if ext not in allowed_ext:
        raise InputGuardError(
            f"不支持的文件类型 '{ext}'，仅允许：{', '.join(sorted(allowed_ext))}",
            field="file",
        )

    # 大小上限
    max_bytes = cfg["max_file_size_mb"] * 1024 * 1024
    if size_bytes > max_bytes:
        raise InputGuardError(
            f"文件过大（{size_bytes / 1024 / 1024:.1f} MB），"
            f"上限 {cfg['max_file_size_mb']} MB",
            field="file",
        )

    # MIME 前缀
    if content_type:
        prefixes = tuple(cfg["allowed_mime_prefixes"])
        if not content_type.startswith(prefixes):
            raise InputGuardError(
                f"不支持的 MIME 类型 '{content_type}'，"
                f"仅允许：{', '.join(prefixes)}",
                field="file",
            )


# ---------- 素材分级校验 ----------


def validate_material_metadata(
    tag: str,
    *,
    contains_confidential: bool = False,
    reference_url: Optional[str] = None,
    reference_dimensions: Optional[List[str]] = None,
) -> MaterialMetadata:
    """校验素材分级字段。合法返回规整化的 MaterialMetadata；否则抛。"""
    cfg_tags = get_config()["material_tags"]

    if tag not in VALID_TAGS:
        raise InputGuardError(
            f"非法的 material_tag '{tag}'。仅允许：{', '.join(sorted(VALID_TAGS))}",
            field="material_tag",
        )

    tag_cfg = cfg_tags.get(tag, {})

    if tag == TAG_INTERNAL:
        return MaterialMetadata(
            tag=tag,
            contains_confidential=bool(contains_confidential),
        )

    # VIRAL_REF
    if tag_cfg.get("requires_reference_source", False):
        if not reference_url or not reference_url.strip():
            raise InputGuardError(
                "爆款参考必须提供 reference_url（参考源链接）",
                field="reference_url",
            )

    dims = [d.strip() for d in (reference_dimensions or []) if d and d.strip()]
    allowed_dims = set(tag_cfg.get("allowed_reference_dimensions", []))
    if allowed_dims:
        bad = [d for d in dims if d not in allowed_dims]
        if bad:
            raise InputGuardError(
                f"非法的 reference_dimensions {bad}。允许：{sorted(allowed_dims)}",
                field="reference_dimensions",
            )

    min_dims = tag_cfg.get("min_reference_dimensions", 0)
    if len(dims) < min_dims:
        raise InputGuardError(
            f"爆款参考必须至少提供 {min_dims} 个 reference_dimensions",
            field="reference_dimensions",
        )

    return MaterialMetadata(
        tag=tag,
        contains_confidential=False,  # VIRAL_REF 不支持保密勾选
        reference_url=reference_url.strip() if reference_url else None,
        reference_dimensions=dims,
    )


# ---------- 文本 / Prompt 校验 ----------


def validate_prompt(text: str) -> None:
    """自然语言指令长度上限校验。"""
    cfg = get_config()["upload"]
    if text is None:
        return
    if len(text) > cfg["max_prompt_chars"]:
        raise InputGuardError(
            f"指令过长（{len(text)} 字符），上限 {cfg['max_prompt_chars']}",
            field="prompt",
        )


def scan_sensitive_terms(text: str) -> List[str]:
    """
    扫描文本中的敏感词命中项。不抛异常——调用方决定怎么处理。
    MVP 阶段大小写不敏感的子串匹配即可，后续可换 Aho-Corasick。
    """
    if not text:
        return []
    haystack = text.lower()
    hits: List[str] = []
    for term in get_sensitive_terms():
        if term and term.lower() in haystack:
            hits.append(term)
    return hits
