"""
Scripting Tools for the Unified MCP for Unity system.
Provides MCP tools for script, ScriptableObject, menu, and refresh operations.
Group: scripting_ext

Migrated from unity-mcp-beta's ManageScript, ManageScriptableObject, ExecuteMenuItem, RefreshUnity.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_scripting_tools(mcp: FastMCP) -> None:
    """Register Scripting tools with the MCP server."""
    group = "scripting_ext"

    @mcp.tool(tags=make_group_tags("scripting_ext"))
    async def manage_script(
        action: str,
        script_path: str | None = None,
        content: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity C# script assets.

        Actions:
        - create: Create a new C# script file
        - read: Read script content
        - update: Update script content

        Args:
            action: The action to perform (create/read/update).
            script_path: Asset path for the script (e.g., 'Assets/Scripts/PlayerController.cs').
            content: Script content (for create/update).
            properties: JSON object with additional properties.
        """
        import json as json_module
        args: dict[str, Any] = {"action": action, "folder": "Assets"}
        if script_path:
            # Extract folder and name from path
            parts = script_path.rsplit("/", 1)
            if len(parts) == 2:
                args["folder"] = parts[0]
                args["name"] = parts[1].replace(".cs", "")
            else:
                args["name"] = script_path.replace(".cs", "")
        if content is not None:
            args["content"] = content
        if properties:
            try:
                props = json_module.loads(properties) if isinstance(properties, str) else properties
                args.update(props)
            except Exception:
                pass

        try:
            result = await get_router().send_tool('manage_script', args)
            return {
                "success": result.get("status") == "success",
                "tool": "manage_script",
                "params": {"action": action, "script_path": script_path},
                "message": f"Script {action} completed" if result.get("status") == "success" else result.get("error", "Script operation failed"),
                "result": result.get("result"),
                "error": result.get("error"),
            }
        except Exception as ex:
            logger.error(f"Failed to manage script: {ex}")
            return {
                "success": False,
                "tool": "manage_script",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("scripting_ext"))
    async def manage_scriptable_object(
        action: str,
        asset_path: str | None = None,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Manage Unity ScriptableObject assets.

        Actions:
        - create: Create a new ScriptableObject asset
        - get: Read ScriptableObject data
        - set_property: Set a property value

        Args:
            action: The action to perform (create/get/set_property).
            asset_path: Asset path (e.g., 'Assets/Data/Config.asset').
            properties: JSON object with action-specific properties.
        """
        import json as json_module
        args: dict[str, Any] = {"action": action}
        if asset_path:
            if action == "create":
                args["save_path"] = asset_path
            else:
                args["asset_path"] = asset_path
        if properties:
            try:
                props = json_module.loads(properties) if isinstance(properties, str) else properties
                args.update(props)
            except Exception:
                pass

        try:
            result = await get_router().send_tool('manage_scriptable_object', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "manage_scriptable_object",
                "params": {"action": action, "asset_path": asset_path},
                "result": unity_result,
                "message": f"ScriptableObject {action} completed",
            }
        except Exception as ex:
            logger.error(f"Failed to manage scriptable object: {ex}")
            return {
                "success": False,
                "tool": "manage_scriptable_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }


    @mcp.tool(tags=make_group_tags("scripting_ext"))
    async def execute_menu_item(
        menu_path: str,
    ) -> dict[str, Any]:
        """Execute a Unity Editor menu item by its path.

        Args:
            menu_path: Full menu path (e.g., 'File/Save Project', 'GameObject/Create Empty').
        """
        try:
            result = await get_router().send_tool('execute_menu_item', {'menu_path': menu_path})
            return {
                "success": result.get("status") == "success",
                "tool": "execute_menu_item",
                "params": {"menu_path": menu_path},
                "result": result.get("result", {}),
                "message": f"Menu item executed: {menu_path}",
            }
        except Exception as ex:
            logger.error(f"Failed to execute menu item '{menu_path}': {ex}")
            return {
                "success": False,
                "tool": "execute_menu_item",
                "params": {"menu_path": menu_path},
                "error": str(ex),
            }

    @mcp.tool(tags=make_group_tags("scripting_ext"))
    async def refresh_unity(
        force: bool = False,
    ) -> dict[str, Any]:
        """Refresh the Unity Asset Database to detect file changes.

        Args:
            force: Whether to force a full reimport (default: false).
        """
        args = {'force': force}

        try:
            result = await get_router().send_tool('refresh_unity', args)
            return {
                "success": result.get("status") == "success",
                "tool": "refresh_unity",
                "params": {"force": force},
                "state": result.get("result", {}).get("state", "submitted") if result.get("status") == "success" else "failed",
                "result": result.get("result", {}),
                "error": result.get("error"),
                "message": "Refresh request processed",
            }
        except Exception as ex:
            logger.error(f"Failed to refresh Unity: {ex}")
            return {
                "success": False,
                "tool": "refresh_unity",
                "error": str(ex),
                "message": f"Failed to refresh Unity: {ex}",
            }
