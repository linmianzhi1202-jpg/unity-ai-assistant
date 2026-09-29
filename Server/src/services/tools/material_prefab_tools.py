"""
Material & Prefab Tools for the Unified MCP for Unity system.
Provides MCP tools for material, shader, prefab, and asset operations.
Group: core

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1B.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_material_prefab_tools(mcp: FastMCP) -> None:
    """Register Material & Prefab tools with the MCP server."""
    group = "core"

    # ── Material ─────────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def create_material(
        material_name: str,
        color: str = "1,1,1,1",
        material_path: str = "Assets/Materials/",
        texture_path: str | None = None,
    ) -> dict[str, Any]:
        """Creates a new material asset.

        Args:
            material_name: Name of the new material.
            color: Comma-separated RGBA color components (0-1 range, e.g., 'r,g,b,a').
            material_path: Folder path where the material should be created.
            texture_path: Optional path to a texture to apply to the material.
        """
        args: dict[str, Any] = {'name': material_name, 'color': color, 'save_path': material_path}
        if texture_path:
            args["texture_path"] = texture_path

        try:
            result = await get_router().send_tool('create_material', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_material",
                "params": {"material_name": material_name, "color": color,
                           "material_path": material_path, "texture_path": texture_path},
                "message": f"Created material '{material_name}' at '{material_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create material: {ex}")
            return {
                "success": False,
                "tool": "create_material",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def assign_material(
        gameobject_path: str,
        material_path: str,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Assigns a material to a GameObject or Prefab sub-object.

        Args:
            gameobject_path: Path to the GameObject in the scene or prefab.
            material_path: Asset path to the material (e.g., Assets/Materials/MyMat.mat).
            prefab_path: Optional prefab asset path for prefab modifications.
        """
        args: dict[str, Any] = {'path': gameobject_path, 'material_path': material_path}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('assign_material', args)
            return {
                "success": result.get("status") == "success",
                "tool": "assign_material",
                "params": {"gameobject_path": gameobject_path, "material_path": material_path,
                           "prefab_path": prefab_path},
                "message": f"Assigned material '{material_path}' to '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to assign material: {ex}")
            return {
                "success": False,
                "tool": "assign_material",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def assign_material_to_fbx(
        fbx_path: str,
        material_path: str,
        sub_mesh_name: str | None = None,
    ) -> dict[str, Any]:
        """Assigns a material to an FBX model without placing it in the scene.

        Args:
            fbx_path: Asset path to the FBX model (e.g., Assets/Models/Character.fbx).
            material_path: Asset path to the material.
            sub_mesh_name: Optional sub-mesh name for multi-material FBX.
        """
        args: dict[str, Any] = {'path': fbx_path, 'material_path': material_path, 'is_fbx': True}
        if sub_mesh_name:
            args["sub_mesh_name"] = sub_mesh_name

        try:
            result = await get_router().send_tool('assign_material_to_fbx', args)
            return {
                "success": result.get("status") == "success",
                "tool": "assign_material_to_fbx",
                "params": {"fbx_path": fbx_path, "material_path": material_path,
                           "sub_mesh_name": sub_mesh_name},
                "message": f"Assigned material '{material_path}' to FBX '{fbx_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to assign material to FBX: {ex}")
            return {
                "success": False,
                "tool": "assign_material_to_fbx",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def assign_shader_to_material(
        material_path: str,
        shader_name: str,
    ) -> dict[str, Any]:
        """Assigns a shader to a material.

        Args:
            material_path: Asset path to the material.
            shader_name: Name of the shader (e.g., 'Standard', 'Unlit/Texture',
                         'Universal Render Pipeline/Lit').
        """
        args: dict[str, Any] = {'material_path': material_path, 'property_name': '_shader_name', 'shader_name_value': shader_name}

        try:
            result = await get_router().send_tool('assign_shader_to_material', args)
            return {
                "success": result.get("status") == "success",
                "tool": "assign_shader_to_material",
                "params": {"material_path": material_path, "shader_name": shader_name},
                "message": f"Assigned shader '{shader_name}' to material '{material_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to assign shader to material: {ex}")
            return {
                "success": False,
                "tool": "assign_shader_to_material",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Prefab ───────────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def create_prefab(
        gameobject_path: str,
        prefab_path: str,
    ) -> dict[str, Any]:
        """Creates a Prefab from a scene GameObject.

        Args:
            gameobject_path: Path to the source GameObject in the scene.
            prefab_path: Asset path for the new prefab (e.g., Assets/Prefabs/MyPrefab.prefab).
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path, 'prefab_path': prefab_path}

        try:
            result = await get_router().send_tool('create_prefab', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_prefab",
                "params": {"gameobject_path": gameobject_path, "prefab_path": prefab_path},
                "message": f"Created prefab '{prefab_path}' from '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create prefab: {ex}")
            return {
                "success": False,
                "tool": "create_prefab",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def create_prefab_variant(
        base_prefab_path: str,
        variant_path: str,
    ) -> dict[str, Any]:
        """Creates a Prefab Variant from an existing prefab.

        Args:
            base_prefab_path: Asset path to the base prefab.
            variant_path: Asset path for the new prefab variant.
        """
        args: dict[str, Any] = {'base_prefab_path': base_prefab_path, 'variant_path': variant_path}

        try:
            result = await get_router().send_tool('create_prefab_variant', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_prefab_variant",
                "params": {"base_prefab_path": base_prefab_path, "variant_path": variant_path},
                "message": f"Created prefab variant '{variant_path}' from '{base_prefab_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create prefab variant: {ex}")
            return {
                "success": False,
                "tool": "create_prefab_variant",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def add_nested_object_to_prefab(
        prefab_path: str,
        object_name: str,
        object_type: str = "Empty",
        parent_path: str | None = None,
    ) -> dict[str, Any]:
        """Adds a nested object to a Prefab asset.

        Args:
            prefab_path: Asset path to the prefab.
            object_name: Name for the new nested object.
            object_type: Type of object to add ('Empty', 'Cube', 'Sphere', etc.).
            parent_path: Optional path within the prefab hierarchy to parent under.
        """
        args: dict[str, Any] = {'prefab_path': prefab_path, 'object_name': object_name, 'object_type': object_type}
        if parent_path:
            args["parent_path"] = parent_path

        try:
            result = await get_router().send_tool('add_nested_object_to_prefab', args)
            return {
                "success": result.get("status") == "success",
                "tool": "add_nested_object_to_prefab",
                "params": {"prefab_path": prefab_path, "object_name": object_name,
                           "object_type": object_type, "parent_path": parent_path},
                "message": f"Added nested '{object_name}' ({object_type}) to prefab '{prefab_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to add nested object to prefab: {ex}")
            return {
                "success": False,
                "tool": "add_nested_object_to_prefab",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Asset Operations ─────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def duplicate_asset(
        source_path: str,
        destination_path: str,
    ) -> dict[str, Any]:
        """Duplicates a project asset.

        Args:
            source_path: Asset path of the source asset.
            destination_path: Asset path for the duplicate.
        """
        args: dict[str, Any] = {'source_path': source_path, 'destination_path': destination_path}

        try:
            result = await get_router().send_tool('duplicate_asset', args)
            return {
                "success": result.get("status") == "success",
                "tool": "duplicate_asset",
                "params": {"source_path": source_path, "destination_path": destination_path},
                "message": f"Duplicated '{source_path}' to '{destination_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to duplicate asset: {ex}")
            return {
                "success": False,
                "tool": "duplicate_asset",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def rename_asset(
        asset_path: str,
        new_name: str,
    ) -> dict[str, Any]:
        """Renames a project asset.

        Args:
            asset_path: Asset path of the asset to rename.
            new_name: The new name (without extension).
        """
        args: dict[str, Any] = {'asset_path': asset_path, 'new_name': new_name}

        try:
            result = await get_router().send_tool('rename_asset', args)
            return {
                "success": result.get("status") == "success",
                "tool": "rename_asset",
                "params": {"asset_path": asset_path, "new_name": new_name},
                "message": f"Renamed '{asset_path}' to '{new_name}'",
            }
        except Exception as ex:
            logger.error(f"Failed to rename asset: {ex}")
            return {
                "success": False,
                "tool": "rename_asset",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
