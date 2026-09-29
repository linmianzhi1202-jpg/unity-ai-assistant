"""
AI Generation Tools for the Unified MCP for Unity system.
Provides MCP tools for AI-powered content generation: images, SFX, 3D models.
Group: ai_generation
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from core.config import config
from services.tools.tool_group_map import make_group_tags
from services.ai_generation_service import (
    AIGenerationType,
    AIGenerationRequest,
    get_ai_generation_service,
)
from core.error_codes import UnifiedErrorCode, make_error

logger = logging.getLogger(__name__)


def register_ai_generation_tools(mcp: FastMCP) -> None:
    """Register AI generation tools with the MCP server."""
    group = "ai_generation"

    @mcp.tool(tags=make_group_tags("ai_generation"))
    async def generate_image(
        prompt: str,
        model: str | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        """Generate images using the OpenAI Images API.

        Text-to-image generation. Native sizes: 1024x1024, 1536x1024, 1024x1536.
        Aspect ratios: 1:1, 3:2, 2:3, auto.

        Args:
            prompt: Text description of the image to generate.
            model: AI model to use (default: from config).
            resolution: Native size or 1k/auto.
            aspect_ratio: Output aspect ratio.
            format: Output format (png/jpeg/webp).
        """
        service = get_ai_generation_service()
        request = AIGenerationRequest(
            generation_type=AIGenerationType.IMAGE,
            prompt=prompt,
            model=model or config.ai_image_model,
            resolution=resolution,
            aspect_ratio=aspect_ratio,
            format=format,
        )
        task = await service.submit(request, timeout=config.ai_generation_timeout)
        if task.status == "failed":
            return make_error(
                UnifiedErrorCode.AI_PROVIDER_ERROR,
                message=task.error or "Image generation failed",
            )
        return task.result or {}

    @mcp.tool(tags=make_group_tags("ai_generation"))
    async def generate_sfx(
        prompt: str,
        duration: float | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        """Generate sound effects from text descriptions using AI.

        Creates WAV or MP3 audio files from text prompts.
        Duration range: 0.5-30 seconds.

        Args:
            prompt: Text description of the sound effect.
            duration: Desired duration in seconds (0.5-30).
            format: Output format (wav/mp3).
        """
        service = get_ai_generation_service()
        request = AIGenerationRequest(
            generation_type=AIGenerationType.SFX,
            prompt=prompt,
            duration=duration,
            format=format,
        )
        task = await service.submit(request, timeout=config.ai_generation_timeout)
        if task.status == "failed":
            return make_error(
                UnifiedErrorCode.AI_PROVIDER_ERROR,
                message=task.error or "SFX generation failed",
            )
        return task.result or {}

    @mcp.tool(tags=make_group_tags("ai_generation"))
    async def generate_3d_model(
        action: str,
        prompt: str | None = None,
        image_path: str | None = None,
        model_path: str | None = None,
        animation_style: str | None = None,
        mesh_quality: str | None = None,
        topology: str | None = None,
        pose_mode: str | None = None,
    ) -> dict[str, Any]:
        """AI-powered 3D model generation, texturing, rigging, and animation.

        Actions:
        - generate_from_text: Generate 3D model from text description
        - generate_from_image: Generate 3D model from an image
        - generate_texture: Generate texture for an existing 3D model
        - auto_rig: Automatically rig a 3D model with bones
        - apply_animation: Apply animation to a rigged model
        - search_animation: Search animation library

        Args:
            action: The 3D generation action to perform.
            prompt: Text description (for generate_from_text / generate_texture / search_animation).
            image_path: Path to source image (for generate_from_image).
            model_path: Path to 3D model (for generate_texture / auto_rig / apply_animation).
            animation_style: Animation style (for apply_animation / search_animation).
            mesh_quality: Mesh quality: low/medium/high (for generate_from_text/image).
            topology: Mesh topology: quad/triangle (for generate_from_text/image).
            pose_mode: Pose mode: a-pose/t-pose (for generate_from_text/image).
        """
        action_map = {
            "generate_from_text": AIGenerationType.MODEL_3D,
            "generate_from_image": AIGenerationType.MODEL_3D,
            "generate_texture": AIGenerationType.MODEL_TEXTURE,
            "auto_rig": AIGenerationType.AUTO_RIG,
            "apply_animation": AIGenerationType.APPLY_ANIMATION,
            "search_animation": AIGenerationType.SEARCH_ANIMATION,
        }

        gen_type = action_map.get(action)
        if not gen_type:
            return make_error(
                UnifiedErrorCode.PARAM_INVALID,
                message=f"Invalid action: {action}. Valid: {', '.join(action_map.keys())}",
            )

        if action == "generate_from_image" and not image_path:
            return make_error(UnifiedErrorCode.PARAM_INVALID, message="image_path is required")
        if action == "generate_from_text" and image_path:
            return make_error(UnifiedErrorCode.PARAM_INVALID, message="Use generate_from_image with image_path")
        service = get_ai_generation_service()
        request = AIGenerationRequest(
            generation_type=gen_type,
            prompt=prompt or (animation_style if action == "search_animation" else "") or "",
            image_path=image_path,
            model_path=model_path,
            animation_style=animation_style,
            mesh_quality=mesh_quality,
            topology=topology,
            pose_mode=pose_mode,
        )
        task = await service.submit(request, timeout=config.ai_generation_timeout)
        if task.status == "failed":
            return make_error(
                UnifiedErrorCode.AI_PROVIDER_ERROR,
                message=task.error or f"3D generation ({action}) failed",
            )
        return task.result or {}
