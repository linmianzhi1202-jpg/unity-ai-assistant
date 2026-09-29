"""
Animation Tools for the Unified MCP for Unity system.
Provides MCP tools for Unity animation system operations.
Group: animation

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


def register_animation_tools(mcp: FastMCP) -> None:
    """Register Animation tools with the MCP server."""
    group = "animation"

    # ── Animation Clips ──────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("animation"))
    async def create_animation_clip(
        clip_name: str,
        save_path: str,
        frame_rate: float | None = None,
        wrap_mode: Literal["Default", "Once", "Loop", "PingPong", "ClampForever"] | None = None,
        is_looping: bool | None = None,
    ) -> dict[str, Any]:
        """Creates a new AnimationClip (.anim) asset file.

        Args:
            clip_name: Name of the animation clip (e.g., 'Idle', 'Walk').
            save_path: Asset path to save the clip (e.g., 'Assets/Animations/Walk.anim').
            frame_rate: Samples per second (default: 60). Use 12 for 2D, 30/60 for 3D.
            wrap_mode: How the animation behaves at end. Defaults to 'Default'.
            is_looping: Whether the animation should loop. Defaults to false.
        """
        args: dict[str, Any] = {'clip_name': clip_name, 'save_path': save_path}
        if frame_rate is not None:
            args["frame_rate"] = frame_rate
        if wrap_mode is not None:
            args["wrap_mode"] = wrap_mode
        if is_looping is not None:
            args["is_looping"] = is_looping

        try:
            result = await get_router().send_tool('create_animation_clip', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_animation_clip",
                "params": {"clip_name": clip_name, "save_path": save_path,
                           "frame_rate": frame_rate, "wrap_mode": wrap_mode,
                           "is_looping": is_looping},
                "message": f"Created animation clip '{clip_name}' at '{save_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create animation clip: {ex}")
            return {
                "success": False,
                "tool": "create_animation_clip",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def get_animation_clip_data(
        clip_path: str,
        max_keyframes_per_curve: int | None = None,
    ) -> dict[str, Any]:
        """Reads data from an AnimationClip, including curves and keyframe values.

        Args:
            clip_path: Asset path to the .anim file (e.g., 'Assets/Animations/Walk.anim').
            max_keyframes_per_curve: Maximum keyframes per curve to limit output size.
        """
        args: dict[str, Any] = {'clip_path': clip_path}
        if max_keyframes_per_curve is not None:
            args["max_keyframes_per_curve"] = max_keyframes_per_curve

        try:
            result = await get_router().send_tool('get_animation_clip_data', args)
            return {
                "success": result.get("status") == "success",
                "tool": "get_animation_clip_data",
                "params": {"clip_path": clip_path, "max_keyframes_per_curve": max_keyframes_per_curve},
                "data": result.get("result", {}),
                "message": f"Retrieved animation clip data from '{clip_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to get animation clip data: {ex}")
            return {
                "success": False,
                "tool": "get_animation_clip_data",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def set_animation_curves(
        clip_path: str,
        gameobject_path: str,
        component_type: str,
        property_name: str,
        keyframes: str,
        curve_type: Literal["Float", "Vector3", "Quaternion", "Color"] = "Float",
    ) -> dict[str, Any]:
        """Sets float animation curves on an AnimationClip for 3D transform animations.

        Args:
            clip_path: Asset path to the .anim file.
            gameobject_path: Path to the animated GameObject relative to clip root.
            component_type: Component type (e.g., 'Transform', 'RectTransform').
            property_name: Property name (e.g., 'm_LocalPosition.x').
            keyframes: JSON array of keyframes: [{"time":0,"value":0,"inTangent":0,"outTangent":0},...].
            curve_type: Type of curve data (Float/Vector3/Quaternion/Color).
        """
        args: dict[str, Any] = {'clip_path': clip_path, 'gameobject_path': gameobject_path, 'component_type': component_type, 'property_name': property_name, 'keyframes': keyframes, 'curve_type': curve_type}

        try:
            result = await get_router().send_tool('set_animation_curves', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_animation_curves",
                "params": {"clip_path": clip_path, "gameobject_path": gameobject_path,
                           "component_type": component_type, "property_name": property_name,
                           "keyframes": keyframes, "curve_type": curve_type},
                "message": f"Set animation curves on '{clip_path}' for '{property_name}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set animation curves: {ex}")
            return {
                "success": False,
                "tool": "set_animation_curves",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def set_sprite_animation_curve(
        clip_path: str,
        sprites: str,
        frame_rate: float = 12.0,
    ) -> dict[str, Any]:
        """Sets sprite animation curve for 2D frame-by-frame animation.

        Args:
            clip_path: Asset path to the .anim file.
            sprites: Comma-separated list of sprite asset paths
                     (e.g., 'Assets/Sprites/frame1.png,Assets/Sprites/frame2.png').
            frame_rate: Frames per second (default: 12 for 2D).
        """
        args: dict[str, Any] = {'clip_path': clip_path, 'sprites': sprites, 'frame_rate': frame_rate}

        try:
            result = await get_router().send_tool('set_sprite_animation_curve', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_sprite_animation_curve",
                "params": {"clip_path": clip_path, "sprites": sprites, "frame_rate": frame_rate},
                "message": f"Set sprite animation curve on '{clip_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set sprite animation curve: {ex}")
            return {
                "success": False,
                "tool": "set_sprite_animation_curve",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def set_animation_clip_settings(
        clip_path: str,
        frame_rate: float | None = None,
        wrap_mode: Literal["Default", "Once", "Loop", "PingPong", "ClampForever"] | None = None,
        is_looping: bool | None = None,
        clear_curves: bool = False,
        clear_events: bool = False,
    ) -> dict[str, Any]:
        """Modifies animation clip settings (frame rate, loop, clear curves/events).

        Args:
            clip_path: Asset path to the .anim file.
            frame_rate: New frame rate.
            wrap_mode: New wrap mode.
            is_looping: New looping setting.
            clear_curves: Whether to remove all curves (default: false).
            clear_events: Whether to remove all events (default: false).
        """
        args: dict[str, Any] = {'clip_path': clip_path}
        if frame_rate is not None:
            args["frame_rate"] = frame_rate
        if wrap_mode is not None:
            args["wrap_mode"] = wrap_mode
        if is_looping is not None:
            args["is_looping"] = is_looping
        args["clear_curves"] = clear_curves
        args["clear_events"] = clear_events

        try:
            result = await get_router().send_tool('set_animation_clip_settings', args)
            return {
                "success": result.get("status") == "success",
                "tool": "set_animation_clip_settings",
                "params": {"clip_path": clip_path, "frame_rate": frame_rate,
                           "wrap_mode": wrap_mode, "is_looping": is_looping,
                           "clear_curves": clear_curves, "clear_events": clear_events},
                "message": f"Updated animation clip settings on '{clip_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to set animation clip settings: {ex}")
            return {
                "success": False,
                "tool": "set_animation_clip_settings",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Animator Controller ──────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("animation"))
    async def create_animator_controller(
        controller_path: str,
        controller_name: str | None = None,
    ) -> dict[str, Any]:
        """Creates a new Animator Controller asset.

        Args:
            controller_path: Asset path for the controller (e.g., 'Assets/Animators/Player.controller').
            controller_name: Optional display name.
        """
        args: dict[str, Any] = {'controller_path': controller_path}
        if controller_name:
            args["controller_name"] = controller_name

        try:
            result = await get_router().send_tool('create_animator_controller', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_animator_controller",
                "params": {"controller_path": controller_path, "controller_name": controller_name},
                "message": f"Created animator controller at '{controller_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create animator controller: {ex}")
            return {
                "success": False,
                "tool": "create_animator_controller",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def get_animator_controller_data(
        controller_path: str,
    ) -> dict[str, Any]:
        """Reads the structure of an Animator Controller (layers, states, transitions, parameters).

        Args:
            controller_path: Asset path to the .controller file.
        """
        args: dict[str, Any] = {'controller_path': controller_path}

        try:
            result = await get_router().send_tool('get_animator_controller_data', args)
            return {
                "success": result.get("status") == "success",
                "tool": "get_animator_controller_data",
                "params": {"controller_path": controller_path},
                "data": result.get("result", {}),
                "message": f"Retrieved animator controller data from '{controller_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to get animator controller data: {ex}")
            return {
                "success": False,
                "tool": "get_animator_controller_data",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def modify_animator_controller(
        controller_path: str,
        action: Literal["add_parameter", "remove_parameter", "add_state", "remove_state",
                        "add_transition", "remove_transition", "add_layer", "remove_layer"],
        params: str | None = None,
    ) -> dict[str, Any]:
        """Batch modifies an Animator Controller (parameters/layers/states/transitions).

        Args:
            controller_path: Asset path to the .controller file.
            action: The modification action to perform.
            params: JSON string with action-specific parameters.
        """
        args: dict[str, Any] = {
            "action_name": "modify_animator_controller",
            "controller_path": controller_path,
            "modification_action": action,
        }
        if params:
            args["modification_params"] = params

        try:
            result = await get_router().send_tool('modify_animator_controller', args)
            return {
                "success": result.get("status") == "success",
                "tool": "modify_animator_controller",
                "params": {"controller_path": controller_path, "action": action, "params": params},
                "message": f"Modified animator controller '{controller_path}' — {action}",
            }
        except Exception as ex:
            logger.error(f"Failed to modify animator controller: {ex}")
            return {
                "success": False,
                "tool": "modify_animator_controller",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    # ── Blend Trees ──────────────────────────────────────────────────

    @mcp.tool(tags=make_group_tags("animation"))
    async def create_blend_tree_state(
        controller_path: str,
        state_name: str,
        blend_type: Literal["1D", "2D"] = "1D",
        blend_parameter: str = "Speed",
        blend_parameter_y: str | None = None,
        motions: str | None = None,
        layer_index: int = 0,
    ) -> dict[str, Any]:
        """Creates a blend tree state in an Animator Controller.

        Args:
            controller_path: Asset path to the .controller file.
            state_name: Name for the blend tree state.
            blend_type: Blend type — '1D' or '2D' (default: '1D').
            blend_parameter: Name of the blend parameter.
            blend_parameter_y: Name of second blend parameter for 2D trees.
            motions: JSON array of motions: [{"motion":"Assets/Anim/Walk.anim","threshold":0.5},...].
            layer_index: Animator layer index (default: 0).
        """
        args: dict[str, Any] = {'controller_path': controller_path, 'state_name': state_name, 'blend_type': blend_type, 'blend_parameter': blend_parameter, 'layer_index': layer_index}
        if blend_parameter_y:
            args["blend_parameter_y"] = blend_parameter_y
        if motions:
            args["motions"] = motions

        try:
            result = await get_router().send_tool('create_blend_tree_state', args)
            return {
                "success": result.get("status") == "success",
                "tool": "create_blend_tree_state",
                "params": {"controller_path": controller_path, "state_name": state_name,
                           "blend_type": blend_type, "blend_parameter": blend_parameter,
                           "blend_parameter_y": blend_parameter_y, "motions": motions,
                           "layer_index": layer_index},
                "message": f"Created blend tree state '{state_name}' in '{controller_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to create blend tree state: {ex}")
            return {
                "success": False,
                "tool": "create_blend_tree_state",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def get_blend_tree_state_data(
        controller_path: str,
        state_name: str,
        layer_index: int = 0,
    ) -> dict[str, Any]:
        """Reads blend tree state data from an Animator Controller.

        Args:
            controller_path: Asset path to the .controller file.
            state_name: Name of the blend tree state.
            layer_index: Animator layer index (default: 0).
        """
        args: dict[str, Any] = {'controller_path': controller_path, 'state_name': state_name, 'layer_index': layer_index}

        try:
            result = await get_router().send_tool('get_blend_tree_state_data', args)
            return {
                "success": result.get("status") == "success",
                "tool": "get_blend_tree_state_data",
                "params": {"controller_path": controller_path, "state_name": state_name,
                           "layer_index": layer_index},
                "data": result.get("result", {}),
                "message": f"Retrieved blend tree state data for '{state_name}'",
            }
        except Exception as ex:
            logger.error(f"Failed to get blend tree state data: {ex}")
            return {
                "success": False,
                "tool": "get_blend_tree_state_data",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }

    @mcp.tool(tags=make_group_tags("animation"))
    async def list_model_animation_clips(
        model_path: str,
    ) -> dict[str, Any]:
        """Lists embedded animation clips in an FBX or other 3D model file.

        Args:
            model_path: Asset path to the model file (e.g., 'Assets/Models/Character.fbx').
        """
        args: dict[str, Any] = {'model_path': model_path}

        try:
            result = await get_router().send_tool('list_model_animation_clips', args)
            return {
                "success": result.get("status") == "success",
                "tool": "list_model_animation_clips",
                "params": {"model_path": model_path},
                "clips": result.get("result", {}).get("clips", []),
                "message": f"Listed animation clips from '{model_path}'",
            }
        except Exception as ex:
            logger.error(f"Failed to list model animation clips: {ex}")
            return {
                "success": False,
                "tool": "list_model_animation_clips",
                "error": str(ex),
                "message": f"Failed to connect to Unity: {ex}",
            }
