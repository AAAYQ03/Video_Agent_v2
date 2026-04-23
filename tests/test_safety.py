"""
core.safety 单元测试（Batch 1）

覆盖：
  - auth: User 解析、反代 header 优先级、token 匹配、公共路径识别
  - input_guard: 文件白名单、素材分级、敏感词扫描
  - signed_url: 签名生成/校验、过期、用户不匹配、签名篡改
  - audit_log: JSONL 格式写入
  - llm_gateway: 限流、审计记录

不依赖任何外部 API（Gemini 等）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 测试环境变量（必须在 import safety 模块之前设定）
os.environ["SAFETY_SECRET"] = "test-secret-for-hmac-signing-long-enough"
os.environ["SAFETY_AUTH_ENABLED"] = "true"
os.environ.pop("SAFETY_TRUSTED_PROXY_HEADER", None)


@pytest.fixture(autouse=True)
def _reset_safety_cache():
    """每个测试前重置 config cache & gateway 单例，避免污染。"""
    from core.safety import config as cfg

    cfg.reload_config()
    # gateway 单例也重置
    import core.safety.llm_gateway as gw

    gw._gateway = None
    yield
    cfg.reload_config()
    gw._gateway = None


# ============================================================
# input_guard
# ============================================================


class TestInputGuard:
    def test_valid_video_file(self):
        from core.safety.input_guard import validate_upload_file

        validate_upload_file("ad.mp4", 100 * 1024 * 1024, "video/mp4")

    def test_valid_image_file(self):
        from core.safety.input_guard import validate_upload_file

        validate_upload_file("frame.png", 1024, "image/png")

    def test_reject_bad_extension(self):
        from core.safety.input_guard import validate_upload_file, InputGuardError

        with pytest.raises(InputGuardError) as e:
            validate_upload_file("payload.exe", 1024, "application/octet-stream")
        assert e.value.field == "file"

    def test_reject_oversize(self):
        from core.safety.input_guard import validate_upload_file, InputGuardError

        with pytest.raises(InputGuardError):
            validate_upload_file("huge.mp4", 999 * 1024 * 1024 * 1024, "video/mp4")

    def test_reject_bad_mime(self):
        from core.safety.input_guard import validate_upload_file, InputGuardError

        with pytest.raises(InputGuardError):
            validate_upload_file("doc.mp4", 1024, "application/pdf")

    def test_internal_tag_minimal(self):
        from core.safety.input_guard import validate_material_metadata, TAG_INTERNAL

        meta = validate_material_metadata(TAG_INTERNAL)
        assert meta.tag == TAG_INTERNAL
        assert not meta.contains_confidential

    def test_internal_tag_with_confidential(self):
        from core.safety.input_guard import validate_material_metadata, TAG_INTERNAL

        meta = validate_material_metadata(TAG_INTERNAL, contains_confidential=True)
        assert meta.contains_confidential is True

    def test_viral_ref_requires_source_url(self):
        from core.safety.input_guard import (
            validate_material_metadata,
            TAG_VIRAL_REF,
            InputGuardError,
        )

        with pytest.raises(InputGuardError) as e:
            validate_material_metadata(TAG_VIRAL_REF)
        assert e.value.field in ("reference_url", "reference_dimensions")

    def test_viral_ref_requires_dimensions(self):
        from core.safety.input_guard import (
            validate_material_metadata,
            TAG_VIRAL_REF,
            InputGuardError,
        )

        with pytest.raises(InputGuardError):
            validate_material_metadata(
                TAG_VIRAL_REF,
                reference_url="https://tiktok.com/xxx",
                reference_dimensions=[],
            )

    def test_viral_ref_valid(self):
        from core.safety.input_guard import validate_material_metadata, TAG_VIRAL_REF

        meta = validate_material_metadata(
            TAG_VIRAL_REF,
            reference_url="https://tiktok.com/xxx",
            reference_dimensions=["structure", "pacing"],
        )
        assert meta.reference_url == "https://tiktok.com/xxx"
        assert meta.reference_dimensions == ["structure", "pacing"]

    def test_viral_ref_rejects_unknown_dimension(self):
        from core.safety.input_guard import (
            validate_material_metadata,
            TAG_VIRAL_REF,
            InputGuardError,
        )

        with pytest.raises(InputGuardError) as e:
            validate_material_metadata(
                TAG_VIRAL_REF,
                reference_url="https://tiktok.com/xxx",
                reference_dimensions=["gibberish"],
            )
        assert e.value.field == "reference_dimensions"

    def test_unknown_tag_rejected(self):
        from core.safety.input_guard import validate_material_metadata, InputGuardError

        with pytest.raises(InputGuardError):
            validate_material_metadata("COMPETITOR")

    def test_sensitive_term_hit(self):
        from core.safety.input_guard import scan_sensitive_terms

        hits = scan_sensitive_terms("这段包含 PROJECT_OMEGA 的内容")
        assert "PROJECT_OMEGA" in hits

    def test_sensitive_term_case_insensitive(self):
        from core.safety.input_guard import scan_sensitive_terms

        hits = scan_sensitive_terms("project_omega 泄露了")
        assert "PROJECT_OMEGA" in hits

    def test_sensitive_term_clean(self):
        from core.safety.input_guard import scan_sensitive_terms

        assert scan_sensitive_terms("一段普通的广告文案") == []


# ============================================================
# signed_url
# ============================================================


class TestSignedUrl:
    def test_sign_and_verify_roundtrip(self):
        from core.safety.signed_url import sign_asset_url, verify_asset_url

        rel = sign_asset_url("job_abc", "videos/shot_01.mp4", "u@e.com", ttl_seconds=60)
        # 解析 query 参数
        qs = rel.split("?", 1)[1]
        params = dict(p.split("=") for p in qs.split("&"))
        verify_asset_url(
            job_id="job_abc",
            path="videos/shot_01.mp4",
            exp_str=params["exp"],
            u_str=params["u"],
            sig=params["sig"],
            current_user_email="u@e.com",
        )

    def test_expired_rejected(self):
        from core.safety.signed_url import sign_asset_url, verify_asset_url

        rel = sign_asset_url("job_abc", "a.png", "u@e.com", ttl_seconds=1)
        qs = rel.split("?", 1)[1]
        params = dict(p.split("=") for p in qs.split("&"))
        time.sleep(1.2)
        with pytest.raises(ValueError) as e:
            verify_asset_url(
                "job_abc", "a.png",
                params["exp"], params["u"], params["sig"],
                current_user_email="u@e.com",
            )
        assert "过期" in str(e.value)

    def test_user_mismatch_rejected(self):
        from core.safety.signed_url import sign_asset_url, verify_asset_url

        rel = sign_asset_url("job_abc", "a.png", "alice@e.com", ttl_seconds=60)
        qs = rel.split("?", 1)[1]
        params = dict(p.split("=") for p in qs.split("&"))
        with pytest.raises(ValueError) as e:
            verify_asset_url(
                "job_abc", "a.png",
                params["exp"], params["u"], params["sig"],
                current_user_email="bob@e.com",
            )
        assert "不匹配" in str(e.value)

    def test_signature_tampering_rejected(self):
        from core.safety.signed_url import sign_asset_url, verify_asset_url

        rel = sign_asset_url("job_abc", "a.png", "u@e.com", ttl_seconds=60)
        qs = rel.split("?", 1)[1]
        params = dict(p.split("=") for p in qs.split("&"))
        # 篡改 path
        with pytest.raises(ValueError):
            verify_asset_url(
                "job_abc", "b.png",  # 原签名是 a.png
                params["exp"], params["u"], params["sig"],
                current_user_email="u@e.com",
            )

    def test_bad_exp_format(self):
        from core.safety.signed_url import verify_asset_url

        with pytest.raises(ValueError):
            verify_asset_url("j", "p", "not-a-number", "dXNlcg", "abc123",
                             current_user_email="u@e.com")


# ============================================================
# auth
# ============================================================


class TestAuth:
    def _make_request(self, headers=None, path="/api/upload", method="POST"):
        from starlette.datastructures import Headers

        req = MagicMock()
        req.headers = Headers(headers or {})
        req.url.path = path
        req.method = method
        req.state = MagicMock()
        return req

    def test_token_resolves_user(self, tmp_path, monkeypatch):
        # 用临时 users 文件，避免依赖仓库的示例用户
        users_file = tmp_path / "users.json"
        users_file.write_text(json.dumps({
            "users": [
                {"email": "alice@x.com", "token": "sk-t-alice", "role": "creator", "active": True},
                {"email": "admin@x.com", "token": "sk-t-admin", "role": "admin", "active": True},
            ]
        }))
        self._patch_users_file(monkeypatch, users_file)

        from core.safety.auth import resolve_user_from_request

        req = self._make_request({"Authorization": "Bearer sk-t-alice"})
        u = resolve_user_from_request(req)
        assert u is not None and u.email == "alice@x.com" and u.role == "creator"

    def test_invalid_token_returns_none(self, tmp_path, monkeypatch):
        users_file = tmp_path / "users.json"
        users_file.write_text(json.dumps({"users": []}))
        self._patch_users_file(monkeypatch, users_file)

        from core.safety.auth import resolve_user_from_request

        req = self._make_request({"Authorization": "Bearer fake"})
        assert resolve_user_from_request(req) is None

    def test_proxy_header_takes_priority(self, tmp_path, monkeypatch):
        users_file = tmp_path / "users.json"
        users_file.write_text(json.dumps({
            "users": [
                {"email": "alice@x.com", "token": "sk-t-alice", "role": "creator", "active": True},
            ]
        }))
        self._patch_users_file(monkeypatch, users_file)
        monkeypatch.setenv("SAFETY_TRUSTED_PROXY_HEADER", "X-User-Email")

        from core.safety.auth import resolve_user_from_request

        # 同时带 header 和 token；header 为已知用户应优先
        req = self._make_request({
            "X-User-Email": "alice@x.com",
            "Authorization": "Bearer wrong-token",
        })
        u = resolve_user_from_request(req)
        assert u is not None and u.email == "alice@x.com"

    def test_public_path_detection(self):
        from core.safety.auth import _is_public_path

        assert _is_public_path("/")
        assert _is_public_path("/api/health")
        assert _is_public_path("/api/auth/whoami")
        assert _is_public_path("/docs")
        assert not _is_public_path("/api/upload")
        assert not _is_public_path("/api/agent/chat")

    def _patch_users_file(self, monkeypatch, path: Path):
        """把 config 指向临时 users.json。"""
        from core.safety import config as cfg

        cfg.reload_config()
        real_get_config = cfg.get_config

        def patched_get_config(_=None):
            data = real_get_config()
            data = dict(data)
            data["paths"] = dict(data["paths"])
            data["paths"]["users_file"] = str(path.relative_to(path.parents[1]))
            return data

        # 更简单的方法：直接让 get_users 读取我们的文件
        def patched_get_users():
            raw = json.loads(path.read_text()).get("users", [])
            return [u for u in raw if u.get("active", True)]

        monkeypatch.setattr(cfg, "get_users", patched_get_users)
        # auth 模块从 core.safety.config 导入了 get_users，需要同步替换
        import core.safety.auth as auth_mod
        monkeypatch.setattr(auth_mod, "get_users", patched_get_users)


# ============================================================
# audit_log
# ============================================================


class TestAuditLog:
    def test_emit_writes_jsonl(self, tmp_path):
        from core.safety.audit_log import AuditLog

        log = AuditLog(log_dir=tmp_path)
        log.emit(
            "upload",
            user="alice@x.com",
            job_id="job_1",
            resource="video.mp4",
            outcome="ok",
            details={"tag": "INTERNAL"},
        )
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["event"] == "upload"
        assert rec["user"] == "alice@x.com"
        assert rec["details"]["tag"] == "INTERNAL"
        assert "ts" in rec

    def test_multiple_events_append(self, tmp_path):
        from core.safety.audit_log import AuditLog

        log = AuditLog(log_dir=tmp_path)
        for i in range(5):
            log.emit("test", user=f"u{i}@x.com")
        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        assert len(lines) == 5


# ============================================================
# llm_gateway
# ============================================================


class TestLLMGateway:
    def test_successful_call_records_audit(self, tmp_path, monkeypatch):
        # 用临时审计目录
        import core.safety.audit_log as audit_mod

        audit_mod._singleton = None
        monkeypatch.setattr(audit_mod, "AuditLog", _make_audit_factory(tmp_path))

        from core.safety.llm_gateway import LLMGateway, GatewayRequest

        gw = LLMGateway()
        result = gw.call(GatewayRequest(
            user_email="creator1@example.com",
            task="intent_parse",
            material_tag="INTERNAL",
            prompt="hello",
            call=lambda p: f"echo:{p}",
            model_name="gemini-test",
        ))
        assert result == "echo:hello"

        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        events = [json.loads(l)["outcome"] for l in lines]
        assert "start" in events and "ok" in events

    def test_rate_limit_triggers(self, tmp_path, monkeypatch):
        import core.safety.audit_log as audit_mod

        audit_mod._singleton = None
        monkeypatch.setattr(audit_mod, "AuditLog", _make_audit_factory(tmp_path))

        from core.safety.llm_gateway import (
            LLMGateway,
            GatewayRequest,
            _InMemoryRateLimiter,
            RateLimitExceeded,
        )

        # 人为把小时上限压到 2
        gw = LLMGateway(rate_limiter=_InMemoryRateLimiter(per_hour=2, per_day=1000))
        req_factory = lambda: GatewayRequest(
            user_email="u@x.com",
            task="t",
            material_tag="INTERNAL",
            prompt="x",
            call=lambda p: "ok",
        )
        gw.call(req_factory())
        gw.call(req_factory())
        with pytest.raises(RateLimitExceeded) as e:
            gw.call(req_factory())
        assert e.value.window == "per_hour"

    def test_call_error_recorded(self, tmp_path, monkeypatch):
        import core.safety.audit_log as audit_mod

        audit_mod._singleton = None
        monkeypatch.setattr(audit_mod, "AuditLog", _make_audit_factory(tmp_path))

        from core.safety.llm_gateway import LLMGateway, GatewayRequest

        gw = LLMGateway()

        def boom(_):
            raise RuntimeError("upstream died")

        with pytest.raises(RuntimeError):
            gw.call(GatewayRequest(
                user_email="u@x.com",
                task="t",
                material_tag="INTERNAL",
                prompt="x",
                call=boom,
            ))
        lines = list(tmp_path.glob("*.jsonl"))[0].read_text().strip().splitlines()
        outcomes = [json.loads(l)["outcome"] for l in lines]
        assert "error" in outcomes


def _make_audit_factory(dir_):
    from core.safety.audit_log import AuditLog

    def factory(log_dir=None):
        return AuditLog(log_dir=dir_)
    return factory
