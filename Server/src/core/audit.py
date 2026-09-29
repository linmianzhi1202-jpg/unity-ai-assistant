"""
Audit Logging Module for the Unified MCP for Unity system.
Records operation audit trails with configurable verbosity and log rotation.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AuditEntry(BaseModel):
    """Single audit log entry."""
    timestamp: float
    action: str              # tool_name or operation
    user_id: str | None = None
    role: str | None = None
    unity_instance: str | None = None
    params_summary: str | None = None  # truncated param summary (never log secrets)
    result: str = ""         # "success" | "denied" | "error"
    error_code: int | None = None
    duration_ms: float | None = None


class AuditLogger:
    """Thread-safe audit logger with file rotation.

    Audit logs record:
    - Who (user_id + role)
    - What (tool_name + params summary)
    - When (timestamp)
    - Where (unity_instance)
    - Result (success/denied/error + error_code)
    - How long (duration_ms)
    """

    def __init__(self, log_path: str | Path, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> None:
        self._log_path = Path(log_path)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._logger = logging.getLogger("unified_mcp.audit")

        # Set up file handler
        self._setup_file_handler()

    def _setup_file_handler(self) -> None:
        """Configure the audit file handler with rotation."""
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

        from logging.handlers import RotatingFileHandler
        handler = RotatingFileHandler(
            self._log_path,
            maxBytes=self._max_bytes,
            backupCount=self._backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.setLevel(logging.INFO)

        # Avoid duplicate handlers
        if not self._logger.handlers:
            self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

    def record(
        self,
        action: str,
        result: str = "success",
        user_id: str | None = None,
        role: str | None = None,
        unity_instance: str | None = None,
        params: dict[str, Any] | None = None,
        error_code: int | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Record an audit entry.

        Args:
            action: The tool name or operation being audited.
            result: "success", "denied", or "error".
            user_id: The user who initiated the action.
            role: The user's role.
            unity_instance: Target Unity instance identifier.
            params: Tool parameters (will be summarized, secrets stripped).
            error_code: UnifiedErrorCode value if result is "error".
            duration_ms: How long the operation took.
        """
        # Summarize params, stripping sensitive keys
        params_summary = None
        if params:
            safe_params = {
                k: ("***" if k in {"api_key", "password", "secret", "token", "key"} else str(v)[:100])
                for k, v in params.items()
            }
            params_summary = json.dumps(safe_params, ensure_ascii=False)[:500]

        entry = AuditEntry(
            timestamp=time.time(),
            action=action,
            user_id=user_id,
            role=role,
            unity_instance=unity_instance,
            params_summary=params_summary,
            result=result,
            error_code=error_code,
            duration_ms=duration_ms,
        )

        self._logger.info(entry.model_dump_json())

    def query_recent(self, count: int = 100, filter_result: str | None = None) -> list[AuditEntry]:
        """Query recent audit entries from the log file.

        Args:
            count: Maximum number of entries to return.
            filter_result: Optional filter by result type.

        Returns:
            List of AuditEntry objects, most recent last.
        """
        entries: list[AuditEntry] = []
        if not self._log_path.exists():
            return entries

        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
            for line in reversed(lines):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditEntry(**data)
                    if filter_result and entry.result != filter_result:
                        continue
                    entries.append(entry)
                    if len(entries) >= count:
                        break
                except Exception:
                    continue
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")

        entries.reverse()
        return entries
