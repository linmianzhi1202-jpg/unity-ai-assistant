"""
AI Generation Service for the Unified MCP for Unity system.
Provides unified dispatch for AI image, SFX, and 3D model generation.
"""

from __future__ import annotations

import asyncio
import base64
import io
import mimetypes
import os
from pathlib import Path
import wave
import httpx
from core.config import config
from services.meshy_client import MeshyClient
import logging
import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AIGenerationType(str, Enum):
    IMAGE = "image"
    SFX = "sfx"
    MODEL_3D = "3d_model"
    MODEL_TEXTURE = "3d_texture"
    AUTO_RIG = "auto_rig"
    APPLY_ANIMATION = "apply_animation"
    SEARCH_ANIMATION = "search_animation"


class AITaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class AITask(BaseModel):
    """Represents an AI generation task."""
    task_id: str
    generation_type: AIGenerationType
    status: AITaskStatus = AITaskStatus.PENDING
    progress: float = 0.0
    created_at: float
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class AIGenerationRequest(BaseModel):
    """Request model for AI generation."""
    generation_type: AIGenerationType
    prompt: str
    model: str | None = None
    resolution: str | None = None        # For images: "1k", "2k", "4k"
    aspect_ratio: str | None = None      # For images: "1:1", "16:9", etc.
    duration: float | None = None        # For SFX: 0.5-30 seconds
    format: str | None = None            # Output format: "png", "jpg", "wav", "mp3"
    image_path: str | None = None        # For image-to-3D
    mesh_quality: str | None = None      # For 3D: "low", "medium", "high"
    topology: str | None = None          # For 3D: "quad", "triangle"
    pose_mode: str | None = None         # For 3D: "a-pose", "t-pose"
    model_path: str | None = None        # For auto_rig / apply_animation
    animation_style: str | None = None   # For apply_animation / search


class AIGenerationService:
    """Unified AI generation service.

    Dispatches generation requests to appropriate providers:
    - Image: OpenAI Images API
    - SFX: Configured provider
    - 3D: Meshy-5/6

    This service manages task lifecycle and progress tracking.
    Actual API calls to providers are delegated to provider adapters.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, AITask] = {}
        self._providers: dict[AIGenerationType, Any] = {}

    def register_provider(self, generation_type: AIGenerationType, provider: Any) -> None:
        """Register a provider adapter for a generation type."""
        self._providers[generation_type] = provider

    async def submit(self, request: AIGenerationRequest, timeout: float = 120.0) -> AITask:
        """Submit an AI generation request.

        Args:
            request: The generation request.
            timeout: Maximum time to wait for completion (seconds).

        Returns:
            AITask with the result.
        """
        task_id = str(uuid.uuid4())
        task = AITask(
            task_id=task_id,
            generation_type=request.generation_type,
            created_at=time.time(),
        )
        self._tasks[task_id] = task

        provider = self._providers.get(request.generation_type)
        if not provider:
            task.status = AITaskStatus.FAILED
            task.completed_at = time.time()
            task.error = f"No provider registered for {request.generation_type.value}"
            return task

        try:
            task.status = AITaskStatus.PROCESSING
            result = await asyncio.wait_for(
                provider.generate(request),
                timeout=timeout,
            )
            if not isinstance(result, dict) or result.get("status") != "completed":
                raise RuntimeError("Provider did not report a completed result")
            if request.generation_type != AIGenerationType.SEARCH_ANIMATION:
                output = Path(result.get("output_path", ""))
                if not output.is_file() or output.stat().st_size == 0:
                    raise RuntimeError("Provider result has no nonempty output file")
            task.status = AITaskStatus.COMPLETED
            task.progress = 1.0
            task.result = result
            task.completed_at = time.time()
        except asyncio.CancelledError:
            task.status = AITaskStatus.FAILED
            task.error = "Generation cancelled locally; a submitted remote job may still be running"
            task.completed_at = time.time()
            raise
        except asyncio.TimeoutError:
            task.status = AITaskStatus.FAILED
            task.error = "Generation timed out; a submitted remote job may still be running"
            task.completed_at = time.time()
        except Exception as e:
            task.status = AITaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()
            logger.error(f"AI generation failed: {e}", exc_info=True)

        return task

    def get_task(self, task_id: str) -> AITask | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self, status: AITaskStatus | None = None) -> list[AITask]:
        """List all tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def cleanup(self, max_age_sec: float = 3600) -> int:
        """Remove completed/failed tasks older than max_age_sec.

        Returns:
            Number of tasks removed.
        """
        now = time.time()
        to_remove = []
        for task_id, task in self._tasks.items():
            if task.status in (AITaskStatus.COMPLETED, AITaskStatus.FAILED):
                if task.completed_at and (now - task.completed_at) > max_age_sec:
                    to_remove.append(task_id)

        for task_id in to_remove:
            del self._tasks[task_id]

        return len(to_remove)


# ─── Provider Adapter Interface ───


class AIProviderAdapter:
    """Base class for AI provider adapters."""

    async def generate(self, request: AIGenerationRequest) -> dict[str, Any]:
        """Execute a generation request.

        Returns:
            Dict with generation result (file paths, URLs, metadata).
        """
        raise NotImplementedError


