"""
结构化审计日志（JSONL）

每天一个文件：logs/audit/YYYY-MM-DD.jsonl
每行一条事件，字段定长，便于后续用 jq / 导入 ES 做分析。

线程安全：用 threading.Lock 保证单进程内写入原子性；跨进程靠 append 模式 + OS 的
  O_APPEND 语义。MVP 单进程单机部署足够。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.safety.config import get_config

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AuditLog:
    def __init__(self, log_dir: Optional[Path] = None):
        cfg = get_config()
        self.log_dir = log_dir or (_PROJECT_ROOT / cfg["paths"]["audit_log_dir"])
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _current_file(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.log_dir / f"{day}.jsonl"

    def emit(
        self,
        event: str,
        *,
        user: Optional[str] = None,
        job_id: Optional[str] = None,
        resource: Optional[str] = None,
        outcome: str = "ok",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        写一条审计事件。

        Args:
            event: 事件名（upload / llm_call / asset_access / auth_failure …）
            user: 用户 email（未认证请求传 'anonymous'）
            job_id: 关联任务 id
            resource: 被操作的资源（文件路径、URL、模型名）
            outcome: ok / denied / error / rate_limited
            details: 任意结构化附加信息（tag、token 消耗、错误原因等）
        """
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "user": user or "anonymous",
            "job_id": job_id,
            "resource": resource,
            "outcome": outcome,
            "details": details or {},
            "pid": os.getpid(),
        }
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            with open(self._current_file(), "a", encoding="utf-8") as f:
                f.write(line)


_singleton: Optional[AuditLog] = None
_singleton_lock = threading.Lock()


def audit_log() -> AuditLog:
    """进程级单例。测试可传 log_dir 到 AuditLog() 另起实例。"""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = AuditLog()
    return _singleton
