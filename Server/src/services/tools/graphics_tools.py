"""
Graphics Tools for the Unified MCP for Unity system.
Provides MCP tools for shader, texture, VFX, and camera operations.
Group: vfx

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1B.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
import json
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def _parse_properties(properties: str | None) -> dict[str, Any]:
    """Parse and validate an optional JSON properties string into a dict."""
    if not properties:
        return {}
    try:
        values = json.loads(properties)
    except json.JSONDecodeError as exc:
        raise ValueError(f"properties 必须是合法 JSON: {exc}") from exc
    if not isinstance(values, dict):
        raise ValueError("properties 必须是 JSON 对象")
    return values


def register_graphics_tools(mcp: FastMCP) -> None:
    """Register Graphics tools with the MCP server."""
    group = "vfx"

    @mcp.tool(tags=make_group_tags("vfx"))
    async def manage_shader(
        action: str,
        shader_path: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity shader assets.

        Actions:
        - get: Read shader properties and info
        - set_property: Set a shader property on a material

        Args:
            action: The action to perform (get/set_property).
            shader_path: Asset path to the shader (e.g., 'Assets/Shaders/MyShader.shader').
            properties: JSON object with action-specific properties.
        """
        args: dict[str, Any] = {"action": action}
        if shader_path:
            args["shader_path"] = shader_path
        if properties:
            try:
                values = _parse_properties(properties)
                if any(key in args for key in values):
                    raise ValueError("properties 不能覆盖 action 或目标路径")
                args.update(values)
            except ValueError as ex:
                return {"success": False, "tool": "manage_shader", "error": str(ex)}

        try:
            result = await get_router().send_tool('manage_shader', args)
            return {
                "success": result.get("status") == "success",
                "tool": "manage_shader",
                "params": {"action": action, "shader_path": shader_path, "properties": properties},
                "message": f"Shader {action} completed" if result.get("status") == "success" else result.get("error"),
                "data": result.get("result"), "error": result.get("error"),
            }
        except Exception as ex:
            logger.error(f"Failed to manage shader: {ex}")
            return {
                "success": False,
                "tool": "manage_shader",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("vfx"))
    async def manage_texture(
        action: str,
        texture_path: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity texture assets (import settings, format, size).

        Actions:
        - get: Read texture import settings
        - set_property: Modify texture import settings

        Args:
            action: The action to perform (get/set_property).
            texture_path: Asset path to the texture.
            properties: JSON object with action-specific properties.
        """
        args: dict[str, Any] = {"action": action}
        if texture_path:
            args["texture_path"] = texture_path
        if properties:
            try:
                values = _parse_properties(properties)
                if any(key in args for key in values):
                    raise ValueError("properties 不能覆盖 action 或目标路径")
                args.update(values)
            except ValueError as ex:
                return {"success": False, "tool": "manage_texture", "error": str(ex)}

        try:
            result = await get_router().send_tool('manage_texture', args)
            return {
                "success": result.get("status") == "success",
                "tool": "manage_texture",
                "params": {"action": action, "texture_path": texture_path, "properties": properties},
                "message": f"Texture {action} completed" if result.get("status") == "success" else result.get("error"),
                "data": result.get("result"), "error": result.get("error"),
            }
        except Exception as ex:
            logger.error(f"Failed to manage texture: {ex}")
            return {
                "success": False,
                "tool": "manage_texture",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("vfx"))
    async def manage_vfx(
        action: str,
        vfx_path: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity Visual Effect Graph assets.

        Actions:
        - get: Read VFX properties
        - set_property: Set VFX property values

        Args:
            action: The action to perform (get/set_property).
            vfx_path: Asset path to the VFX asset (e.g., 'Assets/VFX/Explosion.vfx').
            properties: JSON object with action-specific properties.
        """
        args: dict[str, Any] = {"action": action}
        if vfx_path:
            args["vfx_path"] = vfx_path
        if properties:
            try:
                values = _parse_properties(properties)
                if any(key in args for key in values):
                    raise ValueError("properties 不能覆盖 action 或目标路径")
                args.update(values)
            except ValueError as ex:
                return {"success": False, "tool": "manage_vfx", "error": str(ex)}

        try:
            result = await get_router().send_tool('manage_vfx', args)
            return {
                "success": result.get("status") == "success",
                "tool": "manage_vfx",
                "params": {"action": action, "vfx_path": vfx_path, "properties": properties},
                "message": f"VFX {action} completed" if result.get("status") == "success" else result.get("error"),
                "data": result.get("result"), "error": result.get("error"),
            }
        except Exception as ex:
            logger.error(f"Failed to manage VFX: {ex}")
            return {
                "success": False,
                "tool": "manage_vfx",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("vfx"))
    async def manage_camera(
        action: str,
        camera_path: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity Camera components.

        Actions:
        - get: Read camera properties
        - set_property: Set camera property values
        - set_clear_flags: Set camera clear flags
        - set_background_color: Set camera background color

        Args:
            action: The action to perform.
            camera_path: Path to the camera GameObject.
            properties: JSON object with action-specific properties.
        """
        args: dict[str, Any] = {"action": action}
        if camera_path:
            args["camera_path"] = camera_path
        if properties:
            try:
                values = _parse_properties(properties)
                if any(key in args for key in values):
                    raise ValueError("properties 不能覆盖 action 或目标路径")
                args.update(values)
            except ValueError as ex:
                return {"success": False, "tool": "manage_camera", "error": str(ex)}

        try:
            result = await get_router().send_tool('manage_camera', args)
            return {
                "success": result.get("status") == "success",
                "tool": "manage_camera",
                "params": {"action": action, "camera_path": camera_path, "properties": properties},
                "message": f"Camera {action} completed" if result.get("status") == "success" else result.get("error"),
                "data": result.get("result"), "error": result.get("error"),
            }
        except Exception as ex:
            logger.error(f"Failed to manage camera: {ex}")
            return {
                "success": False,
                "tool": "manage_camera",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
