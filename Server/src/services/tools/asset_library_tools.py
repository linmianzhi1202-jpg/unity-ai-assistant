"""MCP tools for the external Unity asset knowledge library."""

from __future__ import annotations
from services.tools.tool_router import get_router

import asyncio
import json
import logging
import math
import time
from typing import Any

from fastmcp import FastMCP

from services.asset_library_service import (
    COLLECTION_NAME,
    DEFAULT_INDEX_DIR,
    DEFAULT_LIBRARY_ROOT,
    active_asset_collection_name,
    get_asset_record,
    import_asset_to_project,
    index_asset_library,
    load_asset_index_state,
    load_asset_records,
    search_asset_library,
    validate_asset_library,
)
from services.asset_graph_service import (
    apply_asset_relation_changes,
    build_asset_graph,
    get_asset_relations,
    list_manual_asset_relations,
    preview_asset_relation_changes,
)
from services.asset_scene_plan_service import (
    build_asset_scene_preview,
    get_asset_scene_plan_store,
)
from services.asset_library_export_service import (
    apply_asset_export_plan,
    build_asset_export_preview,
    get_asset_export_plan_store,
)
from services.adaptation_task_service import get_adapt_task_manager
from services.tools.tool_group_map import make_group_tags
from services.tools.unity_bridge import get_bridge, send_to_unity

logger = logging.getLogger(__name__)


def _parse_vector3(value: str, field_name: str) -> dict[str, float] | None:
    """Parse an optional comma-separated finite Vector3."""
    if not value or not value.strip():
        return None
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ValueError(f"{field_name} must contain exactly 3 comma-separated values")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"{field_name} must contain numeric values") from exc
    if not all(math.isfinite(number) for number in numbers):
        raise ValueError(f"{field_name} values must be finite")
    return {"x": numbers[0], "y": numbers[1], "z": numbers[2]}


def _manifest_scale(asset: dict[str, Any]) -> dict[str, float] | None:
    value = asset.get("defaultScale")
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Asset defaultScale must contain exactly 3 values")
    try:
        numbers = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ValueError("Asset defaultScale must contain numeric values") from exc
    if not all(math.isfinite(number) and number > 0 for number in numbers):
        raise ValueError("Asset defaultScale values must be finite and positive")
    return {"x": numbers[0], "y": numbers[1], "z": numbers[2]}


def _manifest_float(
    asset: dict[str, Any],
    key: str,
    default: float,
) -> float:
    value = float(asset.get(key, default))
    if not math.isfinite(value):
        raise ValueError(f"Asset {key} must be finite")
    return value


async def _active_project_path(explicit_path: str = "") -> str:
    project_path = explicit_path.strip()
    if project_path:
        return project_path
    info = await get_bridge().get_unity_info()
    return str(info.get("project_path") or info.get("assets_path") or "")


