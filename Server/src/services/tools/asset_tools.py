"""
Asset Tools for the Unified MCP for Unity system.
Provides MCP tools for asset management operations.
Group: core

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1C.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
import math
import os
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def _parse_position(position_str: str) -> list[float]:
    """Parse comma-separated position string like '0,1,0' into [x,y,z] list."""
    if not position_str:
        return [0.0, 0.0, 0.0]
    try:
        values = [float(x.strip()) for x in position_str.split(",")]
    except (ValueError, AttributeError) as exc:
        raise ValueError("Vector must contain numeric x,y,z values") from exc
    if len(values) != 3 or not all(math.isfinite(value) for value in values):
        raise ValueError("Vector must contain exactly 3 finite x,y,z values")
    return values


def register_asset_tools(mcp: FastMCP) -> None:
    """Register Asset tools with the MCP server."""
    group = "core"

    @mcp.tool(tags=make_group_tags("core"))
    async def list_all_prefabs_with_bounding_boxes() -> dict[str, Any]:
        """Lists all Prefab assets in the project with their bounding box dimensions."""
        args: dict[str, Any] = {}

        try:
            result = await get_router().send_tool('list_all_prefabs_with_bounding_boxes', args)
            return {
                "success": result.get("status") == "success",
                "tool": "list_all_prefabs_with_bounding_boxes",
                "prefabs": result.get("result", {}).get("prefabs", []),
                "message": "Listed all prefabs with bounding boxes",
            }
        except Exception as ex:
            logger.error(f"Failed to list prefabs: {ex}")
            return {
                "success": False,
                "tool": "list_all_prefabs_with_bounding_boxes",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def place_asset_in_scene(
        asset_path: str,
        position: str = "0,0,0",
        rotation: str = "0,0,0",
        scale: str | None = None,
    ) -> dict[str, Any]:
        """Places an asset (prefab, model, etc.) into the active scene.

        Args:
            asset_path: Asset path to the prefab or model (e.g., 'Assets/Prefabs/Enemy.prefab').
            position: Comma-separated position coordinates (default: '0,0,0').
            rotation: Comma-separated rotation angles (default: '0,0,0').
            scale: Optional comma-separated scale factors.
        """
        # Extract name from asset path (last segment without extension)
        asset_name = os.path.splitext(os.path.basename(asset_path))[0]

        # Build position as dict (matching manage_gameobject format)
        try:
            pos_list = _parse_position(position)
            args: dict[str, Any] = {'name': asset_name, 'prefab_path': asset_path, 'position': {'x': pos_list[0], 'y': pos_list[1], 'z': pos_list[2]}}
            if rotation:
                rot_list = _parse_position(rotation)
                args["rotation"] = {"x": rot_list[0], "y": rot_list[1], "z": rot_list[2]}
            if scale:
                scale_list = _parse_position(scale)
                args["size"] = {"x": scale_list[0], "y": scale_list[1], "z": scale_list[2]}
        except ValueError as ex:
            return {"success": False, "tool": "place_asset_in_scene", "error": str(ex)}

        try:
            result = await get_router().send_tool('place_asset_in_scene', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "place_asset_in_scene",
                "params": {"asset_path": asset_path, "position": position,
                           "rotation": rotation, "scale": scale},
                "instance_id": unity_result.get("instanceId"),
                "message": f"Placed asset '{asset_path}' in scene at {position}",
            }
        except Exception as ex:
            logger.error(f"Failed to place asset in scene: {ex}")
            return {
                "success": False,
                "tool": "place_asset_in_scene",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
