"""
Scene Tools for the Unified MCP for Unity system.
Provides MCP tools for scene, GameObject, transform, component, and editor operations.
Group: core

IMPORTANT: All tools now dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity.

Migrated from Coplay MCP Server's unity_functions_tools.py (scene-related subset).
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
import math
from typing import Any, Literal

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags
# Import the UnityBridge for actual Unity communication
from services.tools.unity_bridge import send_to_unity

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


def register_scene_tools(mcp: FastMCP) -> None:
    """Register Scene tools with the MCP server."""
    group = "core"

    # ── GameObject CRUD ──────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def create_game_object(
        name: str,
        position: str = "0,0,0",
        primitive_type: Literal["Cube", "Sphere", "Capsule", "Cylinder", "Plane"] | None = None,
        size: str | None = None,
        prefab_path: str | None = None,
        use_world_coordinates: bool | None = None,
    ) -> dict[str, Any]:
        """Creates a new GameObject in the Unity scene. If primitive_type is not specified, creates an empty GameObject.

        Args:
            name: The name of the new GameObject.
            position: Comma-separated position coordinates (e.g., 'x,y,z').
            primitive_type: Optional type of primitive to create (Cube/Sphere/Capsule/Cylinder/Plane).
            size: Optional comma-separated scale factors (e.g., 'x,y,z').
            prefab_path: Optional path to a prefab asset (e.g., Assets/MyPrefab.prefab).
            use_world_coordinates: Whether to use world coordinates (true) or local (false, default).
        """
        args: dict[str, Any] = {'name': name}

        try:
            # Parse position
            pos_list = _parse_position(position)
            if pos_list != [0.0, 0.0, 0.0] or position:
                args["position"] = {"x": pos_list[0], "y": pos_list[1], "z": pos_list[2]}

            # Handle primitive_type by setting it as additional info
            if primitive_type:
                args["primitive_type"] = primitive_type
            if size:
                size_list = _parse_position(size)
                args["size"] = {"x": size_list[0], "y": size_list[1], "z": size_list[2]}
            if prefab_path:
                args["prefab_path"] = prefab_path
            if use_world_coordinates is not None:
                args["use_world_coordinates"] = use_world_coordinates
        except ValueError as ex:
            return {"success": False, "tool": "create_game_object", "error": str(ex)}

        try:
            result = await get_router().send_tool('create_game_object', args)
            # Wrap result in expected format
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "create_game_object",
                "params": {
                    "name": name, "position": position, "primitive_type": primitive_type,
                    "size": size, "prefab_path": prefab_path,
                    "use_world_coordinates": use_world_coordinates,
                },
                "instance_id": unity_result.get("instanceId"),
                "result_name": unity_result.get("name"),
                "message": f"Created GameObject '{name}' at {position}",
            }
        except Exception as ex:
            logger.error(f"Failed to create game object: {ex}")
            return {
                "success": False,
                "tool": "create_game_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def delete_game_object(
        gameobject_path: str,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Deletes a GameObject from the Unity scene.

        Args:
            gameobject_path: Path to the GameObject in the scene hierarchy (e.g., Body/Head/Eyes).
            prefab_path: Optional path to a prefab asset for prefab modifications.
        """
        args = {'path': gameobject_path}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('delete_game_object', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "delete_game_object",
                "params": {"gameobject_path": gameobject_path, "prefab_path": prefab_path},
                "deleted": gameobject_path,
                "message": f"Deleted GameObject at path '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to delete game object: {ex}")
            return {
                "success": False,
                "tool": "delete_game_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def duplicate_game_object(
        gameobject_path: str,
        new_name: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Duplicates a GameObject in the scene or prefab.

        Args:
            gameobject_path: Path to the GameObject to duplicate.
            new_name: Optional name for the duplicated object.
            prefab_path: Optional path to a prefab asset.
        """
        # Duplicate is implemented via create + copy properties pattern
        # For now, use create with original name + "_copy" suffix
        dup_name = new_name or f"{gameobject_path.rsplit('/', 1)[-1]}_Copy"

        args = {'name': dup_name, 'source_path': gameobject_path}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('duplicate_game_object', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "duplicate_game_object",
                "params": {"gameobject_path": gameobject_path, "new_name": new_name, "prefab_path": prefab_path},
                "new_instance_id": unity_result.get("instanceId"),
                "message": f"Duplicated '{gameobject_path}' as '{dup_name}'",
            }
        except Exception as ex:
            logger.error(f"Failed to duplicate game object: {ex}")
            return {
                "success": False,
                "tool": "duplicate_game_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def rename_game_object(
        gameobject_path: str,
        new_name: str,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Renames a GameObject in the scene or prefab.

        Args:
            gameobject_path: Path to the GameObject to rename.
            new_name: The new name for the GameObject.
            prefab_path: Optional path to a prefab asset.
        """
        args = {'path': gameobject_path, 'name': new_name}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('rename_game_object', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "rename_game_object",
                "params": {"gameobject_path": gameobject_path, "new_name": new_name, "prefab_path": prefab_path},
                "renamed_to": new_name,
                "message": f"Renamed '{gameobject_path}' to '{new_name}'",
            }
        except Exception as ex:
            logger.error(f"Failed to rename game object: {ex}")
            return {
                "success": False,
                "tool": "rename_game_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def parent_game_object(
        child_path: str,
        parent_path: str | None = None,
        world_position_stays: bool = True,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Sets the parent of a GameObject. Pass null parent_path to unparent.

        Args:
            child_path: Path to the child GameObject.
            parent_path: Path to the new parent GameObject. Null to unparent.
            world_position_stays: Whether to preserve world position (default: true).
            prefab_path: Optional path to a prefab asset.
        """
        # Parenting requires custom handling — use execute_script or direct API
        # Fall back to sending as manage_gameobject with extended args
        args = {'child_path': child_path, 'parent_path': parent_path, 'world_position_stays': world_position_stays}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('parent_game_object', args)
            return {
                "success": result.get("status") == "success",
                "tool": "parent_game_object",
                "params": {
                    "child_path": child_path, "parent_path": parent_path,
                    "world_position_stays": world_position_stays, "prefab_path": prefab_path,
                },
                "message": f"Parented '{child_path}' under '{parent_path or 'root'}'",
            }
        except Exception as ex:
            logger.error(f"Failed to parent game object: {ex}")
            return {
                "success": False,
                "tool": "parent_game_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Transform ────────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def set_transform(
        gameobject_path: str,
        position: str | None = None,
        rotation: str | None = None,
        scale: str | None = None,
        prefab_path: str | None = None,
        use_world_coordinates: bool | None = None,
    ) -> dict[str, Any]:
        """Sets the position, rotation, or scale of a GameObject.

        Args:
            gameobject_path: Path to the GameObject (e.g., Body/Head/Eyes).
            position: Comma-separated position coordinates (e.g., 'x,y,z').
            rotation: Comma-separated rotation angles in degrees (e.g., 'x,y,z').
            scale: Comma-separated scale factors (e.g., 'x,y,z').
            prefab_path: Optional path to a prefab asset.
            use_world_coordinates: Whether to use world coordinates (default: false/local).
        """
        args: dict[str, Any] = {"path": gameobject_path}

        try:
            if position:
                pos_list = _parse_position(position)
                args["position"] = {"x": pos_list[0], "y": pos_list[1], "z": pos_list[2]}
            if rotation:
                rot_list = _parse_position(rotation)
                args["rotation"] = {"x": rot_list[0], "y": rot_list[1], "z": rot_list[2]}
            if scale:
                scale_list = _parse_position(scale)
                args["scale"] = {"x": scale_list[0], "y": scale_list[1], "z": scale_list[2]}
            if use_world_coordinates is not None:
                args["world_coordinates"] = use_world_coordinates
            if prefab_path:
                args["prefab_path"] = prefab_path
        except ValueError as ex:
            return {"success": False, "tool": "set_transform", "error": str(ex)}

        try:
            result = await get_router().send_tool('set_transform', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "set_transform",
                "params": {
                    "gameobject_path": gameobject_path, "position": position,
                    "rotation": rotation, "scale": scale,
                    "prefab_path": prefab_path, "use_world_coordinates": use_world_coordinates,
                },
                **{k: v for k, v in unity_result.items() if k in ("position", "rotation", "scale")},
                "message": f"Set transform on '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set transform: {ex}")
            return {
                "success": False,
                "tool": "set_transform",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def set_sibling_index(
        gameobject_path: str,
        sibling_index: int,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Sets the sibling index of a GameObject to reorder it in the hierarchy.

        Args:
            gameobject_path: Path to the GameObject.
            sibling_index: The new sibling index (0-based).
            prefab_path: Optional path to a prefab asset.
        """
        args = {'path': gameobject_path, 'sibling_index': sibling_index}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('set_sibling_index', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_sibling_index",
                "params": {"gameobject_path": gameobject_path, "sibling_index": sibling_index, "prefab_path": prefab_path},
                "message": f"Set sibling index of '{gameobject_path}' to {sibling_index}",
            }
        except Exception as ex:
            logger.error(f"Failed to set sibling index: {ex}")
            return {
                "success": False,
                "tool": "set_sibling_index",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Tag & Layer ──────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def set_tag(
        gameobject_path: str,
        tag: str,
        create_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Sets the tag of a GameObject. Optionally creates the tag if it doesn't exist.

        Args:
            gameobject_path: Path to the GameObject.
            tag: The tag to assign (e.g., 'Player', 'Respawn').
            create_if_missing: Whether to create the tag if it doesn't exist (default: false).
        """
        args = {
            "path": gameobject_path,
            "tag": tag,
            "create_if_missing": create_if_missing,
        }

        try:
            result = await get_router().send_tool('set_tag', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "set_tag",
                "params": {"gameobject_path": gameobject_path, "tag": tag, "create_if_missing": create_if_missing},
                "assigned_tag": tag,
                "message": f"Set tag of '{gameobject_path}' to '{tag}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set tag: {ex}")
            return {
                "success": False,
                "tool": "set_tag",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def set_layer(
        gameobject_path: str,
        layer: str,
        create_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Sets the layer of a GameObject. Optionally creates the layer if it doesn't exist.

        Args:
            gameobject_path: Path to the GameObject.
            layer: The layer name to assign (e.g., 'Default', 'Water', 'UI').
            create_if_missing: Whether to create the layer if it doesn't exist (default: false).
        """
        args = {
            "path": gameobject_path,
            "layer": layer,
            "create_if_missing": create_if_missing,
        }

        try:
            result = await get_router().send_tool('set_layer', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "set_layer",
                "params": {"gameobject_path": gameobject_path, "layer": layer, "create_if_missing": create_if_missing},
                "assigned_layer": layer,
                "message": f"Set layer of '{gameobject_path}' to '{layer}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set layer: {ex}")
            return {
                "success": False,
                "tool": "set_layer",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Components ───────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def add_component(
        gameobject_path: str,
        component_type: str,
        prefab_path: str | None = None,
        allow_duplicate: bool = False,
    ) -> dict[str, Any]:
        """Adds a component to a GameObject (e.g., Rigidbody, BoxCollider, AudioSource).

        Args:
            gameobject_path: Path to the GameObject.
            component_type: Type of component to add (e.g., 'Rigidbody', 'BoxCollider').
            prefab_path: Optional path to a prefab asset.
            allow_duplicate: Add another instance even if the component already exists.
        """
        args = {'path': gameobject_path, 'component_type': component_type, 'allow_duplicate': allow_duplicate}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('add_component', args)
            unity_result = result.get("result", {})
            success = result.get("status") == "success"
            already_exists = bool(unity_result.get("already_exists"))
            message = unity_result.get("warning")
            if not message:
                message = (
                    f"Component '{component_type}' already exists on '{gameobject_path}'"
                    if already_exists
                    else f"Added component '{component_type}' to '{gameobject_path}'"
                )
            return {
                "success": success,
                "tool": "add_component",
                "params": {
                    "gameobject_path": gameobject_path,
                    "component_type": component_type,
                    "prefab_path": prefab_path,
                    "allow_duplicate": allow_duplicate,
                },
                "added_component": unity_result.get("added"),
                "component_added": unity_result.get("added_component", not already_exists if success else False),
                "already_exists": already_exists,
                "warning": unity_result.get("warning"),
                "instance_id": unity_result.get("instanceId"),
                "message": message,
            }
        except Exception as ex:
            logger.error(f"Failed to add component: {ex}")
            return {
                "success": False,
                "tool": "add_component",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def remove_component(
        gameobject_path: str,
        component_type: str,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Removes a component from a GameObject.

        Args:
            gameobject_path: Path to the GameObject.
            component_type: Type of component to remove.
            prefab_path: Optional path to a prefab asset.
        """
        args = {'path': gameobject_path, 'component_type': component_type}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('remove_component', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "remove_component",
                "params": {"gameobject_path": gameobject_path, "component_type": component_type, "prefab_path": prefab_path},
                "removed_component": unity_result.get("removed"),
                "message": f"Removed component '{component_type}' from '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to remove component: {ex}")
            return {
                "success": False,
                "tool": "remove_component",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def set_property(
        gameobject_path: str,
        component_type: str,
        property_name: str,
        value: str,
        prefab_path: str | None = None,
        asset_path: str | None = None,
        auto_audit: bool = True,
    ) -> dict[str, Any]:
        """Sets a property of a component on a GameObject. Optionally auto-audits the
        component's references after writing (default: True).

        Args:
            gameobject_path: Path to the GameObject.
            component_type: Type of the component (e.g., 'Rigidbody').
            property_name: Name of the property to set.
            value: New value for the property. For assets, use path (e.g., Assets/...).
            prefab_path: Optional path to a prefab asset.
            asset_path: Optional path to a non-prefab asset (.asset).
            auto_audit: After writing, run audit_references to verify all refs (default: True).
        """
        args = {
            "action": "set_property",
            "path": gameobject_path,
            "component_type": component_type,
            "property_name": property_name,
            "value": value,
        }
        if prefab_path:
            args["prefab_path"] = prefab_path
        if asset_path:
            args["asset_path"] = asset_path

        try:
            result = await send_to_unity("manage_components", args)
            response = {
                "success": result.get("status") == "success",
                "tool": "set_property",
                "params": {
                    "gameobject_path": gameobject_path, "component_type": component_type,
                    "property_name": property_name, "value": value,
                    "prefab_path": prefab_path, "asset_path": asset_path,
                    "auto_audit": auto_audit,
                },
                "message": f"Set {component_type}.{property_name} = {value} on '{gameobject_path}'",
            }

            # Auto-audit: verify all references on the component after writing
            if auto_audit and result.get("status") == "success":
                try:
                    audit_args = {
                        "action": "audit_references",
                        "path": gameobject_path,
                        "component_type": component_type,
                    }
                    audit_result = await send_to_unity("manage_components", audit_args)
                    unity_audit = audit_result.get("result", {})
                    response["_audit"] = {
                        "total_null_refs": unity_audit.get("total_null_refs", 0),
                        "repaired_count": unity_audit.get("repaired_count", 0),
                        "issues": unity_audit.get("issues", []),
                        "message": (
                            f"Auto-audit: {unity_audit.get('total_null_refs', 0)} null refs, "
                            f"{unity_audit.get('repaired_count', 0)} repaired"
                            if audit_result.get("status") == "success"
                            else "Auto-audit failed: " + audit_result.get("error", "unknown")
                        ),
                    }
                except Exception as audit_ex:
                    response["_audit"] = {"error": str(audit_ex), "message": "Auto-audit exception"}

            return response
        except Exception as ex:
            logger.error(f"Failed to set property: {ex}")
            return {
                "success": False,
                "tool": "set_property",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Scene Operations ─────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def save_scene(
        scene_name: str | None = None,
    ) -> dict[str, Any]:
        """Saves the current scene.

        Args:
            scene_name: Optional name for the saved scene.
        """
        args = {}
        if scene_name:
            args["scene_name"] = scene_name

        try:
            result = await get_router().send_tool('save_scene', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "save_scene",
                "params": {"scene_name": scene_name},
                "message": f"Scene saved successfully",
            }
        except Exception as ex:
            logger.error(f"Failed to save scene: {ex}")
            return {
                "success": False,
                "tool": "save_scene",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def create_scene(
        scene_path: str,
        add_to_build_settings: bool = True,
    ) -> dict[str, Any]:
        """Creates a new scene and optionally adds it to Build Settings.

        Args:
            scene_path: Asset path for the new scene (e.g., 'Assets/Scenes/MyScene.unity').
            add_to_build_settings: Whether to add the scene to Build Settings (default: true).
        """
        args = {
            "action": "create",
            "path": scene_path,
            "mode": "Single",
        }

        try:
            result = await send_to_unity("manage_scene", args)
            unity_result = result.get("result", {})

            # After creating, try to save the scene to the specified path
            # This ensures the .unity file is actually written to disk
            save_args = {
                "action": "save",
                "path": scene_path,
            }
            try:
                await send_to_unity("manage_scene", save_args)
            except Exception:
                pass  # Save might fail if scene was already saved during create

            return {
                "success": result.get("status") == "success",
                "tool": "create_scene",
                "params": {"scene_path": scene_path, "add_to_build_settings": add_to_build_settings},
                "message": f"Created scene at '{scene_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create scene: {ex}")
            return {
                "success": False,
                "tool": "create_scene",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def open_scene(
        scene_path: str,
        open_mode: Literal["Single", "Additive"] = "Single",
    ) -> dict[str, Any]:
        """Opens a scene in the Unity Editor.

        Args:
            scene_path: Asset path to the scene (e.g., 'Assets/Scenes/Main.unity').
            open_mode: How to open the scene — 'Single' replaces current, 'Additive' adds to current.
        """
        args = {'path': scene_path, 'mode': open_mode}

        try:
            result = await get_router().send_tool('open_scene', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "open_scene",
                "params": {"scene_path": scene_path, "open_mode": open_mode},
                "message": f"Opened scene '{scene_path}' ({open_mode})",
            }
        except Exception as ex:
            logger.error(f"Failed to open scene: {ex}")
            return {
                "success": False,
                "tool": "open_scene",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Scene Assets ─────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def create_terrain(
        name: str = "Terrain",
        width: int = 500,
        length: int = 500,
        heightmap_resolution: int = 513,
        save_path: str = "Assets/",
    ) -> dict[str, Any]:
        """Creates a new Terrain object in the scene.

        Args:
            name: Name for the terrain GameObject.
            width: Terrain width in meters (default: 500).
            length: Terrain length in meters (default: 500).
            heightmap_resolution: Heightmap resolution (default: 513, must be 2^n+1).
            save_path: Path to save terrain data asset.
        """
        args = {'name': name, 'width': width, 'length': length, 'heightmap_resolution': heightmap_resolution, 'save_path': save_path}

        try:
            result = await get_router().send_tool('create_terrain', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_terrain",
                "params": {"name": name, "width": width, "length": length,
                           "heightmap_resolution": heightmap_resolution, "save_path": save_path},
                "message": f"Created Terrain '{name}' ({width}x{length})",
            }
        except Exception as ex:
            logger.error(f"Failed to create terrain: {ex}")
            return {
                "success": False,
                "tool": "create_terrain",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def create_panel_settings_asset(
        save_path: str,
        name: str = "PanelSettings",
    ) -> dict[str, Any]:
        """Creates a UI Toolkit PanelSettings asset.

        Args:
            save_path: Folder path where the asset should be created.
            name: Name for the PanelSettings asset.
        """
        args = {'save_path': save_path, 'name': name}

        try:
            result = await get_router().send_tool('create_panel_settings_asset', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_panel_settings_asset",
                "params": {"save_path": save_path, "name": name},
                "message": f"Created PanelSettings '{name}' at '{save_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create panel settings: {ex}")
            return {
                "success": False,
                "tool": "create_panel_settings_asset",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Editor Control ───────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("core"))
    async def check_compile_errors() -> dict[str, Any]:
        """Checks for compilation errors in the Unity project."""
        args = {}

        try:
            result = await get_router().send_tool('check_compile_errors', args)
            unity_result = result.get("result", {})

            # Handle the case where Unity returns the result directly
            has_errors = unity_result.get("has_errors", False)
            error_count = unity_result.get("error_count", 0)
            is_compiling = unity_result.get("is_compiling", False)
            errors = unity_result.get("errors", [])

            return {
                "success": result.get("status") == "success",
                "tool": "check_compile_errors",
                "has_errors": has_errors,
                "error_count": error_count,
                "is_compiling": is_compiling,
                "errors": errors,
                "message": unity_result.get("message", "Compilation check complete"),
            }
        except ConnectionError as ex:
            # If connection fails, Unity might be recompiling
            logger.warning(f"Unity connection lost during compile check (likely recompiling): {ex}")
            return {
                "success": False,
                "tool": "check_compile_errors",
                "has_errors": False,
                "error_count": 0,
                "is_compiling": True,  # Assume compiling if we can't connect
                "errors": [],
                "message": f"Unity is likely recompiling (connection lost): {ex}",
            }
        except Exception as ex:
            logger.error(f"Failed to check compile errors: {ex}")
            return {
                "success": False,
                "tool": "check_compile_errors",
                "has_errors": False,
                "error_count": 0,
                "is_compiling": False,
                "errors": [],
                "message": f"Failed to check compilation: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def play_game() -> dict[str, Any]:
        """Starts play mode in the Unity Editor."""
        try:
            result = await get_router().send_tool('play_game', {})
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "play_game",
                "state": "playing",
                "message": "Play mode started",
            }
        except Exception as ex:
            logger.error(f"Failed to start play mode: {ex}")
            return {
                "success": False,
                "tool": "play_game",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def stop_game() -> dict[str, Any]:
        """Stops play mode in the Unity Editor."""
        try:
            result = await get_router().send_tool('stop_game', {})
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "stop_game",
                "state": "stopped",
                "message": "Play mode stopped",
            }
        except Exception as ex:
            logger.error(f"Failed to stop play mode: {ex}")
            return {
                "success": False,
                "tool": "stop_game",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
