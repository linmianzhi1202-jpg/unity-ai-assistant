"""
Agent Tools for the Unified MCP for Unity system.
Provides MCP tools for Unity Editor interaction: logs, state, hierarchy, scripting.
Group: core

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1D.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import asyncio
import logging
import re
import time
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags
from services.tools.unity_bridge import send_to_unity

logger = logging.getLogger(__name__)


def register_agent_tools(mcp: FastMCP) -> None:
    """Register Agent tools with the MCP server."""
    group = "core"

    @mcp.tool(tags=make_group_tags("core"))
    async def get_unity_logs(
        skip_newest_n_logs: int = 0,
        limit: int = 100,
        show_logs: bool = True,
        show_warnings: bool = True,
        show_errors: bool = True,
        show_stack_traces: bool = True,
        search_term: str | None = None,
        clear_buffer: bool = False,
        since_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Get logs from the Unity Editor console buffer, ordered chronologically.

        Time-filtered by default: only returns logs after the last refresh_unity call.
        Use clear_buffer=True to wipe the in-memory buffer (good after fixing errors).
        Use since_seconds to override the cutoff (e.g. 30 = last 30 seconds only).

        Args:
            skip_newest_n_logs: Number of most recent log entries to skip (default: 0).
            limit: Maximum number of log entries to return (default: 100).
            show_logs: Include INFO level logs (default: true).
            show_warnings: Include WARNING level logs (default: true).
            show_errors: Include ERROR/EXCEPTION level logs (default: true).
            show_stack_traces: Include stack traces (default: true).
            search_term: Only include logs containing this text (case-insensitive).
            clear_buffer: Clear all buffered logs (default: false).
            since_seconds: Only return logs from the last N seconds. Overrides refresh-time cutoff.
        """
        args: dict[str, Any] = {'skip_newest_n_logs': skip_newest_n_logs, 'limit': limit, 'show_logs': show_logs, 'show_warnings': show_warnings, 'show_errors': show_errors, 'show_stack_traces': show_stack_traces}
        if search_term:
            args["search_term"] = search_term
        if clear_buffer:
            args["clear_buffer"] = True
        if since_seconds is not None and since_seconds > 0:
            args["since_seconds"] = since_seconds

        try:
            result = await get_router().send_tool('get_unity_logs', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "get_unity_logs",
                "params": {"skip_newest_n_logs": skip_newest_n_logs, "limit": limit,
                           "show_logs": show_logs, "show_warnings": show_warnings,
                           "show_errors": show_errors, "show_stack_traces": show_stack_traces,
                           "search_term": search_term, "clear_buffer": clear_buffer,
                           "since_seconds": since_seconds},
                "logs": unity_result.get("logs", []),
                "count": unity_result.get("count", 0),
                "total_buffered": unity_result.get("total_buffered"),
                "filtered_by_time": unity_result.get("filtered_by_time"),
                "cutoff_time": unity_result.get("cutoff_time"),
                "message": f"Retrieved {unity_result.get('count', 0)} log entries",
            }
        except Exception as ex:
            logger.error(f"Failed to get Unity logs: {ex}")
            return {
                "success": False,
                "tool": "get_unity_logs",
                "error": str(ex),
                "message": str(ex),
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def get_unity_editor_state() -> dict[str, Any]:
        """Retrieve the current state of the Unity Editor, excluding scene hierarchy."""
        args: dict[str, Any] = {}

        try:
            result = await get_router().send_tool('get_unity_editor_state', args)
            return {
                "success": result.get("status") == "success",
                "tool": "get_unity_editor_state",
                "state": result.get("result", {}),
                "message": "Retrieved Unity editor state",
            }
        except Exception as ex:
            logger.error(f"Failed to get editor state: {ex}")
            return {
                "success": False,
                "tool": "get_unity_editor_state",
                "error": str(ex),
                "message": str(ex),
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def list_game_objects_in_hierarchy(
        name_filter: str | None = None,
        tag_filter: str | None = None,
        component_filter: str | None = None,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """List GameObjects in the scene hierarchy with optional filtering.

        Args:
            name_filter: Optional name substring filter (case-insensitive).
            tag_filter: Optional tag filter.
            component_filter: Optional component type filter (e.g., 'Rigidbody').
            max_depth: Optional maximum traversal depth in hierarchy.
        """
        args: dict[str, Any] = {}
        if name_filter:
            args["name_filter"] = name_filter
        if tag_filter:
            args["tag_filter"] = tag_filter
        if component_filter:
            args["component_filter"] = component_filter
        if max_depth is not None:
            args["max_depth"] = max_depth

        try:
            result = await get_router().send_tool('list_game_objects_in_hierarchy', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "list_game_objects_in_hierarchy",
                "params": {"name_filter": name_filter, "tag_filter": tag_filter,
                           "component_filter": component_filter, "max_depth": max_depth},
                "hierarchy": unity_result.get("hierarchy", []),
                "message": "Listed scene hierarchy",
            }
        except Exception as ex:
            logger.error(f"Failed to list hierarchy: {ex}")
            return {
                "success": False,
                "tool": "list_game_objects_in_hierarchy",
                "error": str(ex),
                "message": str(ex),
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def get_game_object_info(
        gameobject_path: str,
        include_children: bool = True,
        include_components: bool = True,
    ) -> dict[str, Any]:
        """Get detailed information about a GameObject, including AABB bounds.

        Args:
            gameobject_path: Path to the GameObject in the hierarchy.
            include_children: Whether to include child objects (default: true).
            include_components: Whether to include component details (default: true).
        """
        args: dict[str, Any] = {'path': gameobject_path, 'include_children': include_children, 'include_components': include_components}

        try:
            result = await get_router().send_tool('get_game_object_info', args)
            unity_result = result.get("result", {})
            success = result.get("status") == "success"
            return {
                "success": success,
                "tool": "get_game_object_info",
                "params": {"gameobject_path": gameobject_path,
                           "include_children": include_children,
                           "include_components": include_components},
                "info": unity_result,
                "error": result.get("error") if not success else None,
                "message": (
                    f"Retrieved info for '{gameobject_path}'"
                    if success
                    else result.get("error", f"Failed to retrieve info for '{gameobject_path}'")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to get game object info: {ex}")
            return {
                "success": False,
                "tool": "get_game_object_info",
                "error": str(ex),
                "message": str(ex),
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def execute_script(
        script: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute a C# script in the Unity Editor context.

        Every script uses Unity compilation. The tool waits for compile, executes the
        generated menu action, and reads a result that survives domain reload.

        Args:
            script: C# code to execute. The code runs in Editor context with access to
                    UnityEditor and UnityEngine APIs.
            timeout: Execution timeout in seconds (default: 30).
        """
        args: dict[str, Any] = {
            "script": script,
            "timeout": timeout,
        }

        eval_id = None
        try:
            result = await send_to_unity("execute_script", args)
            output = result.get("result", {}).get("output", "")
            success = result.get("status") == "success"

            if not success:
                raise RuntimeError(result.get("error", "Script execution failed"))
            eval_match = re.search(r"\[MCP_EVAL_ID:([a-f0-9]+)\]", output)
            if not eval_match:
                raise RuntimeError("Unity did not return a verifiable script execution ID")
            if eval_match:
                eval_id = eval_match.group(1)
                deadline = time.monotonic() + timeout
                while True:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Script compilation did not complete before timeout")
                    await asyncio.sleep(.5)
                    compilation = await send_to_unity("manage_editor", {"action": "check_compile_errors"})
                    if compilation.get("status") != "success":
                        raise RuntimeError(compilation.get("error", "Cannot read compilation status"))
                    state = compilation.get("result", {})
                    if state.get("has_errors"):
                        raise RuntimeError(f"Script compilation failed: {state.get('errors', [])}")
                    if state.get("is_compiling") is False:
                        break
                menu_result = await send_to_unity("manage_editor", {"action": "execute_menu_item", "menu_path": f"Temp/MCP Eval {eval_id}"})
                if menu_result.get("status") != "success":
                    raise RuntimeError(menu_result.get("error", "Compiled script did not execute"))
                while True:
                    execution = await send_to_unity("execute_script", {"eval_id": eval_id})
                    if execution.get("status") != "success":
                        raise RuntimeError(execution.get("error", "Cannot verify script result"))
                    saved = execution.get("result", {})
                    if saved.get("state") == "failed":
                        raise RuntimeError(saved.get("error", "Script failed"))
                    if saved.get("state") == "completed":
                        output = saved.get("output", "")
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("execution_uncertain: compiled script result was not observed")
                    await asyncio.sleep(.25)

            return {
                "success": success,
                "tool": "execute_script",
                "params": {"script": script, "timeout": timeout},
                "output": output,
                "message": "Script executed in Unity Editor",
            }
        except Exception as ex:
            logger.error(f"Failed to execute script: {ex}")
            return {
                "success": False,
                "tool": "execute_script",
                "error": str(ex),
                "message": str(ex),
            }
        finally:
            if eval_id:
                try:
                    await asyncio.wait_for(send_to_unity("execute_script", {"eval_id": eval_id, "cleanup": True}), timeout=5)
                except Exception as cleanup_error:
                    logger.warning("Could not clean temporary script %s: %s", eval_id, cleanup_error)
