"""
Extended Unity Tools — Phase D: AI-First Unity Editor Control.
Provides MCP tools for creating ScriptableObjects with data, attaching custom
MonoBehaviours (cross-asmdef), and binding SerializeField references.

Group: core

Strategy: Each tool dispatches to Unity Editor via UnityBridge TCP client,
where C# ToolDispatcher.cs handlers execute in full Unity Editor context
with access to ALL project assemblies.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import json as json_module
import logging
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_extended_unity_tools(mcp: FastMCP) -> None:
    """Register Phase D extended Unity editor tools with the MCP server.

    Tools registered:
    - create_scriptable_object  — Create .asset with type+properties in one call
    - attach_mbehaviour         — Attach custom MonoBehaviour to GameObject (cross-asmdef)
    - set_serialized_reference  — Set SerializeField object reference (drag-drop equivalent)
    """
    group = "core"

    @mcp.tool(tags=make_group_tags("core"))
    async def create_scriptable_object(
        type_name: str,
        asset_path: str,
        properties: str | None = None,
    ) -> dict[str, Any]:
        """Create a ScriptableObject .asset with type name and property values in one step.

        This is the AI-first replacement for: ScriptableObject.CreateInstance + SerializedObject
        property writing + AssetDatabase.CreateAsset — all done in one Unity-side call.

        Use this instead of execute_script for creating project-specific ScriptableObjects
        like MyGame.Resources.ResourceNodeData, MyGame.Data.EventPromptData, etc.

        Args:
            type_name: Full type name with assembly. Examples:
                "MyGame.Resources.ResourceNodeData, MyGame.Resources"
                "MyGame.Data.EventPromptData, MyGame.Data"
                "MyGame.Cards.CardData, MyGame.Cards"
                Also supports short names like "ResourceNodeData" (scans all assemblies).
            asset_path: Destination path for the .asset file, e.g.
                "Assets/MyGame/ScriptableObjects/ResourceNodes/ResourceNode_rn_01.asset".
                Parent directories are created automatically.
            properties: JSON object string with property name→value pairs. Keys must match
                the serialized field names in the ScriptableObject. Supports:
                - string: {"id":"rn_01","displayName":"示例"}
                - int: {"level":3,"cardsPerRound":2}
                - float: {"rareCardBonus":0.15}
                - bool: {"isAvailable":true}
                - enum (by name): {"type":"Tower","school":"Heroic"}
                - object reference: {"_config":"Assets/Configs/GameConfig.asset"}
                - arrays (JSON array): {"producedSchools":["Heroic","Frontier"]}

        Returns:
            Dict with success status, created asset_path, type_name, and properties applied.

        Example:
            create_scriptable_object(
                type_name="MyGame.Resources.ResourceNodeData, MyGame.Resources",
                asset_path="Assets/MyGame/ScriptableObjects/ResourceNodes/Node.asset",
                properties='{"id":"rn_01","displayName":"示例","type":"Tower","level":1,'
                           '"cardsPerRound":1,"rareCardBonus":0.1,'
                           '"producedSchools":["Heroic","Nostalgia"]}'
            )
        """
        args: dict[str, Any] = {'type_name': type_name, 'asset_path': asset_path}
        if properties:
            args["properties"] = properties

        try:
            result = await get_router().send_tool('create_scriptable_object', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "create_scriptable_object",
                "params": {
                    "type_name": type_name,
                    "asset_path": asset_path,
                    "properties": properties,
                },
                "asset_path": unity_result.get("asset_path", asset_path),
                "type": unity_result.get("type", type_name),
                "properties_applied": unity_result.get("properties_applied", 0),
                "message": (
                    f"ScriptableObject '{type_name}' created at '{unity_result.get('asset_path', asset_path)}'"
                    if result.get("status") == "success"
                    else result.get("error", "Unknown error")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to create ScriptableObject: {ex}")
            return {
                "success": False,
                "tool": "create_scriptable_object",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def attach_mbehaviour(
        gameobject_path: str,
        script_type_name: str,
    ) -> dict[str, Any]:
        """Attach a custom MonoBehaviour script to a GameObject in the scene.

        Works across asmdef boundaries — resolves the type by scanning ALL loaded
        assemblies in the Unity Editor. Supports short names, full names, and
        assembly-qualified names.

        This is the AI-first replacement for: AddComponent<CustomScript>() where
        the custom script lives in a project asmdef that MCP can't directly reference.

        Args:
            gameobject_path: Hierarchy path to the GameObject, e.g.
                "Canvas/HUD" or "UIRoot/Canvas/CardSelectionPanel".
            script_type_name: Type name of the MonoBehaviour script. Supported formats:
                - Short name: "HudController", "LevelBootstrapper"
                - Full name: "MyGame.UI.HudController"
                - Assembly-qualified: "MyGame.UI.HudController, MyGame.UI"

        Returns:
            Dict with success status, added component type, and GameObject path.

        Example:
            attach_mbehaviour(
                gameobject_path="Canvas/HUD",
                script_type_name="HudController"
            )
        """
        args: dict[str, Any] = {'path': gameobject_path, 'script_type_name': script_type_name}

        try:
            result = await get_router().send_tool('attach_mbehaviour', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "attach_mbehaviour",
                "params": {
                    "gameobject_path": gameobject_path,
                    "script_type_name": script_type_name,
                },
                "component": unity_result.get("attached", script_type_name),
                "instanceId": unity_result.get("instanceId", ""),
                "message": (
                    f"Attached '{unity_result.get('attached', script_type_name)}' to '{gameobject_path}'"
                    if result.get("status") == "success"
                    else result.get("error", "Unknown error")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to attach MonoBehaviour: {ex}")
            return {
                "success": False,
                "tool": "attach_mbehaviour",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("core"))
    async def set_serialized_reference(
        gameobject_path: str,
        component_type: str,
        property_name: str,
        target_path: str,
    ) -> dict[str, Any]:
        """Set a SerializeField object reference on a component — the drag-and-drop equivalent.

        Binds a Unity object (GameObject, TextAsset, ScriptableObject, Material, etc.)
        to a SerializeField field on a MonoBehaviour component. This is the AI-first
        replacement for dragging assets onto Inspector fields.

        Common use case: after creating UI panels and attaching custom scripts,
        bind child GameObjects or assets to the script's SerializeField fields.

        Args:
            gameobject_path: Hierarchy path to the GameObject, e.g. "Canvas/HUD".
            component_type: Type name of the component that has the field.
                Examples: "HudController", "MyGame.UI.HudController, MyGame.UI".
            property_name: The SerializeField field name (exact C# field name).
                Examples: "_roundText", "_gameConfig", "_levelJson".
            target_path: The target to assign to the field. Accepts:
                - Hierarchy path: "Canvas/HUD/RoundText" (binds to GameObject)
                - Asset path: "Assets/MyGame/Data/levels.json" (binds to TextAsset)
                - Asset path: "Assets/MyGame/ScriptableObjects/Configs/GameConfig.asset"

        Returns:
            Dict with success status, the property that was set, and the value assigned.

        Example:
            # Bind a TMP child to HudController._roundText SerializeField
            set_serialized_reference(
                gameobject_path="Canvas/HUD",
                component_type="HudController",
                property_name="_roundText",
                target_path="Canvas/HUD/RoundText"
            )
        """
        args: dict[str, Any] = {'path': gameobject_path, 'component_type': component_type, 'property_name': property_name, 'target_path': target_path}

        try:
            result = await get_router().send_tool('set_serialized_reference', args)
            unity_result = result.get("result", {})
            return {
                "success": result.get("status") == "success",
                "tool": "set_serialized_reference",
                "params": {
                    "gameobject_path": gameobject_path,
                    "component_type": component_type,
                    "property_name": property_name,
                    "target_path": target_path,
                },
                "property": unity_result.get("property", f"{component_type}.{property_name}"),
                "assigned": unity_result.get("assigned", target_path),
                "message": (
                    f"Set '{component_type}.{property_name}' → '{unity_result.get('assigned', target_path)}'"
                    if result.get("status") == "success"
                    else result.get("error", "Unknown error")
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to set serialized reference: {ex}")
            return {
                "success": False,
                "tool": "set_serialized_reference",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
