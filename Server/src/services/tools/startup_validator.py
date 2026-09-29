"""
Startup Validator — cross-validates the Python tool_action_registry.json
against Unity's live registered handlers at server startup.

Verification flow:
    1. Load tool_action_registry.json
    2. Connect to Unity via TCP
    3. Call manage_editor → get_registered_actions to get Unity's handler list
    4. Compare registry entries against Unity handlers
    5. Output PASS/WARN/ERROR report

Usage:
    from services.tools.startup_validator import validate_registry

    report = await validate_registry()
    # report["status"]: "pass" | "warning" | "error"
    # report["details"]: list of issues found
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from services.tools.tool_router import ToolRouter, get_router

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "tool_action_registry.json")


class ValidationReport:
    """Structured result of a registry-vs-Unity cross-check."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []
        self.status: str = "pending"
        self.unity_handlers: set[str] = set()
        self.registry_handlers: set[str] = set()
        self.registry_tool_count: int = 0
        self.validation_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "unity_handler_count": len(self.unity_handlers),
            "registry_handler_count": len(self.registry_handlers),
            "registry_tool_count": self.registry_tool_count,
            "validation_duration_ms": round(self.validation_duration_ms, 1),
            "timestamp": time.time(),
        }

    def summary(self) -> str:
        lines = [
            f"=== Registry Validation: {self.status.upper()} ===",
            f"  Registry: {self.registry_tool_count} tools → {len(self.registry_handlers)} Unity handlers",
            f"  Unity:    {len(self.unity_handlers)} handlers live",
            f"  Duration: {self.validation_duration_ms:.0f} ms",
        ]
        if self.errors:
            lines.append(f"  ERRORS ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"    - {e}")
        if self.warnings:
            lines.append(f"  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"    - {w}")
        return "\n".join(lines)


async def validate_registry(
    router: ToolRouter | None = None,
    timeout: float = 10.0,
) -> ValidationReport:
    """Main entry point: cross-validate the registry against live Unity.

    Args:
        router: Optional ToolRouter instance. Created if not provided.
        timeout: Maximum seconds to wait for Unity response.

    Returns:
        ValidationReport with status and details.
    """
    report = ValidationReport()
    t_start = time.time()

    if router is None:
        try:
            router = get_router()
        except Exception as ex:
            report.errors.append(f"Failed to load ToolRouter: {ex}")
            report.status = "error"
            report.validation_duration_ms = (time.time() - t_start) * 1000
            return report

    report.registry_tool_count = len(router._routes)
    report.registry_handlers = set(router.list_all_unity_handlers())

    # ── Try to query Unity for its live handler list ─────────────────
    try:
        from services.tools.unity_bridge import send_to_unity

        unity_response = await asyncio.wait_for(
            send_to_unity("manage_editor", {"action": "get_registered_actions"}),
            timeout=timeout,
        )

        result = unity_response.get("result", {})
        handlers_list = result.get("handlers", [])
        report.unity_handlers = set(str(h).lower() for h in handlers_list)
        report.info.append(
            f"Unity reported {len(report.unity_handlers)} live handlers"
        )

    except asyncio.TimeoutError:
        report.errors.append(
            f"Unity did not respond within {timeout}s. "
            "Is Unity Editor running with MCP plugin enabled?"
        )
        report.status = "error"
        report.validation_duration_ms = (time.time() - t_start) * 1000
        return report

    except Exception as ex:
        report.warnings.append(
            f"Could not query Unity handlers: {ex}. "
            "Skipping cross-check; assuming registry is authoritative."
        )
        report.status = "warning"
        report.validation_duration_ms = (time.time() - t_start) * 1000
        return report

    # ── Cross-reference ──────────────────────────────────────────────

    if not report.unity_handlers:
        report.errors.append(
            "Unity returned empty handler list. "
            "ToolDispatcher may not have registered any handlers."
        )
        report.status = "error"
        report.validation_duration_ms = (time.time() - t_start) * 1000
        return report

    # Check: registry handlers that Unity doesn't know about
    missing_in_unity = report.registry_handlers - report.unity_handlers
    if missing_in_unity:
        for handler in sorted(missing_in_unity):
            report.errors.append(
                f"Registry handler '{handler}' NOT found in Unity. "
                f"Tools routing to '{handler}' will fail."
            )

    # Check: Unity handlers that registry doesn't know about
    missing_in_registry = report.unity_handlers - report.registry_handlers
    if missing_in_registry:
        for handler in sorted(missing_in_registry):
            report.warnings.append(
                f"Unity handler '{handler}' NOT in registry. "
                f"Consider adding to tool_action_registry.json."
            )

    # Final status
    if report.errors:
        report.status = "error"
    elif report.warnings:
        report.status = "warning"
    else:
        report.status = "pass"
        report.info.append("All registry handlers match Unity's live handlers.")

    report.validation_duration_ms = (time.time() - t_start) * 1000
    return report


async def validate_or_warn() -> bool:
    """Convenience: validate and log results. Returns True if passed."""
    report = await validate_registry()
    summary = report.summary()
    print(summary)

    if report.status == "error":
        logger.error(summary)
        return False
    elif report.status == "warning":
        logger.warning(summary)
        return True  # warnings don't block startup
    else:
        logger.info(summary)
        return True
