"""
UI Tools for the Unified MCP for Unity system.
Provides MCP tools for Unity UI system operations.
Group: ui

IMPORTANT: All tools dispatch to Unity Editor via UnityBridge TCP client.
Previously these were stub implementations that returned "dispatched to Unity"
without actually communicating with Unity. Fixed in Phase 1A.
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
from typing import Any, Literal

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_ui_tools(mcp: FastMCP) -> None:
    """Register UI tools with the MCP server."""
    group = "ui"

    @mcp.tool(tags=make_group_tags("ui"))
    async def set_rect_transform(
        gameobject_path: str,
        anchor_min: str | None = None,
        anchor_max: str | None = None,
        pivot: str | None = None,
        size_delta: str | None = None,
        anchored_position: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Sets RectTransform properties of a UI GameObject.

        Args:
            gameobject_path: Path to the UI GameObject.
            anchor_min: Comma-separated anchor minimum values (x,y).
            anchor_max: Comma-separated anchor maximum values (x,y).
            pivot: Comma-separated pivot point values (x,y).
            size_delta: Comma-separated size delta values (width,height).
            anchored_position: Comma-separated anchored position values (x,y).
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path}
        if anchor_min is not None:
            args["anchor_min"] = anchor_min
        if anchor_max is not None:
            args["anchor_max"] = anchor_max
        if pivot is not None:
            args["pivot"] = pivot
        if size_delta is not None:
            args["size_delta"] = size_delta
        if anchored_position is not None:
            args["anchored_position"] = anchored_position
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('set_rect_transform', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_rect_transform",
                "params": {"gameobject_path": gameobject_path, "anchor_min": anchor_min,
                           "anchor_max": anchor_max, "pivot": pivot,
                           "size_delta": size_delta, "anchored_position": anchored_position,
                           "prefab_path": prefab_path},
                "message": f"Set RectTransform on '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set rect transform: {ex}")
            return {
                "success": False,
                "tool": "set_rect_transform",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("ui"))
    async def create_ui_element(
        element_type: Literal["button", "text", "image", "panel", "inputfield", "dropdown", "toggle", "scrollview"],
        element_name: str,
        parent_path: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Creates a UI element in the scene.

        Args:
            element_type: Type of UI element to create (button/text/image/panel/inputfield/dropdown/toggle/scrollview).
            element_name: Name for the new UI element.
            parent_path: Optional parent GameObject path. Defaults to Canvas.
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'element_type': element_type, 'element_name': element_name}
        if parent_path:
            args["parent_path"] = parent_path
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('create_ui_element', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_ui_element",
                "params": {"element_type": element_type, "element_name": element_name,
                           "parent_path": parent_path, "prefab_path": prefab_path},
                "message": f"Created UI element '{element_name}' of type '{element_type}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create UI element: {ex}")
            return {
                "success": False,
                "tool": "create_ui_element",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("ui"))
    async def set_ui_text(
        gameobject_path: str,
        text: str | None = None,
        font_size: int | None = None,
        color: str | None = None,
        alignment: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Sets UI text properties (content, font size, color, alignment).

        Args:
            gameobject_path: Path to the UI text GameObject.
            text: The text content to display.
            font_size: Font size.
            color: Comma-separated RGBA color (e.g., '1,1,1,1').
            alignment: Text alignment ('UpperLeft', 'MiddleCenter', 'LowerRight', etc.).
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path}
        if text is not None:
            args["text"] = text
        if font_size is not None:
            args["font_size"] = font_size
        if color is not None:
            args["color"] = color
        if alignment is not None:
            args["alignment"] = alignment
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('set_ui_text', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_ui_text",
                "params": {"gameobject_path": gameobject_path, "text": text,
                           "font_size": font_size, "color": color,
                           "alignment": alignment, "prefab_path": prefab_path},
                "message": f"Set UI text on '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set UI text: {ex}")
            return {
                "success": False,
                "tool": "set_ui_text",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("ui"))
    async def set_ui_layout(
        gameobject_path: str,
        layout_type: Literal["vertical", "horizontal", "grid"],
        spacing: float | None = None,
        padding: str | None = None,
        child_alignment: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Sets layout properties on a UI GameObject.

        Args:
            gameobject_path: Path to the UI GameObject.
            layout_type: Type of layout to apply (vertical/horizontal/grid).
            spacing: Space between child elements.
            padding: Comma-separated padding (left,right,top,bottom).
            child_alignment: Child alignment setting.
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path, 'layout_type': layout_type}
        if spacing is not None:
            args["spacing"] = spacing
        if padding is not None:
            args["padding"] = padding
        if child_alignment is not None:
            args["child_alignment"] = child_alignment
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('set_ui_layout', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_ui_layout",
                "params": {"gameobject_path": gameobject_path, "layout_type": layout_type,
                           "spacing": spacing, "padding": padding,
                           "child_alignment": child_alignment, "prefab_path": prefab_path},
                "message": f"Set layout '{layout_type}' on '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set UI layout: {ex}")
            return {
                "success": False,
                "tool": "set_ui_layout",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("ui"))
    async def add_persistent_listener(
        gameobject_path: str,
        event_name: str = "onClick",
        target_path: str | None = None,
        method_name: str | None = None,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Adds a persistent event listener to a UI component (e.g., Button.onClick).

        Args:
            gameobject_path: Path to the UI GameObject with the event.
            event_name: Name of the event (e.g., 'onClick', 'onValueChanged').
            target_path: Path to the target GameObject that has the method.
            method_name: Name of the method to call on the target.
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path, 'event_name': event_name}
        if target_path is not None:
            args["target_path"] = target_path
        if method_name is not None:
            args["method_name"] = method_name
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('add_persistent_listener', args)
            unity_result = result.get("result", {}) if isinstance(result, dict) else {}
            success = result.get("status") == "success"
            if not success:
                error = result.get("error") or unity_result.get("error") or "Failed to add persistent listener"
                return {
                    "success": False,
                    "tool": "add_persistent_listener",
                    "params": {"gameobject_path": gameobject_path, "event_name": event_name,
                               "target_path": target_path, "method_name": method_name,
                               "prefab_path": prefab_path},
                    "error": error,
                    "message": error,
                }

            return {
                "success": True,
                "tool": "add_persistent_listener",
                "params": {"gameobject_path": gameobject_path, "event_name": event_name,
                           "target_path": target_path, "method_name": method_name,
                           "prefab_path": prefab_path},
                "target_component": unity_result.get("target_component"),
                "method_name": unity_result.get("method_name", method_name),
                "method_params": unity_result.get("method_params"),
                "binding_strategy": unity_result.get("binding_strategy"),
                "unity_result": unity_result,
                "message": unity_result.get(
                    "message",
                    f"Added persistent listener '{event_name}' to '{gameobject_path}'",
                ),
            }
        except Exception as ex:
            logger.error(f"Failed to add persistent listener: {ex}")
            return {
                "success": False,
                "tool": "add_persistent_listener",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("ui"))
    async def remove_persistent_listener(
        gameobject_path: str,
        event_name: str = "onClick",
        listener_index: int = 0,
        prefab_path: str | None = None,
    ) -> dict[str, Any]:
        """Removes a persistent event listener from a UI component.

        Args:
            gameobject_path: Path to the UI GameObject.
            event_name: Name of the event (e.g., 'onClick').
            listener_index: Index of the listener to remove (0-based).
            prefab_path: Optional path to a prefab asset.
        """
        args: dict[str, Any] = {'gameobject_path': gameobject_path, 'event_name': event_name, 'listener_index': listener_index}
        if prefab_path:
            args["prefab_path"] = prefab_path

        try:
            result = await get_router().send_tool('remove_persistent_listener', args)
            return {
                "success": result.get("status") == "success",
                "tool": "remove_persistent_listener",
                "params": {"gameobject_path": gameobject_path, "event_name": event_name,
                           "listener_index": listener_index, "prefab_path": prefab_path},
                "message": f"Removed persistent listener #{listener_index} from '{gameobject_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to remove persistent listener: {ex}")
            return {
                "success": False,
                "tool": "remove_persistent_listener",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
