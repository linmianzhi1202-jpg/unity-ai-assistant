"""
Testing Tools for the Unified MCP for Unity system.
Provides MCP tools for running tests and batch execution.
Group: testing

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1C.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import asyncio
import math
import uuid
import json
import logging
from typing import Any

from fastmcp import FastMCP
from services.tools.unity_bridge import ExecutionUncertainError, ProjectSelectionError

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_testing_tools(mcp: FastMCP) -> None:
    """Register Testing tools with the MCP server."""
    group = "testing"


    @mcp.tool(tags=make_group_tags("testing"))
    async def run_tests(
        test_filter: str | None = None,
        test_mode: str = "EditMode",
        timeout: float = 300.0,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Run Unity EditMode or PlayMode tests and wait for verified results.

        Args:
            test_filter: Optional literal fixture/method name, optionally namespace-qualified.
            test_mode: EditMode or PlayMode (default: EditMode).
            timeout: Maximum local wait in seconds; expiry does not stop running Unity tests.
            run_id: Resume waiting for an existing run without submitting another run.
        """
        if test_mode not in {"EditMode", "PlayMode"} or not math.isfinite(timeout) or timeout <= 0:
            return {"success": False, "tool": "run_tests", "state": "error", "error": "Use EditMode/PlayMode and a finite positive timeout"}
        if run_id is not None:
            try:
                if uuid.UUID(run_id).hex != run_id:
                    raise ValueError()
            except (ValueError, AttributeError):
                return {"success": False, "tool": "run_tests", "state": "error", "error": "Invalid run_id"}
        existing = run_id is not None
        identifier = run_id or uuid.uuid4().hex
        params = {"test_filter": test_filter, "test_mode": test_mode, "timeout": timeout}
        result = {}
        async def wait_for_result():
            nonlocal result
            if not existing:
                try:
                    response = await get_router().send_tool("run_tests", {
                        "action": "start", "run_id": identifier, "test_filter": test_filter, "test_mode": test_mode})
                    if response.get("status") != "success":
                        raise RuntimeError(response.get("error", "Unity could not start tests"))
                    result = response.get("result", {})
                except ExecutionUncertainError:
                    # Submission may have reached Unity. Only query this ID; never replay start.
                    pass
            while True:
                if result.get("state") in {"passed", "failed", "no_tests", "error", "interrupted"}:
                    success = result.get("state") == "passed" and result.get("success") is True and result.get("passed", 0) > 0
                    return {"success": success, "tool": "run_tests", "params": params,
                            "run_id": identifier, "state": result["state"], "results": result,
                            "error": result.get("error"),
                            "message": "Tests passed" if success else result.get("error", "Tests did not pass")}
                await asyncio.sleep(.25)
                try:
                    response = await get_router().send_tool("run_tests", {"action": "status", "run_id": identifier})
                except ProjectSelectionError:
                    # A domain reload briefly removes the selected instance heartbeat.
                    # UnityBridge remains bound to the same project.
                    continue
                except ConnectionError:
                    continue
                if response.get("status") != "success":
                    raise RuntimeError(response.get("error", "Cannot read test results"))
                result = response.get("result", {})

        try:
            return await asyncio.wait_for(wait_for_result(), timeout)
        except asyncio.TimeoutError:
            return {"success": False, "tool": "run_tests", "params": params, "run_id": identifier,
                    "state": "timeout", "results": result,
                    "error": "Local wait timed out; Unity tests may still be running. Query run_tests with this run_id; do not resubmit."}
        except asyncio.CancelledError:
            logger.info("Stopped waiting for test run %s; Unity execution was not cancelled", identifier)
            raise
        except Exception as error:
            return {"success": False, "tool": "run_tests", "params": params, "run_id": identifier,
                    "state": "error", "results": result, "error": str(error)}

    @mcp.tool(tags=make_group_tags("testing"))
    async def batch_execute(
        commands: str,
        stop_on_error: bool = True,
    ) -> dict[str, Any]:
        """Execute multiple tool commands in a single batch.

        Args:
            commands: JSON array of command objects: [{"tool":"create_game_object","params":{...}},...].
            stop_on_error: Whether to stop execution on first error (default: true).
        """
        # Parse JSON string to object so Unity's C# sees a proper JArray
        try:
            parsed_commands = json.loads(commands) if isinstance(commands, str) else commands
        except json.JSONDecodeError:
            return {"success": False, "error": "commands must be a JSON array"}
        if not isinstance(parsed_commands, list) or not parsed_commands:
            return {"success": False, "error": "commands must be a nonempty JSON array"}
        for command in parsed_commands:
            if not isinstance(command, dict) or not command.get("tool"):
                return {"success": False, "error": "Each command requires tool and params/arguments"}
            if get_router().resolve(command["tool"]) is None or command["tool"] == "batch_execute":
                return {"success": False, "error": f"No Unity route for {command['tool']}"}
            if not isinstance(command.get("arguments", command.get("params", {})), dict):
                return {"success": False, "error": "Command parameters must be an object"}
        results, errors = [], []
        for command in parsed_commands:
            name = command["tool"]
            try:
                response = await mcp.call_tool(name, command.get("arguments", command.get("params", {})))
                payload = response.structured_content
                if payload is None:
                    payload = [item.model_dump(mode="json") for item in response.content]
                failed = response.is_error or (isinstance(payload, dict) and
                    (payload.get("success") is False or payload.get("status") in {"error", "failed"}))
                entry = {"tool": name, "status": "error" if failed else "success", "result": payload}
            except Exception as error:
                failed = True
                entry = {"tool": name, "status": "error", "error": str(error)}
            results.append(entry)
            if failed:
                errors.append(entry)
                if stop_on_error:
                    break
        return {
            "success": not errors, "tool": "batch_execute",
            "params": {"commands": commands, "stop_on_error": stop_on_error},
            "results": {"results": results, "count": len(parsed_commands), "executed": len(results),
                        "ok": len(results) - len(errors), "fail": len(errors), "errors": errors},
            "message": "Batch execution completed" if not errors else "Batch contains failed commands",
            "error": f"{len(errors)} batch command(s) failed" if errors else None,
        }