def _output_path(prefix: str, suffix: str) -> Path:
    directory = Path(config.ai_output_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{uuid.uuid4().hex}{suffix}"


def _input_uri(value: str | None) -> str:
    if not value:
        raise ValueError("An input model/image is required")
    if value.startswith(("https://", "data:")):
        return value
    path = Path(value).expanduser()
    if not path.is_absolute() and config.unity_project_path:
        path = Path(config.unity_project_path) / path
    data = path.read_bytes()
    if not data:
        raise ValueError("Input file is empty")
    mime = "model/gltf-binary" if path.suffix.lower() == ".glb" else mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


class ImageProviderAdapter(AIProviderAdapter):
    def __init__(self, model: str = "gpt-image-1", api_key: str | None = None):
        self.model, self.api_key = model, api_key

    async def generate(self, request: AIGenerationRequest) -> dict[str, Any]:
        key = self.api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY is required")
        if not request.prompt.strip():
            raise ValueError("prompt is required")
        model = request.model or self.model
        sizes = {"1:1": "1024x1024", "3:2": "1536x1024", "2:3": "1024x1536", "auto": "auto"}
        ratio = request.aspect_ratio or "1:1"
        if ratio not in sizes:
            raise ValueError("Supported aspect ratios: 1:1, 3:2, 2:3, auto")
        if request.resolution not in (None, "1k", "auto", "1024x1024", "1536x1024", "1024x1536"):
            raise ValueError("Use a supported native image size; 2k/4k are not supported by this adapter")
        size = request.resolution if request.resolution and "x" in request.resolution else sizes[ratio]
        fmt = (request.format or "png").lower().replace("jpg", "jpeg")
        if fmt not in {"png", "jpeg", "webp"}:
            raise ValueError("Image format must be png, jpeg or webp")
        async with httpx.AsyncClient(timeout=config.ai_generation_timeout) as client:
            response = await client.post("https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": model, "prompt": request.prompt, "n": 1, "size": size, "output_format": fmt})
            response.raise_for_status()
            data = base64.b64decode(response.json()["data"][0]["b64_json"], validate=True)
        if not data or not (data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8") or (data.startswith(b"RIFF") and data[8:12] == b"WEBP")):
            raise RuntimeError("Provider returned invalid image bytes")
        from PIL import Image
        with Image.open(io.BytesIO(data)) as decoded:
            if decoded.format.lower() != fmt:
                raise RuntimeError("Provider returned an unexpected image format")
            decoded.verify()
        output = _output_path("image", "." + fmt)
        output.write_bytes(data)
        return {"success": True, "status": "completed", "model": model, "output_path": str(output), "size": size}


class SfxProviderAdapter(AIProviderAdapter):
    def __init__(self, provider: str = "elevenlabs", api_key: str | None = None):
        self.provider, self.api_key = provider, api_key

    async def generate(self, request: AIGenerationRequest) -> dict[str, Any]:
        if self.provider not in {"default", "elevenlabs"}:
            raise ValueError(f"Unsupported SFX provider: {self.provider}")
        key = self.api_key or os.environ.get("ELEVENLABS_API_KEY")
        if not key:
            raise ValueError("ELEVENLABS_API_KEY is required")
        if not request.prompt.strip():
            raise ValueError("prompt is required")
        if request.duration is not None and not .5 <= request.duration <= 30:
            raise ValueError("duration must be between 0.5 and 30 seconds")
        fmt = (request.format or "mp3").lower()
        if fmt not in {"wav", "mp3"}:
            raise ValueError("SFX format must be wav or mp3")
        payload = {"text": request.prompt, "model_id": "eleven_text_to_sound_v2"}
        if request.duration is not None:
            payload["duration_seconds"] = request.duration
        async with httpx.AsyncClient(timeout=config.ai_generation_timeout) as client:
            response = await client.post("https://api.elevenlabs.io/v1/sound-generation",
                headers={"xi-api-key": key}, params={"output_format": "pcm_44100" if fmt == "wav" else "mp3_44100_128"}, json=payload)
            response.raise_for_status()
            data = response.content
            if not data or "json" in response.headers.get("content-type", ""):
                raise RuntimeError("Provider returned no audio")
        if fmt == "wav":
            if len(data) % 2:
                raise RuntimeError("Invalid PCM audio length")
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(44100); audio.writeframes(data)
            data = buffer.getvalue()
        elif not (data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)):
            raise RuntimeError("Invalid MP3 audio")
        output = _output_path("sfx", "." + fmt)
        output.write_bytes(data)
        return {"success": True, "status": "completed", "provider": "elevenlabs", "output_path": str(output)}


