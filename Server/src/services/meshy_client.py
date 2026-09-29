"""
Meshy API Client - Real text-to-3D and text-to-image generation using Meshy API.
Supports:
  - Text-to-3D: preview + refine workflow with automatic polling (v2 API)
  - Text-to-Image: generate images via nano-banana-pro model (v1 API)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

MESHY_API_BASE_V2 = "https://api.meshy.ai/openapi/v2"
MESHY_API_BASE_V1 = "https://api.meshy.ai/openapi/v1"
DEFAULT_POLL_INTERVAL = 2.0
DEFAULT_TIMEOUT = 600.0  # 10 minutes per stage (some models need more refine time)
DEFAULT_IMAGE_TIMEOUT = 300.0  # 5 minutes for image generation (nano-banana-pro)


class MeshyClient:
    """Async client for Meshy Text-to-3D (v2) and Text-to-Image (v1) APIs."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("MESHY_API_KEY", "")
        if not self.api_key:
            raise ValueError("MESHY_API_KEY is required. Set it in .env or pass directly.")
        auth_headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self._http = httpx.AsyncClient(
            base_url=MESHY_API_BASE_V2,
            headers=auth_headers,
            timeout=60.0,
        )
        self._http_v1 = httpx.AsyncClient(
            base_url=MESHY_API_BASE_V1,
            headers=auth_headers,
            timeout=60.0,
        )

    async def close(self):
        await self._http.aclose()
        await self._http_v1.aclose()

    async def create_v1_task(self, resource: str, payload: dict) -> str:
        response = await self._http_v1.post(f"/{resource}", json=payload)
        response.raise_for_status()
        task_id = response.json().get("result")
        if not isinstance(task_id, str) or not task_id:
            raise RuntimeError("Meshy did not return a task ID")
        return task_id

    async def poll_v1_task(self, resource: str, task_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            response = await self._http_v1.get(f"/{resource}/{task_id}")
            response.raise_for_status()
            task = response.json()
            if task.get("status") == "SUCCEEDED":
                return task
            if task.get("status") in {"FAILED", "CANCELED", "CANCELLED"}:
                raise RuntimeError(f"Meshy {task_id}: {task.get('task_error', {})}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Meshy task {task_id} timed out; remote execution may continue")
            await asyncio.sleep(DEFAULT_POLL_INTERVAL)

    async def search_animations(self, query: str) -> list:
        response = await self._http_v1.get("/animations/library", params={"search": query})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, list):
            raise RuntimeError("Invalid Meshy animation catalogue response")
        return result

    async def create_preview(
        self,
        prompt: str,
        model_type: str = "standard",
        ai_model: str = "meshy-6",
        topology: str | None = None,
        target_polycount: int | None = None,
        pose_mode: str | None = None,
        should_remesh: bool = False,
    ) -> dict[str, Any]:
        """Create a text-to-3d preview task (geometry only, no texture)."""
        payload = {
            "mode": "preview",
            "prompt": prompt,
            "model_type": model_type,
            "ai_model": ai_model,
            "should_remesh": should_remesh,
        }
        if topology:
            payload["topology"] = topology
        if target_polycount:
            payload["target_polycount"] = target_polycount
        if pose_mode:
            payload["pose_mode"] = pose_mode

        resp = await self._http.post("/text-to-3d", json=payload)
        resp.raise_for_status()
        result = resp.json()
        return result  # {"result": "task_id"}

    async def create_refine(
        self,
        preview_task_id: str,
        enable_pbr: bool = True,
        hd_texture: bool = False,
        texture_prompt: str | None = None,
        ai_model: str = "meshy-6",
    ) -> dict[str, Any]:
        """Create a refine task to add textures to a preview model."""
        payload = {
            "mode": "refine",
            "preview_task_id": preview_task_id,
            "enable_pbr": enable_pbr,
            "hd_texture": hd_texture,
            "ai_model": ai_model,
        }
        if texture_prompt:
            payload["texture_prompt"] = texture_prompt

        resp = await self._http.post("/text-to-3d", json=payload)
        resp.raise_for_status()
        result = resp.json()
        return result  # {"result": "task_id"}

    async def get_task(self, task_id: str, retries: int = 3) -> dict[str, Any]:
        """Get task status and result."""
        for attempt in range(retries):
            try:
                resp = await self._http.get(f"/text-to-3d/{task_id}")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"GET retry {attempt+1}/{retries} after {wait}s: {e}")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def poll_task(
        self,
        task_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict[str, Any]:
        """Poll a task until it completes or fails."""
        start = time.time()
        consecutive_errors = 0
        while True:
            try:
                task = await self.get_task(task_id, retries=3)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                elapsed = time.time() - start
                if elapsed > timeout or consecutive_errors > 5:
                    raise RuntimeError(f"Task {task_id} failed after {consecutive_errors} consecutive network errors") from e
                logger.warning(f"Task {task_id}: poll error (attempt {consecutive_errors}), retrying in 3s: {e}")
                await asyncio.sleep(3.0)
                continue

            status = task.get("status", "UNKNOWN")
            progress = task.get("progress", 0)

            if status == "SUCCEEDED":
                logger.info(f"Task {task_id} succeeded (progress: {progress}%)")
                return task
            elif status in ("FAILED", "CANCELED"):
                error_msg = task.get("task_error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Task {task_id} {status}: {error_msg}")

            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(f"Task {task_id} timed out after {timeout}s (status: {status})")

            logger.info(f"Task {task_id}: {status} ({progress}%), elapsed: {elapsed:.0f}s")
            await asyncio.sleep(poll_interval)

    async def download_file(self, url: str, dest_path: Path) -> Path:
        """Download a file from URL to local path."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if not resp.content or any(t in resp.headers.get("content-type", "") for t in ("text/html", "application/json")):
                raise RuntimeError("Provider returned an empty or invalid download")
            dest_path.write_bytes(resp.content)
        logger.info(f"Downloaded: {dest_path}")
        return dest_path

    async def generate_model(
        self,
        prompt: str,
        name: str,
        output_dir: str | Path,
        model_type: str = "standard",
        topology: str | None = None,
        target_polycount: int | None = None,
        enable_pbr: bool = True,
        texture_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Complete text-to-3D workflow: preview -> poll -> refine -> poll -> download."""
        output_dir = Path(output_dir) / name
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"=== Generating 3D model: {name} ===")
        logger.info(f"  Prompt: {prompt[:120]}...")

        # Step 1: Create preview
        logger.info(f"[{name}] Creating preview task...")
        preview_result = await self.create_preview(
            prompt=prompt,
            model_type=model_type,
            topology=topology,
            target_polycount=target_polycount,
        )
        preview_task_id = preview_result["result"]
        logger.info(f"[{name}] Preview task ID: {preview_task_id}")

        # Step 2: Poll preview
        logger.info(f"[{name}] Waiting for preview to complete...")
        preview_task = await self.poll_task(preview_task_id)

        # Step 3: Create refine
        logger.info(f"[{name}] Creating refine task...")
        refine_result = await self.create_refine(
            preview_task_id=preview_task_id,
            enable_pbr=enable_pbr,
            texture_prompt=texture_prompt,
        )
        refine_task_id = refine_result["result"]
        logger.info(f"[{name}] Refine task ID: {refine_task_id}")

        # Step 4: Poll refine
        logger.info(f"[{name}] Waiting for refine to complete...")
        refine_task = await self.poll_task(refine_task_id)

        # Step 5: Download files
        logger.info(f"[{name}] Downloading model files...")
        model_urls = refine_task.get("model_urls", {})

        # Download GLB (preferred format for Unity)
        glb_url = model_urls.get("glb")
        if glb_url:
            await self.download_file(glb_url, output_dir / f"{name}.glb")

        # Download textures
        texture_urls = refine_task.get("texture_urls", [])
        if texture_urls:
            tex = texture_urls[0]
            tex_dir = output_dir / "textures"
            tex_dir.mkdir(exist_ok=True)
            for tex_name, tex_url in tex.items():
                if tex_url and isinstance(tex_url, str):
                    ext = ".png"
                    await self.download_file(tex_url, tex_dir / f"{name}_{tex_name}{ext}")

        # Save metadata
        metadata = {
            "name": name,
            "prompt": prompt,
            "preview_task_id": preview_task_id,
            "refine_task_id": refine_task_id,
            "model_urls": model_urls,
            "texture_urls": texture_urls,
            "thumbnail_url": refine_task.get("thumbnail_url"),
            "consumed_credits": refine_task.get("consumed_credits", 0),
        }
        (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

        logger.info(f"[{name}] Done! Files saved to {output_dir}")
        return metadata

    # ═══ Text-to-Image API (v1) ═══

    async def create_image(
        self,
        prompt: str,
        ai_model: str = "nano-banana-pro",
        aspect_ratio: str = "1:1",
        generate_multi_view: bool = False,
    ) -> dict[str, Any]:
        """Create a text-to-image task via Meshy v1 API."""
        payload = {
            "ai_model": ai_model,
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "generate_multi_view": generate_multi_view,
        }
        resp = await self._http_v1.post("/text-to-image", json=payload)
        resp.raise_for_status()
        return resp.json()  # {"result": "task_id"}

    async def get_image_task(self, task_id: str, retries: int = 3) -> dict[str, Any]:
        """Get text-to-image task status and result."""
        for attempt in range(retries):
            try:
                resp = await self._http_v1.get(f"/text-to-image/{task_id}")
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Image GET retry {attempt+1}/{retries} after {wait}s: {e}")
                    await asyncio.sleep(wait)
                else:
                    raise

    async def poll_image_task(
        self,
        task_id: str,
        poll_interval: float = 2.0,
        timeout: float = DEFAULT_IMAGE_TIMEOUT,
    ) -> dict[str, Any]:
        """Poll a text-to-image task until it completes or fails."""
        start = time.time()
        consecutive_errors = 0
        while True:
            try:
                task = await self.get_image_task(task_id, retries=3)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                elapsed = time.time() - start
                if elapsed > timeout or consecutive_errors > 5:
                    raise RuntimeError(
                        f"Image task {task_id} failed after {consecutive_errors} errors"
                    ) from e
                logger.warning(f"Image {task_id}: poll error {consecutive_errors}, retry in 3s")
                await asyncio.sleep(3.0)
                continue

            status = task.get("status", "UNKNOWN")
            progress = task.get("progress", 0)

            if status == "SUCCEEDED":
                logger.info(f"Image task {task_id} succeeded ({progress}%)")
                return task
            elif status in ("FAILED", "CANCELED"):
                error_msg = task.get("task_error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Image task {task_id} {status}: {error_msg}")

            elapsed = time.time() - start
            if elapsed > timeout:
                raise TimeoutError(
                    f"Image task {task_id} timed out after {timeout}s (status: {status})"
                )
            logger.info(f"Image {task_id}: {status} ({progress}%), elapsed: {elapsed:.0f}s")
            await asyncio.sleep(poll_interval)

    async def download_image(self, url: str, dest_path: Path) -> Path:
        """Download a generated image from URL to local path (PNG)."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            dest_path.write_bytes(resp.content)
        logger.info(f"Downloaded image: {dest_path}")
        return dest_path

    async def generate_image(
        self,
        prompt: str,
        name: str,
        output_dir: str | Path,
        ai_model: str = "nano-banana-pro",
        aspect_ratio: str = "1:1",
    ) -> dict[str, Any]:
        """Complete text-to-image workflow: create -> poll -> download."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"=== Generating image: {name} ===")
        logger.info(f"  Prompt: {prompt[:120]}...")

        # Step 1: Create
        result = await self.create_image(
            prompt=prompt,
            ai_model=ai_model,
            aspect_ratio=aspect_ratio,
        )
        task_id = result["result"]
        logger.info(f"[{name}] Image task ID: {task_id}")

        # Step 2: Poll
        task = await self.poll_image_task(task_id)

        # Step 3: Download
        image_urls = task.get("image_urls", [])
        for i, url in enumerate(image_urls):
            suffix = f"_{i}" if len(image_urls) > 1 else ""
            dest = output_dir / f"{name}{suffix}.png"
            await self.download_image(url, dest)

        meta = {
            "name": name,
            "prompt": prompt,
            "task_id": task_id,
            "ai_model": ai_model,
            "aspect_ratio": aspect_ratio,
            "image_urls": image_urls,
            "consumed_credits": task.get("consumed_credits", 0),
        }
        (output_dir / f"{name}_metadata.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False)
        )

        logger.info(f"[{name}] Image done! Credits: {meta['consumed_credits']}")
        return meta
