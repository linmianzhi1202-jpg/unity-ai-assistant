"""
Screenshot Tools for the Unified MCP for Unity system.
Provides MCP tools for capturing scene and UI screenshots.
Group: core

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1C.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_screenshot_tools(mcp: FastMCP) -> None:
    """Register Screenshot tools with the MCP server."""
    group = "core"

    @mcp.tool(tags=make_group_tags("core"))
    async def capture_scene_object(
        gameobject_path: str | None = None,
        width: int = 512,
        height: int = 512,
        format: str = "PNG",
    ) -> dict[str, Any]:
        """Captures a screenshot of the Scene view, optionally framing a specific GameObject.

        Args:
            gameobject_path: Optional path to a GameObject to frame in the screenshot.
            width: Screenshot width in pixels (default: 512).
            height: Screenshot height in pixels (default: 512).
            format: Image format ('PNG' or 'JPG').
        """
        args: dict[str, Any] = {'width': width, 'height': height, 'format': format}
        if gameobject_path:
            args["gameobject_path"] = gameobject_path

        try:
            result = await get_router().send_tool('capture_scene_object', args)
            success = result.get("status") == "success"
            unity_result = result.get("result", {}) if success else {}
            return {
                "success": success,
                "tool": "capture_scene_object",
                "params": {"gameobject_path": gameobject_path, "width": width,
                           "height": height, "format": format},
                "path": unity_result.get("path"),
                "width": unity_result.get("width"),
                "height": unity_result.get("height"),
                "format": unity_result.get("format"),
                "framed_object": unity_result.get("framed_object"),
                "file_exists": unity_result.get("file_exists", False),
                "file_size": unity_result.get("file_size", 0),
                "error": result.get("error") if not success else None,
                "message": (
                    unity_result.get("message", f"Captured scene screenshot ({width}x{height})")
                    if success
                    else result.get("error", "Unity failed to capture the scene screenshot")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to capture scene screenshot: {ex}")
            return {
                "success": False,
                "tool": "capture_scene_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def capture_ui_canvas(
        canvas_path: str | None = None,
        width: int = 1920,
        height: int = 1080,
        format: str = "PNG",
    ) -> dict[str, Any]:
        """Captures a screenshot of a UI Canvas.

        Args:
            canvas_path: Optional path to a specific Canvas. Defaults to the first Canvas found.
            width: Screenshot width in pixels (default: 1920).
            height: Screenshot height in pixels (default: 1080).
            format: Image format ('PNG' or 'JPG').
        """
        args: dict[str, Any] = {'width': width, 'height': height, 'format': format}
        if canvas_path:
            args["canvas_path"] = canvas_path

        try:
            result = await get_router().send_tool('capture_ui_canvas', args)
            success = result.get("status") == "success"
            unity_result = result.get("result", {}) if success else {}
            return {
                "success": success,
                "tool": "capture_ui_canvas",
                "params": {"canvas_path": canvas_path, "width": width,
                           "height": height, "format": format},
                "path": unity_result.get("path"),
                "width": unity_result.get("width"),
                "height": unity_result.get("height"),
                "format": unity_result.get("format"),
                "framed_object": unity_result.get("framed_object"),
                "file_exists": unity_result.get("file_exists", False),
                "file_size": unity_result.get("file_size", 0),
                "error": result.get("error") if not success else None,
                "message": (
                    unity_result.get("message", f"Captured UI screenshot ({width}x{height})")
                    if success
                    else result.get("error", "Unity failed to capture the UI screenshot")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to capture UI canvas screenshot: {ex}")
            return {
                "success": False,
                "tool": "capture_ui_canvas",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