class Model3DProviderAdapter(AIProviderAdapter):
    def __init__(self, provider: str = "meshy", api_key: str | None = None):
        self.provider, self.api_key = provider, api_key

    async def generate(self, request: AIGenerationRequest) -> dict[str, Any]:
        if self.provider != "meshy":
            raise ValueError(f"Unsupported 3D provider: {self.provider}")
        client = MeshyClient(self.api_key)
        try:
            kind = request.generation_type
            if kind == AIGenerationType.SEARCH_ANIMATION:
                results = await client.search_animations(request.prompt)
                return {"success": True, "status": "completed", "results": results, "count": len(results)}
            polycount = {None: None, "low": 10000, "medium": 30000, "high": 100000}
            if request.mesh_quality not in polycount:
                raise ValueError("mesh_quality must be low, medium or high")
            if request.topology not in (None, "quad", "triangle") or request.pose_mode not in (None, "a-pose", "t-pose"):
                raise ValueError("Invalid topology or pose_mode")
            if kind == AIGenerationType.MODEL_3D and not request.image_path:
                if not request.prompt.strip():
                    raise ValueError("prompt is required")
                preview = await client.create_preview(request.prompt, topology=request.topology,
                    target_polycount=polycount[request.mesh_quality], pose_mode=request.pose_mode,
                    should_remesh=bool(request.topology or request.mesh_quality))
                await client.poll_task(preview["result"])
                task_id = (await client.create_refine(preview["result"]))["result"]
                task = await client.poll_task(task_id)
            else:
                if kind == AIGenerationType.MODEL_3D:
                    resource, payload = "image-to-3d", {"image_url": _input_uri(request.image_path), "ai_model": "meshy-6"}
                    for key, value in {"topology": request.topology, "target_polycount": polycount[request.mesh_quality], "pose_mode": request.pose_mode}.items():
                        if value is not None: payload[key] = value
                    payload["should_remesh"] = bool(request.topology or request.mesh_quality)
                elif kind == AIGenerationType.MODEL_TEXTURE:
                    if not request.prompt.strip(): raise ValueError("Texture prompt is required")
                    resource, payload = "retexture", {"model_url": _input_uri(request.model_path), "text_style_prompt": request.prompt}
                elif kind == AIGenerationType.AUTO_RIG:
                    resource, payload = "rigging", {"model_url": _input_uri(request.model_path)}
                elif kind == AIGenerationType.APPLY_ANIMATION:
                    style = request.animation_style
                    if not style: raise ValueError("animation_style must be an action ID or unique animation name")
                    if style.isdigit(): action_id = int(style)
                    else:
                        matches = await client.search_animations(style)
                        if len(matches) != 1: raise ValueError(f"Animation name is ambiguous or absent; choose an action_id from search_animation ({len(matches)} matches)")
                        action_id = matches[0]["action_id"]
                    model_path = request.model_path or ""
                    if model_path.startswith("rig:"):
                        rig_id = model_path[4:]
                        if not rig_id: raise ValueError("rig task ID is required")
                    else:
                        rig_id = await client.create_v1_task("rigging", {"model_url": _input_uri(model_path)})
                        await client.poll_v1_task("rigging", rig_id)
                    resource, payload = "animations", {"rig_task_id": rig_id, "action_id": action_id}
                else:
                    raise ValueError(f"Unknown 3D operation: {kind}")
                task_id = await client.create_v1_task(resource, payload)
                task = await client.poll_v1_task(resource, task_id)
            urls = task.get("model_urls") or task.get("result") or {}
            choices = [(urls.get("fbx"), ".fbx"), (urls.get("rigged_character_fbx_url"), ".fbx"),
                       (urls.get("animation_fbx_url"), ".fbx"), (urls.get("glb"), ".glb"),
                       (urls.get("rigged_character_glb_url"), ".glb"), (urls.get("animation_glb_url"), ".glb")]
            selected = next(((url, suffix) for url, suffix in choices if url), None)
            if selected is None: raise RuntimeError(f"Meshy task {task_id} succeeded without a model download")
            output = _output_path("model", selected[1])
            await client.download_file(selected[0], output)
            textures = []
            for index, group in enumerate(task.get("texture_urls") or []):
                for name, url in group.items():
                    if not isinstance(url, str) or not url:
                        continue
                    safe_name = "".join(c for c in name if c.isalnum() or c == "_")
                    texture = output.parent / (output.stem + f"_{index}_{safe_name}.png")
                    await client.download_file(url, texture)
                    textures.append(str(texture))
            return {"success": True, "status": "completed", "provider": "meshy", "task_id": task_id,
                    "textures": textures,
                    "generation_type": kind.value, "output_path": str(output), "model_urls": urls}
        finally:
            await client.close()


# ─── Singleton Instance ───

_instance: AIGenerationService | None = None


def get_ai_generation_service() -> AIGenerationService:
    """Get or create the global AI generation service instance."""
    global _instance
    if _instance is None:
        _instance = AIGenerationService()
        _instance.register_provider(AIGenerationType.IMAGE, ImageProviderAdapter(config.ai_image_model))
        _instance.register_provider(AIGenerationType.SFX, SfxProviderAdapter(config.ai_sfx_provider))
        model = Model3DProviderAdapter(config.ai_3d_provider)
        for kind in (AIGenerationType.MODEL_3D, AIGenerationType.MODEL_TEXTURE, AIGenerationType.AUTO_RIG, AIGenerationType.APPLY_ANIMATION, AIGenerationType.SEARCH_ANIMATION):
            _instance.register_provider(kind, model)
    return _instance