def register_asset_library_tools(mcp: FastMCP) -> None:
    """Register external asset knowledge-library tools."""
    group = "rag"

    @mcp.tool(tags=make_group_tags(group))
    def asset_library_index(
        action: str = "status",
        rebuild: bool = False,
        embedding_provider: str = "bge-m3",
    ) -> dict[str, Any]:
        """Inspect or rebuild the external Unity asset semantic index.

        Args:
            action: "status", "validate", "index", or "graph".
            rebuild: Delete and recreate the dedicated collection before indexing.
            embedding_provider: "bge-m3" (recommended) or "local-hash".
        """
        try:
            if action == "status":
                records = load_asset_records()
                indexed_count = 0
                index_error = None
                try:
                    import chromadb

                    collection_name = active_asset_collection_name(DEFAULT_INDEX_DIR)
                    collection = chromadb.PersistentClient(
                        path=str(DEFAULT_INDEX_DIR)
                    ).get_collection(collection_name)
                    indexed_count = collection.count()
                except Exception as exc:
                    index_error = str(exc)
                return {
                    "success": True,
                    "collection": active_asset_collection_name(DEFAULT_INDEX_DIR),
                    "index_state": load_asset_index_state(DEFAULT_INDEX_DIR),
                    "library_root": str(DEFAULT_LIBRARY_ROOT.resolve()),
                    "manifest_count": len(records),
                    "indexed_count": indexed_count,
                    "index_error": index_error,
                    "assets": [
                        {
                            "asset_id": record.asset_id,
                            "display_name": record.data.get("displayName", ""),
                            "category": record.data.get("category", ""),
                        }
                        for record in records
                    ],
                }
            if action == "index":
                return index_asset_library(
                    rebuild=rebuild,
                    embedding_provider=embedding_provider,
                    progress=logger.info,
                )
            if action == "validate":
                return validate_asset_library()
            if action == "graph":
                return build_asset_graph()
            return {
                "success": False,
                "error": "action must be 'status', 'validate', 'index', or 'graph'",
            }
        except Exception as exc:
            logger.exception("Asset library indexing failed")
            return {"success": False, "error": str(exc)}

    @mcp.tool(name="search_asset_library", tags=make_group_tags(group))
    def search_asset_library_tool(
        query: str,
        category: str = "",
        top_k: int = 5,
        filters_json: str = "",
        expand_relations: bool = False,
        diversify_variants: bool = False,
        candidate_count: int = 30,
    ) -> dict[str, Any]:
        """Search reusable external Unity assets by natural-language description.

        Returns asset IDs, Prefab metadata, dimensions, tags, and source paths.

        Args:
            query: Natural-language request, such as "古代书生" or "一匹坐骑".
            category: Optional category filter, such as character or animal.
            top_k: Maximum number of results, from 1 to 20.
            filters_json: Optional JSON filters for tags, colors, sizeClass,
                bounds, assetIds, or excludeAssetIds.
            expand_relations: Add related assets from the lightweight graph.
            diversify_variants: Prefer distinct variant groups before repeats.
            candidate_count: Vector candidate pool, from 5 to 100.
        """
        try:
            filters: dict[str, Any] = {}
            if filters_json.strip():
                parsed = json.loads(filters_json)
                if not isinstance(parsed, dict):
                    raise ValueError("filters_json must be a JSON object")
                filters = parsed
            return search_asset_library(
                query=query,
                category=category,
                top_k=max(1, min(top_k, 20)),
                filters=filters,
                expand_relations=expand_relations,
                diversify_variants=diversify_variants,
                candidate_count=max(5, min(int(candidate_count), 100)),
            )
        except Exception as exc:
            logger.exception("Asset library search failed")
            return {"success": False, "query": query, "error": str(exc)}

    @mcp.tool(name="get_asset_relations", tags=make_group_tags(group))
    def get_asset_relations_tool(
        asset_id: str,
        relation_types: list[str] | None = None,
        depth: int = 1,
        origins: list[str] | None = None,
        include_constraints: bool = False,
        direction: str = "outgoing",
    ) -> dict[str, Any]:
        """Query asset relations and optionally compile placement constraints.

        Use origins=["manual"] to inspect curated knowledge. Set
        include_constraints=true when planning placement; faces and
        avoid_overlap are constraints only and never positive retrieval links.
        Direction accepts outgoing, incoming, or both.
        """
        try:
            return get_asset_relations(
                asset_id,
                relation_types=relation_types,
                depth=max(1, min(int(depth), 3)),
                origins=origins,
                include_constraints=include_constraints,
                direction=direction,
            )
        except Exception as exc:
            logger.exception("Asset relation search failed")
            return {"success": False, "asset_id": asset_id, "error": str(exc)}

    @mcp.tool(name="list_manual_asset_relations", tags=make_group_tags(group))
    def list_manual_asset_relations_tool(
        asset_id: str = "",
        relation_type: str = "",
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """List the centralized manual relation overlay.

        Results include endpoint expansion, invalid endpoints, direction,
        weights, spatial parameters, and retrieval/constraint eligibility.
        """
        try:
            return list_manual_asset_relations(
                asset_id=asset_id.strip(),
                relation_type=relation_type.strip(),
                enabled=enabled,
            )
        except Exception as exc:
            logger.exception("Manual asset relation listing failed")
            return {"success": False, "error": str(exc)}

    @mcp.tool(name="preview_asset_relation_changes", tags=make_group_tags(group))
    def preview_asset_relation_changes_tool(changes_json: str) -> dict[str, Any]:
        """Preview manual relation upsert/delete/enable/disable operations.

        changes_json is an array (or {"changes": [...]}) whose entries contain
        op. Upsert entries also contain relation with source and target
        endpoints ({"assetId": ...} or {"variantGroup": ...}), type, weight,
        optional bidirectional/note, and optional spatial minDistance,
        maxDistance, or yawOffset. This tool never writes files or the graph.
        """
        try:
            parsed = json.loads(changes_json)
            changes = parsed.get("changes", []) if isinstance(parsed, dict) else parsed
            if not isinstance(changes, list):
                raise ValueError("changes_json must be an array or an object with changes")
            return preview_asset_relation_changes(
                [dict(item) for item in changes if isinstance(item, dict)]
            )
        except Exception as exc:
            logger.exception("Manual asset relation preview failed")
            return {"success": False, "status": "error", "error": str(exc)}

    @mcp.tool(name="apply_asset_relation_changes", tags=make_group_tags(group))
    def apply_asset_relation_changes_tool(plan_id: str) -> dict[str, Any]:
        """Atomically apply a previewed manual relation plan and rebuild the graph.

        Call preview_asset_relation_changes first. Stale plans are rejected;
        relation and generated graph files are both restored if rebuilding fails.
        """
        try:
            return apply_asset_relation_changes(plan_id.strip())
        except Exception as exc:
            logger.exception("Manual asset relation apply failed")
            return {"success": False, "status": "error", "plan_id": plan_id, "error": str(exc)}

    @mcp.tool(tags=make_group_tags(group))
    async def preview_asset_scene_plan(
        intent: str,
        reference_object: str = "",
        region_center: str = "",
        region_size: str = "",
        max_assets: int = 20,
        density: str = "medium",
        constraints_json: str = "",
    ) -> dict[str, Any]:
        """Create a read-only multi-asset scene plan from natural language.

        The tool decomposes the request into roles, uses recipes and the asset
        graph to select Prefabs, then places surface providers before occupants,
        roadside decoration, and background assets. Placements include support,
        zone, grounding-group, contact, slope, and forbidden-zone evidence. It
        does not import assets or modify the active Unity scene.
        """
        try:
            constraints: dict[str, Any] = {}
            if constraints_json.strip():
                parsed = json.loads(constraints_json)
                if not isinstance(parsed, dict):
                    raise ValueError("constraints_json must be a JSON object")
                constraints = parsed
            center = _parse_vector3(region_center, "region_center")
            size = _parse_vector3(region_size, "region_size")
            context_response = await get_router().send_tool('preview_asset_scene_plan', {'reference_path': reference_object.strip(), 'region_center': center, 'region_size': size, 'intent': intent})
            if context_response.get("status") != "success":
                return {
                    "success": False,
                    "status": "error",
                    "error": context_response.get(
                        "error", "Unity scene analysis failed"
                    ),
                    "unity": context_response,
                }
            scene_context = context_response.get("result", context_response)
            return build_asset_scene_preview(
                intent=intent,
                scene_context=scene_context,
                reference_object=reference_object.strip(),
                region_center=center,
                region_size=size,
                max_assets=max_assets,
                density=density,
                constraints=constraints,
            )
        except Exception as exc:
            logger.exception("Asset scene preview failed")
            return {"success": False, "status": "error", "error": str(exc)}

    @mcp.tool(tags=make_group_tags(group))
    async def apply_asset_scene_plan(
        plan_id: str,
        auto_save: bool = False,
        destination_folder: str = "Assets/AIAssetLibrary",
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Apply a confirmed multi-asset preview as one background task."""
        plan = get_asset_scene_plan_store().get(plan_id)
        if not plan:
            return {
                "success": False,
                "error_code": "plan_not_found",
                "error": "Asset scene plan was not found or has expired.",
            }
        if not plan.get("can_apply"):
            return {
                "success": False,
                "error_code": "plan_blocked",
                "error": "Asset scene plan contains blocking issues.",
                "preview": plan,
            }

        manager = get_adapt_task_manager()

        async def run_scene_plan(task) -> dict[str, Any]:
            task.update(status="running", phase="verify_scene", progress=0.05)
            context_response = await send_to_unity(
                "manage_gameobject",
                {
                    "action": "analyze_scene_placement_context",
                    "reference_path": plan.get("reference_object") or "",
                    "region_center": plan.get("region_center"),
                    "region_size": plan.get("region_size"),
                },
            )
            if context_response.get("status") != "success":
                raise RuntimeError(
                    context_response.get("error", "Unity scene analysis failed")
                )
            current_context = context_response.get("result", context_response)
            if (
                plan.get("scene_token")
                and current_context.get("scene_token") != plan.get("scene_token")
            ):
                raise RuntimeError("Unity scene changed after preview; preview again")

            project_path = await _active_project_path()
            if not project_path:
                raise RuntimeError("Could not determine the active Unity project path")
            task.update(phase="import_assets", progress=0.2)
            imported: dict[str, dict[str, Any]] = {}
            changed_imports: list[str] = []
            placements = plan.get("placements", [])
            unique_asset_ids = list(
                dict.fromkeys(
                    str(item.get("asset_id")) for item in placements
                    if item.get("asset_id")
                )
            )
            for asset_id in unique_asset_ids:
                result = await asyncio.to_thread(
                    import_asset_to_project,
                    asset_id,
                    project_path,
                    destination_folder,
                    overwrite,
                )
                imported[asset_id] = result
                if result.get("changed"):
                    changed_imports.append(result["target_asset_path"])

            if changed_imports:
                task.update(phase="refresh_assets", progress=0.45)
                for asset_path in changed_imports:
                    await send_to_unity(
                        "manage_asset",
                        {"action": "import_asset", "asset_path": asset_path},
                    )

            batch: list[dict[str, Any]] = []
            for placement in placements:
                asset_id = str(placement["asset_id"])
                selected = get_asset_record(asset_id).public_dict()
                item = {
                    **placement,
                    "prefab_path": imported[asset_id]["prefab_asset_path"],
                    "name": placement.get("display_name") or asset_id,
                    "ground_offset": _manifest_float(
                        selected, "groundOffset", 0.0
                    ),
                    "forward_axis": selected.get("forwardAxis", "+Z"),
                }
                scale = _manifest_scale(selected)
                if scale is not None:
                    item["scale"] = scale
                batch.append(item)

            task.update(phase="place_assets", progress=0.65)
            placement_response = await send_to_unity(
                "manage_gameobject",
                {
                    "action": "place_prefab_batch_smart",
                    "scene_token": plan.get("scene_token"),
                    "placements": batch,
                    "region_center": plan.get("region_center"),
                    "region_size": plan.get("region_size"),
                },
            )
            if placement_response.get("status") != "success":
                raise RuntimeError(
                    placement_response.get("error", "Unity batch placement failed")
                )

            save_response = None
            if auto_save:
                task.update(phase="save_scene", progress=0.92)
                save_response = await send_to_unity(
                    "manage_scene", {"action": "save"}
                )
                if save_response.get("status") != "success":
                    raise RuntimeError(
                        save_response.get("error", "Scene save failed")
                    )
            return {
                "success": True,
                "status": "applied",
                "plan_id": plan_id,
                "recipe_id": plan.get("recipe_id"),
                "asset_count": len(batch),
                "imports": imported,
                "placement": placement_response.get("result", {}),
                "scene_saved": auto_save,
                "save": save_response,
            }

        task = manager.start(
            request={
                "plan_id": plan_id,
                "recipe_id": plan.get("recipe_id"),
                "asset_count": plan.get("asset_count"),
            },
            runner_factory=run_scene_plan,
            task_type="asset_scene_plan",
        )
        return {
            "success": True,
            "status": task.status,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "next_action": "Poll get_task_status until completed or failed.",
        }

    @mcp.tool(tags=make_group_tags(group))
    async def preview_asset_library_export(
        bundle_name: str,
        source_mode: str = "selection",
        source_paths: list[str] | None = None,
        category: str = "environment",
        intent: str = "",
        metadata_overrides_json: str = "",
        recursive: bool = True,
    ) -> dict[str, Any]:
        """Preview extracting Unity Prefabs and visual dependencies into the library.

        This is the first, read-only step of the export workflow. It resolves
        Prefab assets from the current Unity selection, explicit paths, or folders;
        analyzes models, materials, textures, animations, shaders, GUIDs, bounds,
        Pivot/contact geometry, Collider support, surface zones, script blockers,
        size, and generated knowledge metadata. It does not write files or update
        the index. After reviewing a successful preview, call
        apply_asset_library_export(plan_id), then poll get_task_status(task_id).

        Args:
            bundle_name: Shared asset bundle display/folder name.
            source_mode: selection, paths, or folder.
            source_paths: Prefab/folder paths under Assets for paths/folder mode.
            category: Knowledge category, such as environment or prop.
            intent: Natural-language usage description used by metadata fallback.
            metadata_overrides_json: Optional JSON object keyed by Prefab path,
                source GUID, or Prefab name. Values may provide id, displayName,
                tags, aliases, description, useCases, variantGroup, variantColor,
                modelPath, materialPath, groundOffset, forwardAxis,
                semanticAttributes, placementProfile, and relations.
            recursive: Recursively scan Prefab folders.
        """
        try:
            overrides: dict[str, Any] = {}
            if metadata_overrides_json.strip():
                parsed = json.loads(metadata_overrides_json)
                if not isinstance(parsed, dict):
                    raise ValueError("metadata_overrides_json must be a JSON object")
                overrides = parsed
            unity_response = await get_router().send_tool('preview_asset_library_export', {'source_mode': source_mode, 'source_paths': source_paths or [], 'recursive': recursive})
            if unity_response.get("status") != "success":
                return {
                    "success": False,
                    "status": "error",
                    "error": unity_response.get(
                        "error", "Unity dependency analysis failed"
                    ),
                    "unity": unity_response,
                }
            analysis = unity_response.get("result", unity_response)
            preview = build_asset_export_preview(
                unity_analysis=analysis,
                bundle_name=bundle_name,
                category=category,
                intent=intent,
                metadata_overrides=overrides,
            )
            preview["success"] = True
            return preview
        except Exception as exc:
            logger.exception("Asset library export preview failed")
            return {
                "success": False,
                "status": "error",
                "error": str(exc),
            }

    @mcp.tool(tags=make_group_tags(group))
    async def apply_asset_library_export(plan_id: str) -> dict[str, Any]:
        """Apply a confirmed asset-library export preview as a background task.

        The task verifies that source files did not change, copies shared visual
        dependencies into staging, remaps GUIDs deterministically, writes one
        searchable manifest per Prefab, validates and atomically publishes the
        bundle, then incrementally updates the semantic index. Poll the returned
        task_id with get_task_status until completed or failed.
        """
        plan = get_asset_export_plan_store().get(plan_id)
        if not plan:
            return {
                "success": False,
                "error_code": "plan_not_found",
                "error": "Asset export plan was not found or has expired.",
            }
        if not plan.get("can_export"):
            return {
                "success": False,
                "error_code": "plan_blocked",
                "error": "Asset export preview contains blocking issues.",
                "preview": plan,
            }

        manager = get_adapt_task_manager()

        async def run_export(task) -> dict[str, Any]:
            def update(phase: str, progress: float) -> None:
                task.update(
                    status="running",
                    phase=phase,
                    progress=progress,
                )

            return await asyncio.to_thread(
                apply_asset_export_plan,
                plan_id,
                update,
            )

        task = manager.start(
            request={
                "plan_id": plan_id,
                "bundle_id": plan.get("bundle_id"),
                "bundle_name": plan.get("bundle_name"),
                "asset_count": plan.get("prefab_count"),
            },
            runner_factory=run_export,
            task_type="asset_library_export",
        )
        return {
            "success": True,
            "status": task.status,
            "task_id": task.task_id,
            "task_type": task.task_type,
            "phase": task.phase,
            "progress": task.progress,
            "next_action": (
                "Poll get_task_status with task_id until status is completed "
                "or failed."
            ),
        }

    @mcp.tool(tags=make_group_tags(group))
    async def import_asset_from_library(
        asset_id: str,
        destination_folder: str = "Assets/AIAssetLibrary",
        unity_project_root: str = "",
        overwrite: bool = False,
        refresh: bool = True,
    ) -> dict[str, Any]:
        """Copy a library asset and all dependencies into the active Unity project.

        The complete asset folder is copied with its .meta files so Prefab, FBX,
        material, and texture GUID references remain valid.

        Args:
            asset_id: Stable ID returned by search_asset_library.
            destination_folder: Project-relative destination starting with Assets.
            unity_project_root: Optional explicit Unity project or Assets path.
            overwrite: Update files if the same asset has already been imported.
            refresh: Refresh Unity's AssetDatabase after copying.
        """
        try:
            project_path = await _active_project_path(unity_project_root)
            if not project_path:
                return {
                    "success": False,
                    "error": "Could not determine the active Unity project path",
                }

            result = import_asset_to_project(
                asset_id=asset_id,
                unity_project_root=project_path,
                destination_folder=destination_folder,
                overwrite=overwrite,
            )
            if refresh:
                if not result.get("changed", False):
                    result["unity_refresh"] = False
                    result["refresh_skipped"] = True
                    return result
                try:
                    unity_result = await send_to_unity(
                        "manage_asset",
                        {
                            "action": "import_asset",
                            "asset_path": result["target_asset_path"],
                        },
                    )
                    result["unity_refresh"] = (
                        unity_result.get("status") == "success"
                    )
                    result["targeted_import"] = result["unity_refresh"]
                    if not result["unity_refresh"]:
                        fallback = await send_to_unity(
                            "manage_editor",
                            {"action": "refresh", "force": False},
                        )
                        result["unity_refresh"] = (
                            fallback.get("status") == "success"
                        )
                        result["refresh_fallback"] = fallback
                except ConnectionError as exc:
                    result["unity_refresh"] = True
                    result["refresh_message"] = (
                        "Unity reloaded the connection while importing: "
                        f"{exc}"
                    )
            return result
        except Exception as exc:
            logger.exception("Asset library import failed")
            return {"success": False, "asset_id": asset_id, "error": str(exc)}

    @mcp.tool(tags=make_group_tags(group))
    async def place_asset_from_library(
        query: str,
        category: str = "",
        reference_object: str = "",
        relation: str = "near",
        distance: float = 2.0,
        position: str = "",
        rotation: str = "",
        ground_snap: bool = True,
        avoid_collisions: bool = True,
        face_reference: bool = False,
        destination_folder: str = "Assets/AIAssetLibrary",
        overwrite: bool = False,
        auto_save: bool = False,
        max_attempts: int = 12,
        minimum_confidence: float = 0.55,
    ) -> dict[str, Any]:
        """Find, import, and intelligently place one external library asset.

        Args:
            query: Natural-language asset request, such as "古代书生".
            category: Optional asset category filter.
            reference_object: Optional scene hierarchy path used as the anchor.
            relation: near, left, right, front, behind, or on.
            distance: Desired edge-to-edge spacing in Unity world units.
            position: Optional explicit x,y,z position, overriding relative placement.
            rotation: Optional x,y,z Euler rotation.
            ground_snap: Snap the asset's lower bounds to scene geometry.
            avoid_collisions: Search nearby candidates until bounds do not overlap.
            face_reference: Rotate the placed asset horizontally toward the anchor.
            destination_folder: Project-relative asset import root.
            overwrite: Replace an older imported version when source content changed.
            auto_save: Save the active scene only after successful placement.
            max_attempts: Maximum placement candidates, from 1 to 36.
            minimum_confidence: Refuse ambiguous Top-1 results below this value.
        """
        started = time.perf_counter()
        timings: dict[str, float] = {}
        try:
            normalized_relation = relation.strip().lower()
            allowed_relations = {
                "near", "left", "right", "front", "behind", "on"
            }
            if normalized_relation not in allowed_relations:
                raise ValueError(
                    "relation must be near, left, right, front, behind, or on"
                )
            if not math.isfinite(distance) or distance < 0:
                raise ValueError("distance must be finite and non-negative")

            explicit_position = _parse_vector3(position, "position")
            explicit_rotation = _parse_vector3(rotation, "rotation")

            phase_started = time.perf_counter()
            search_result = search_asset_library(
                query=query,
                category=category,
                top_k=3,
            )
            timings["search_ms"] = round(
                (time.perf_counter() - phase_started) * 1000, 2
            )
            results = search_result.get("results", [])
            if not results:
                return {
                    "success": False,
                    "query": query,
                    "error": "No matching asset found",
                    "search": search_result,
                    "timings_ms": timings,
                }
            selected = results[0]
            if float(selected.get("confidence", 0.0)) < max(
                0.0, min(float(minimum_confidence), 1.0)
            ):
                return {
                    "success": False,
                    "query": query,
                    "error_code": "ambiguous_asset_match",
                    "error": "Top asset match confidence is too low; review candidates.",
                    "candidates": results,
                    "search": search_result,
                    "timings_ms": timings,
                }

            phase_started = time.perf_counter()
            project_path = await _active_project_path()
            if not project_path:
                raise RuntimeError(
                    "Could not determine the active Unity project path"
                )
            import_result = import_asset_to_project(
                asset_id=str(selected["assetId"]),
                unity_project_root=project_path,
                destination_folder=destination_folder,
                overwrite=overwrite,
            )
            timings["import_ms"] = round(
                (time.perf_counter() - phase_started) * 1000, 2
            )

            changed = bool(
                import_result.get(
                    "changed",
                    not import_result.get("already_imported", False),
                )
            )
            refresh_result: dict[str, Any] | None = None
            if changed:
                phase_started = time.perf_counter()
                try:
                    refresh_result = await send_to_unity(
                        "manage_asset",
                        {
                            "action": "import_asset",
                            "asset_path": import_result["target_asset_path"],
                        },
                    )
                    if refresh_result.get("status") != "success":
                        refresh_result = await send_to_unity(
                            "manage_editor",
                            {"action": "refresh", "force": False},
                        )
                except ConnectionError as exc:
                    refresh_result = {
                        "status": "reload",
                        "message": str(exc),
                    }
                timings["refresh_ms"] = round(
                    (time.perf_counter() - phase_started) * 1000, 2
                )

            placement_args: dict[str, Any] = {
                "action": "place_prefab_smart",
                "prefab_path": import_result["prefab_asset_path"],
                "name": selected.get("displayName")
                or selected.get("assetId"),
                "reference_path": reference_object.strip(),
                "relation": normalized_relation,
                "distance": distance,
                "ground_snap": ground_snap,
                "avoid_collisions": avoid_collisions,
                "face_reference": face_reference,
                "max_attempts": max(1, min(int(max_attempts), 36)),
                "ground_offset": _manifest_float(
                    selected, "groundOffset", 0.0
                ),
                "forward_axis": str(selected.get("forwardAxis", "+Z")),
            }
            manifest_scale = _manifest_scale(selected)
            if manifest_scale is not None:
                placement_args["scale"] = manifest_scale
            if explicit_position is not None:
                placement_args["position"] = explicit_position
            if explicit_rotation is not None:
                placement_args["rotation"] = explicit_rotation

            phase_started = time.perf_counter()
            placement_response = await send_to_unity(
                "manage_gameobject",
                placement_args,
            )
            timings["placement_ms"] = round(
                (time.perf_counter() - phase_started) * 1000, 2
            )
            if placement_response.get("status") != "success":
                return {
                    "success": False,
                    "query": query,
                    "selected_asset": selected,
                    "import": import_result,
                    "refresh": refresh_result,
                    "placement": placement_response,
                    "error": placement_response.get(
                        "error", "Unity placement failed"
                    ),
                    "timings_ms": timings,
                }

            save_response: dict[str, Any] | None = None
            if auto_save:
                phase_started = time.perf_counter()
                save_response = await send_to_unity(
                    "manage_scene",
                    {"action": "save"},
                )
                timings["save_ms"] = round(
                    (time.perf_counter() - phase_started) * 1000, 2
                )
                if save_response.get("status") != "success":
                    return {
                        "success": False,
                        "query": query,
                        "selected_asset": selected,
                        "import": import_result,
                        "refresh": refresh_result,
                        "placement": placement_response.get("result", {}),
                        "save": save_response,
                        "error": save_response.get(
                            "error", "Asset was placed but scene save failed"
                        ),
                        "timings_ms": timings,
                    }

            timings["total_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            return {
                "success": True,
                "query": query,
                "selected_asset": {
                    "asset_id": selected.get("assetId"),
                    "display_name": selected.get("displayName"),
                    "category": selected.get("category"),
                    "score": selected.get("score"),
                },
                "import": import_result,
                "refresh": refresh_result,
                "placement": placement_response.get("result", {}),
                "scene_saved": auto_save,
                "save": save_response,
                "timings_ms": timings,
            }
        except Exception as exc:
            logger.exception("Asset library placement failed")
            timings["total_ms"] = round(
                (time.perf_counter() - started) * 1000, 2
            )
            return {
                "success": False,
                "query": query,
                "error": str(exc),
                "timings_ms": timings,
            }
