"""Read-only multi-asset scene planning backed by recipes and hybrid search."""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from services.asset_graph_service import (
    CONSTRAINT_RELATION_TYPES,
    DEFAULT_RECIPES_PATH,
    RETRIEVAL_RELATION_TYPES,
    get_asset_relations,
    load_scene_recipes,
)
from services.asset_library_service import (
    DEFAULT_LIBRARY_ROOT,
    AssetRecord,
    get_asset_record,
    load_asset_records,
    search_asset_library,
)


PLAN_TTL_SECONDS = 1800.0


class AssetScenePlanStore:
    def __init__(self, ttl_seconds: float = PLAN_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._plans: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, plan: dict[str, Any]) -> str:
        now = time.time()
        plan_id = uuid.uuid4().hex
        payload = dict(plan)
        payload.update(
            {"plan_id": plan_id, "created_at": now, "expires_at": now + self.ttl_seconds}
        )
        with self._lock:
            self._cleanup_locked(now)
            self._plans[plan_id] = payload
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_locked(time.time())
            plan = self._plans.get(plan_id)
            return dict(plan) if plan else None

    def _cleanup_locked(self, now: float) -> None:
        for plan_id in [
            key for key, value in self._plans.items()
            if float(value.get("expires_at", 0.0)) <= now
        ]:
            self._plans.pop(plan_id, None)


_PLAN_STORE = AssetScenePlanStore()


def get_asset_scene_plan_store() -> AssetScenePlanStore:
    return _PLAN_STORE


def _recipe_score(intent: str, recipe: dict[str, Any]) -> float:
    normalized = intent.lower()
    keywords = [str(item).lower() for item in recipe.get("keywords", [])]
    matched = [keyword for keyword in keywords if keyword and keyword in normalized]
    if not matched:
        return 0.0
    longest = max(len(item) for item in matched)
    return len(matched) * 10.0 + longest


def _local_llm_roles(intent: str) -> list[dict[str, Any]]:
    model = os.environ.get("UNITY_ASSET_PLANNER_MODEL", "qwen2.5-coder:7b")
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    prompt = (
        "把 Unity 场景描述拆成需要检索的资产角色。只输出 JSON，格式为 "
        '{"roles":[{"query":"资产描述","count":1,"relation":"near"}]}。'
        "relation 只能是 near,left,right,front,behind,on。不要输出解释。\n"
        f"用户描述：{intent}"
    )
    payload = json.dumps(
        {"model": model, "prompt": prompt, "stream": False, "format": "json"}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=12.0) as response:
            outer = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(str(outer.get("response", "{}")))
        roles = parsed.get("roles", [])
        return [dict(role) for role in roles if isinstance(role, dict)]
    except Exception:
        return []


def _scene_object_match(
    role: dict[str, Any],
    asset_ids: list[str],
    scene_context: dict[str, Any],
    library_root: Path | str,
    records_by_id: dict[str, AssetRecord] | None = None,
) -> dict[str, Any] | None:
    if not role.get("existingPreferred"):
        return None
    terms: set[str] = set()
    for asset_id in asset_ids:
        record = (records_by_id or {}).get(asset_id)
        if record is None:
            try:
                record = get_asset_record(asset_id, library_root)
            except KeyError:
                continue
        if record is None:
            continue
        terms.add(str(record.data.get("displayName", "")).lower())
        terms.update(str(item).lower() for item in record.data.get("aliases", []))
    for obj in scene_context.get("objects", []):
        name = str(obj.get("name", "")).lower()
        path = str(obj.get("path", "")).lower()
        if any(term and (term in name or term in path) for term in terms):
            return obj
    return None


def _select_asset(
    role: dict[str, Any],
    index: int,
    library_root: Path | str,
    records_by_id: dict[str, AssetRecord] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    explicit = [str(item) for item in role.get("assetIds", []) if str(item)]
    if explicit:
        valid: list[dict[str, Any]] = []
        for asset_id in explicit:
            record = (records_by_id or {}).get(asset_id)
            if record is None:
                try:
                    record = get_asset_record(asset_id, library_root)
                except KeyError:
                    continue
            if record is None:
                continue
            valid.append(record.public_dict())
        if not valid:
            return None, []
        selected = valid[index % len(valid)]
        return selected, valid[:5]
    query = str(role.get("query", "")).strip()
    result = search_asset_library(
        query,
        category=str(role.get("category", "")),
        top_k=5,
        expand_relations=False,
        diversify_variants=True,
    )
    alternatives = result.get("results", [])
    return (alternatives[index % len(alternatives)] if alternatives else None), alternatives


def _vector(value: Any, default: tuple[float, float, float]) -> tuple[float, float, float]:
    if isinstance(value, dict):
        raw = [value.get(axis) for axis in "xyz"]
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        raw = list(value)
    else:
        return default
    try:
        result = tuple(float(item) for item in raw)
    except (TypeError, ValueError):
        return default
    return result if all(math.isfinite(item) for item in result) else default


def _preview_position(
    placement_index: int,
    relation: str,
    distance: float,
    layout: str,
    center: tuple[float, float, float],
) -> dict[str, float]:
    x, y, z = center
    if layout == "pair_line":
        pair = placement_index // 2
        side = -1.0 if placement_index % 2 == 0 else 1.0
        return {"x": x + side * distance, "y": y, "z": z + pair * distance * 2.0}
    if layout == "pair":
        side = -1.0 if placement_index % 2 == 0 else 1.0
        return {"x": x + side * distance, "y": y, "z": z}
    if layout == "scatter":
        angle = math.radians(placement_index * 137.5)
        radius = max(0.5, distance) * (1.0 + placement_index * 0.35)
        return {"x": x + math.cos(angle) * radius, "y": y, "z": z + math.sin(angle) * radius}
    offsets = {
        "left": (-distance, 0.0),
        "right": (distance, 0.0),
        "front": (0.0, distance),
        "behind": (0.0, -distance),
        "near": (distance, 0.0),
        "on": (0.0, 0.0),
    }
    dx, dz = offsets.get(relation, (distance, 0.0))
    return {"x": x + dx, "y": y, "z": z + dz}


def _asset_min_spacing(
    asset_id: str,
    library_root: Path | str,
    records_by_id: dict[str, AssetRecord] | None = None,
) -> float:
    try:
        record = (records_by_id or {}).get(asset_id)
        if record is None:
            record = get_asset_record(asset_id, library_root)
        value = record.data.get("placementProfile", {}).get("minSpacing", 0.0)
        return max(0.0, float(value))
    except (KeyError, TypeError, ValueError):
        return 0.0


def _append_manual_companions(
    placements: list[dict[str, Any]],
    asset_limit: int,
    center: tuple[float, float, float],
    library_root: Path | str,
    records_by_id: dict[str, AssetRecord] | None = None,
) -> list[dict[str, Any]]:
    """Add only explicit manual companion knowledge, never constraint-only edges."""
    existing_ids = {str(item.get("asset_id", "")) for item in placements}
    companions: list[dict[str, Any]] = []
    for source in list(placements):
        if len(placements) + len(companions) >= asset_limit:
            break
        source_id = str(source.get("asset_id", ""))
        if not source_id:
            continue
        try:
            related = get_asset_relations(
                source_id,
                relation_types=RETRIEVAL_RELATION_TYPES,
                depth=1,
                origins={"manual"},
                direction="outgoing",
                library_root=library_root,
            )
        except (KeyError, ValueError):
            continue
        for edge in related.get("relations", []):
            target_id = str(edge.get("target", ""))
            target_node = edge.get("targetNode") or {}
            if (
                not target_id
                or target_id in existing_ids
                or target_id.startswith(("bundle:", "variant:", "recipe:"))
                or target_node.get("type") != "asset"
            ):
                continue
            record = (records_by_id or {}).get(target_id)
            if record is None:
                try:
                    record = get_asset_record(target_id, library_root)
                except KeyError:
                    continue
            if record is None:
                continue
            selected = record.public_dict()
            metadata = edge.get("metadata", {}) if isinstance(edge.get("metadata"), dict) else {}
            relation_type = str(edge.get("type", "pairs_with"))
            relation = "on" if relation_type == "placed_on" else "near"
            layout = "line" if relation_type == "lines_path" else "single"
            distance = max(0.0, float(metadata.get("minDistance", 2.0)))
            alias = f"graph-companion-{len(companions) + 1}"
            companion = {
                "alias": alias,
                "role": "graph-companion",
                "asset_id": target_id,
                "display_name": selected.get("displayName"),
                "required": False,
                "reference": f"@{source['alias']}",
                "relation": relation,
                "distance": distance,
                "layout": layout,
                "layout_index": len(companions),
                "ground_snap": True,
                "avoid_collisions": True,
                "face_reference": False,
                "minimum_clearance": 0.0,
                "preview_position": _preview_position(
                    len(companions), relation, distance, layout, center
                ),
                "alternatives": [],
                "relationEvidence": [],
                "compiledConstraints": [],
                "added_by_relation": {
                    "source": source_id,
                    "type": relation_type,
                    "origin": edge.get("origin"),
                },
            }
            companions.append(companion)
            existing_ids.add(target_id)
            break
    placements.extend(companions)
    return companions


def _compile_selected_relations(
    placements: list[dict[str, Any]],
    library_root: Path | str,
    records_by_id: dict[str, AssetRecord] | None = None,
) -> None:
    by_asset: dict[str, list[dict[str, Any]]] = {}
    for placement in placements:
        placement.setdefault("relationEvidence", [])
        placement.setdefault("compiledConstraints", [])
        placement.setdefault("minimum_clearance", 0.0)
        by_asset.setdefault(str(placement.get("asset_id", "")), []).append(placement)

    allowed_types = RETRIEVAL_RELATION_TYPES | CONSTRAINT_RELATION_TYPES
    spacing = {
        asset_id: _asset_min_spacing(asset_id, library_root, records_by_id)
        for asset_id in by_asset
        if asset_id
    }
    placement_order = {id(item): index for index, item in enumerate(placements)}
    for source in placements:
        source_id = str(source.get("asset_id", ""))
        if not source_id:
            continue
        try:
            related = get_asset_relations(
                source_id,
                relation_types=allowed_types,
                depth=1,
                include_constraints=True,
                direction="outgoing",
                library_root=library_root,
            )
        except (KeyError, ValueError):
            continue
        seen: set[tuple[str, str, str]] = set()
        for edge in related.get("relations", []):
            target_id = str(edge.get("target", ""))
            targets = by_asset.get(target_id, [])
            if not targets:
                continue
            for target in targets:
                if target is source:
                    continue
                relation_type = str(edge.get("type", ""))
                evidence_key = (source_id, target_id, relation_type)
                if evidence_key in seen:
                    continue
                seen.add(evidence_key)
                evidence = {
                    "sourceAssetId": source_id,
                    "targetAssetId": target_id,
                    "targetAlias": target.get("alias"),
                    "type": relation_type,
                    "origin": edge.get("origin"),
                    "weight": edge.get("weight"),
                    "retrievalEligible": bool(edge.get("retrievalEligible", False)),
                    "constraintEligible": bool(edge.get("constraintEligible", False)),
                }
                source["relationEvidence"].append(evidence)
                constraint = edge.get("compiledConstraint")
                if not isinstance(constraint, dict):
                    continue
                compiled = {
                    **constraint,
                    "targetAlias": target.get("alias"),
                    "origin": edge.get("origin"),
                }
                target_reference = f"@{target['alias']}"
                effective_spacing = max(
                    spacing.get(source_id, 0.0),
                    spacing.get(target_id, 0.0),
                    float(compiled.get("minimumClearance", 0.0) or 0.0),
                )
                compiled["effectiveMinimumClearance"] = effective_spacing
                source["compiledConstraints"].append(compiled)

                if relation_type == "avoid_overlap":
                    source["avoid_collisions"] = True
                    source["minimum_clearance"] = max(
                        float(source.get("minimum_clearance", 0.0)),
                        effective_spacing,
                    )
                elif relation_type == "faces":
                    source["reference"] = target_reference
                    source["face_reference"] = True
                elif relation_type == "placed_on":
                    source["reference"] = target_reference
                    source["relation"] = "on"
                elif relation_type == "lines_path":
                    source["reference"] = target_reference
                    source["layout"] = "line"
                    source["distance"] = max(
                        float(source.get("distance", 0.0)),
                        float(compiled.get("spacing", 0.0) or 0.0),
                        effective_spacing,
                    )
                elif (
                    relation_type == "placed_near"
                    and placement_order[id(target)] < placement_order[id(source)]
                ):
                    source["reference"] = target_reference
                    source["relation"] = "near"
                    source["distance"] = max(
                        float(source.get("distance", 0.0)),
                        float(compiled.get("minDistance", 0.0) or 0.0),
                        effective_spacing,
                    )


def _order_placements_by_dependencies(
    placements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    pending = list(placements)
    ordered: list[dict[str, Any]] = []
    available: set[str] = set()
    while pending:
        progressed = False
        for placement in list(pending):
            references = [
                str(placement.get("reference", "")),
                str(placement.get("supportReference", "")),
                str(placement.get("zoneReference", "")),
            ]
            unresolved = [
                value[1:]
                for value in references
                if value.startswith("@") and value[1:] not in available
            ]
            if not unresolved:
                pending.remove(placement)
                ordered.append(placement)
                available.add(str(placement.get("alias", "")))
                progressed = True
        if not progressed:
            ordered.extend(pending)
            return ordered, False
    return ordered, True


def _role_placement_priority(
    role: dict[str, Any],
    records_by_id: dict[str, AssetRecord],
) -> int:
    priorities = {"surface": 0, "occupant": 1, "roadside": 2, "background": 3, "obstacle": 4}
    for asset_id in role.get("assetIds", []):
        record = records_by_id.get(str(asset_id))
        if record is not None:
            profile = record.data.get("placementProfile", {})
            return priorities.get(str(profile.get("placementRole", "obstacle")), 4)
    terms = " ".join(
        str(role.get(key, "")) for key in ("id", "query", "category")
    ).lower()
    if any(term in terms for term in ("road", "道路", "bridge", "桥", "platform", "平台")):
        return 0
    if any(term in terms for term in ("character", "人物", "文人", "horse", "马", "mount")):
        return 1
    if any(term in terms for term in ("tree", "树", "lantern", "灯", "banner", "旗")):
        return 2
    if any(term in terms for term in ("cliff", "mountain", "山崖", "山体", "背景")):
        return 3
    return 4


def _semantic_placement_profile(
    asset_id: str,
    records_by_id: dict[str, AssetRecord],
) -> dict[str, Any]:
    record = records_by_id.get(asset_id)
    if record is None:
        return {}
    value = record.data.get("placementProfile", {})
    return dict(value) if isinstance(value, dict) else {}


def _existing_surface(scene_context: dict[str, Any], prefer_road: bool) -> dict[str, Any] | None:
    candidates = list(scene_context.get("surfaces", [])) or list(scene_context.get("grounds", []))
    if prefer_road:
        for candidate in candidates:
            if str(candidate.get("surface_type", "")).lower() == "road":
                return candidate
    return candidates[0] if candidates else None


def _expand_surface_coverage(
    placements: list[dict[str, Any]],
    records_by_id: dict[str, AssetRecord],
    center: tuple[float, float, float],
    size: tuple[float, float, float],
    asset_limit: int,
    constraints: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any] | None:
    """Tile a selected surface so its usable area covers the requested region."""
    if not bool(constraints.get("autoSurfaceTiling", True)):
        return None
    surfaces = [
        item
        for item in placements
        if _semantic_placement_profile(
            str(item.get("asset_id", "")), records_by_id
        ).get("placementRole") == "surface"
    ]
    if not surfaces:
        return None

    template = surfaces[0]
    profile = _semantic_placement_profile(
        str(template.get("asset_id", "")), records_by_id
    )
    geometry = profile.get("surfaceGeometry", {})
    geometry = geometry if isinstance(geometry, dict) else {}
    footprint = profile.get("footprint", {})
    footprint = footprint if isinstance(footprint, dict) else {}
    tile_width = max(
        0.0,
        float(geometry.get("effectiveWidth", footprint.get("x", 0.0)) or 0.0),
    )
    tile_length = max(
        0.0,
        float(geometry.get("effectiveLength", footprint.get("z", 0.0)) or 0.0),
    )
    if tile_width <= 0.01 or tile_length <= 0.01:
        warnings.append("Selected surface has no usable dimensions; automatic tiling was skipped")
        return None

    overlap = min(
        max(0.0, float(constraints.get("surfaceTileOverlap", 0.02) or 0.0)),
        min(tile_width, tile_length) * 0.25,
    )
    step_width = max(0.01, tile_width - overlap)
    step_length = max(0.01, tile_length - overlap)
    required_width = max(0.01, abs(float(size[0])))
    required_length = max(0.01, abs(float(size[2])))
    surface_type = str(profile.get("surfaceType", "ground")).lower()

    if surface_type in {"road", "bridge"}:
        columns = 1
        rows = max(1, 1 + math.ceil(max(0.0, required_length - tile_length) / step_length))
    else:
        columns = max(1, 1 + math.ceil(max(0.0, required_width - tile_width) / step_width))
        rows = max(1, 1 + math.ceil(max(0.0, required_length - tile_length) / step_length))
    required_tiles = columns * rows
    max_surface_tiles = max(
        1,
        min(int(constraints.get("maxSurfaceTiles", asset_limit) or asset_limit), 100),
    )
    available_tiles = min(
        max_surface_tiles,
        max(0, asset_limit - (len(placements) - len(surfaces))),
    )
    planned_tiles = min(max(required_tiles, len(surfaces)), available_tiles)

    existing_aliases = {str(item.get("alias", "")) for item in placements}
    role_id = str(template.get("role", "surface"))
    while len(surfaces) < planned_tiles:
        clone = copy.deepcopy(template)
        alias_index = len(surfaces) + 1
        alias = f"{role_id}-{alias_index}"
        while alias in existing_aliases:
            alias_index += 1
            alias = f"{role_id}-{alias_index}"
        clone["alias"] = alias
        clone["layout_index"] = len(surfaces)
        clone["reference"] = ""
        clone["alternatives"] = []
        placements.append(clone)
        surfaces.append(clone)
        existing_aliases.add(alias)

    axis = str(geometry.get("centerlineAxis", "+Z")).upper()
    for index, placement in enumerate(surfaces):
        if surface_type in {"road", "bridge"}:
            row = index
            column = 0
        else:
            row = index // columns
            column = index % columns
        offset_x = (column - (columns - 1) / 2.0) * step_width
        offset_z = (row - (rows - 1) / 2.0) * step_length
        if surface_type in {"road", "bridge"} and axis.endswith("X"):
            offset_x, offset_z = offset_z, 0.0
        position = {
            "x": center[0] + offset_x,
            "y": center[1],
            "z": center[2] + offset_z,
        }
        placement.update(
            {
                "layout": "single",
                "layout_index": index,
                "position": position,
                "position_is_ground_point": True,
                "preview_position": position,
                "avoid_collisions": False,
                "surface_tile_index": index,
                "surface_tile_row": row,
                "surface_tile_column": column,
                "surface_tile_count": planned_tiles,
            }
        )

    if required_tiles > available_tiles:
        errors.append(
            f"Surface coverage requires {required_tiles} tiles but only "
            f"{available_tiles} fit within max_assets/maxSurfaceTiles"
        )
    elif required_tiles > 1:
        warnings.append(
            f"Surface was expanded to {required_tiles} tiles to cover "
            f"{required_width:.2f} x {required_length:.2f} meters"
        )
    return {
        "surfaceType": surface_type,
        "tileAssetId": template.get("asset_id"),
        "tileSize": {"x": tile_width, "z": tile_length},
        "requestedSize": {"x": required_width, "z": required_length},
        "columns": columns,
        "rows": rows,
        "requiredTiles": required_tiles,
        "plannedTiles": planned_tiles,
        "complete": required_tiles <= available_tiles,
    }


def _apply_semantic_placement(
    placements: list[dict[str, Any]],
    records_by_id: dict[str, AssetRecord],
    scene_context: dict[str, Any],
    intent: str,
    errors: list[str],
) -> None:
    priority = {"surface": 0, "occupant": 1, "roadside": 2, "background": 3, "obstacle": 4}
    placements.sort(
        key=lambda item: priority.get(
            str(_semantic_placement_profile(str(item.get("asset_id", "")), records_by_id).get("placementRole", "obstacle")),
            4,
        )
    )
    surfaces = [
        item
        for item in placements
        if _semantic_placement_profile(
            str(item.get("asset_id", "")), records_by_id
        ).get("placementRole") == "surface"
    ]
    surface = surfaces[0] if surfaces else None
    road_requested = any(term in intent.lower() for term in ("road", "道路", "路面", "石板路"))
    existing = None if surfaces else _existing_surface(scene_context, road_requested)
    anchor_reference = f"@{surface['alias']}" if surface else str((existing or {}).get("path", ""))
    surface_references = [f"@{item['alias']}" for item in surfaces]
    ground_candidate = next(
        (
            item for item in scene_context.get("surfaces", [])
            if str(item.get("surface_type", "")).lower() in {"terrain", "ground"}
        ),
        None,
    )
    ground_reference = str((ground_candidate or {}).get("path", ""))
    support_type = ""
    support_width = 4.0
    proxy_surface = False
    if surface:
        surface_profile = _semantic_placement_profile(str(surface.get("asset_id", "")), records_by_id)
        support_type = str(surface_profile.get("surfaceType", "ground"))
        geometry = surface_profile.get("surfaceGeometry", {})
        if isinstance(geometry, dict):
            support_width = max(0.1, float(geometry.get("effectiveWidth", 4.0) or 4.0))
            proxy_surface = bool(geometry.get("proxySurface", False))
    elif existing:
        support_type = str(existing.get("surface_type", "ground"))
        bounds = existing.get("bounds", {})
        size = bounds.get("size", {}) if isinstance(bounds, dict) else {}
        support_width = max(0.1, float(size.get("x", 4.0) or 4.0))
        proxy_surface = bool(existing.get("proxy_surface", False))

    needs_support = any(
        _semantic_placement_profile(str(item.get("asset_id", "")), records_by_id).get("placementRole")
        in {"occupant", "roadside", "background"}
        for item in placements
    )
    if road_requested and needs_support and not anchor_reference:
        errors.append("No analyzable road, platform, Terrain, or Ground support was selected")

    role_slots = {"occupant": 0, "roadside": 0, "background": 0}
    for placement in placements:
        asset_id = str(placement.get("asset_id", ""))
        profile = _semantic_placement_profile(asset_id, records_by_id)
        role = str(profile.get("placementRole", "obstacle"))
        placement.update(
            {
                "placementRole": role,
                "supportReference": None,
                "zoneReference": None,
                "surfaceZone": "anchor" if role == "surface" else "near",
                "groundingGroup": None,
                "supportEvidence": [],
                "surfaceNormal": {"x": 0.0, "y": 1.0, "z": 0.0},
                "contactError": None,
                "lateralOffset": 0.0,
                "alignToPath": False,
                "forbiddenZoneViolations": [],
                "groundingMode": profile.get("groundingMode", "bounds_bottom"),
                "pivotToContact": profile.get("pivotToContact", [0.0, 0.0, 0.0]),
                "contactPoints": profile.get("contactPoints", [[0.0, 0.0, 0.0]]),
                "footprint": profile.get("footprint", {"x": 0.0, "z": 0.0}),
                "maxSlopeDegrees": float(profile.get("maxSlopeDegrees", 25.0) or 25.0),
                "allowedSurfaceTypes": profile.get("allowedSurfaceTypes", ["ground"]),
                "forbiddenZones": profile.get("forbiddenZones", []),
                "supportSurfaceType": None,
            }
        )
        if role == "surface":
            # Surface tiles have authoritative preview positions. Graph relations may
            # describe their context, but must not make a tile depend on an occupant.
            placement["reference"] = ""
            placement["relation"] = "near"
            if ground_reference:
                placement["supportReference"] = ground_reference
                placement["supportSurfaceType"] = str(
                    (ground_candidate or {}).get("surface_type", "ground")
                )
                placement["groundingGroup"] = f"support:{ground_reference}:surface"
            placement["supportEvidence"] = [{
                "kind": "surface_provider",
                "surfaceType": profile.get("surfaceType", "ground"),
                "proxySurface": bool((profile.get("surfaceGeometry") or {}).get("proxySurface", False)),
                "baseSupport": ground_reference or None,
            }]
            continue
        if not anchor_reference or role not in role_slots:
            continue
        slot = role_slots[role]
        role_slots[role] += 1
        if surface_references and role in {"roadside", "background"}:
            role_anchor = surface_references[(slot // 2) % len(surface_references)]
        else:
            role_anchor = anchor_reference
        preferred = max(0.0, float(profile.get("preferredDistance", 1.0) or 1.0))
        placement["zoneReference"] = role_anchor
        if role == "occupant":
            placement["supportReference"] = role_anchor
            placement["supportSurfaceType"] = support_type or "ground"
            placement["groundingGroup"] = f"support:{role_anchor}"
        else:
            placement["supportReference"] = ground_reference or None
            placement["supportSurfaceType"] = str(
                (ground_candidate or {}).get("surface_type", "ground")
            )
            placement["groundingGroup"] = (
                f"support:{ground_reference}:{role}" if ground_reference else None
            )
        placement["surface_slot_index"] = slot
        placement["supportEvidence"] = [{
            "kind": "selected_asset" if surfaces else "existing_scene_surface",
            "reference": placement["supportReference"],
            "zoneReference": role_anchor,
            "surfaceType": support_type or "ground",
            "proxySurface": proxy_surface,
        }]
        if role == "occupant":
            placement["surfaceZone"] = "top"
            side = -1.0 if slot % 2 == 0 else 1.0
            placement["lateralOffset"] = side * min(support_width * 0.25, max(0.5, preferred * 0.5))
            placement["alignToPath"] = True
        elif role == "roadside":
            placement["surfaceZone"] = "left_side" if slot % 2 == 0 else "right_side"
            placement["lateralOffset"] = max(1.0, preferred)
            placement["alignToPath"] = True
        elif role == "background":
            placement["surfaceZone"] = "left_outer" if slot % 2 == 0 else "right_outer"
            placement["lateralOffset"] = max(6.0, preferred)
        forbidden = {str(item) for item in profile.get("forbiddenZones", [])}
        if placement["surfaceZone"] in forbidden:
            placement["forbiddenZoneViolations"].append(placement["surfaceZone"])
            errors.append(f"{placement['alias']} was assigned to forbidden zone {placement['surfaceZone']}")


def build_asset_scene_preview(
    *,
    intent: str,
    scene_context: dict[str, Any],
    reference_object: str = "",
    region_center: Any = None,
    region_size: Any = None,
    max_assets: int = 20,
    density: str = "medium",
    constraints: dict[str, Any] | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    recipes_path: Path | str = DEFAULT_RECIPES_PATH,
) -> dict[str, Any]:
    if not intent.strip():
        raise ValueError("intent is required")
    constraints = constraints or {}
    records_by_id = {
        record.asset_id: record for record in load_asset_records(library_root)
    }
    recipes = load_scene_recipes(recipes_path)
    ranked_recipes = sorted(
        ((recipe, _recipe_score(intent, recipe)) for recipe in recipes),
        key=lambda item: item[1],
        reverse=True,
    )
    recipe = ranked_recipes[0][0] if ranked_recipes and ranked_recipes[0][1] > 0 else None
    parser = "recipe_rules"
    roles = list(recipe.get("roles", [])) if recipe else []
    if not roles:
        roles = _local_llm_roles(intent)
        parser = "qwen2.5-coder:7b" if roles else "single_query_fallback"
    if not roles:
        roles = [{"id": "asset", "query": intent, "count": 1, "relation": "near"}]
    roles = [
        role
        for _, role in sorted(
            enumerate(roles),
            key=lambda item: (
                _role_placement_priority(item[1], records_by_id),
                item[0],
            ),
        )
        if isinstance(role, dict)
    ]

    density_multiplier = {"low": 0.6, "medium": 1.0, "high": 1.5}.get(
        density.lower(), 1.0
    )
    asset_limit = max(1, min(int(max_assets), 100))
    center = _vector(region_center, (0.0, 0.0, 0.0))
    size = _vector(region_size, (20.0, 10.0, 20.0))
    if reference_object:
        for obj in scene_context.get("objects", []):
            if str(obj.get("path", "")) == reference_object:
                center = _vector(obj.get("position"), center)
                break

    placements: list[dict[str, Any]] = []
    parsed_roles: list[dict[str, Any]] = []
    errors: list[str] = []
    primary_alias = reference_object or ""
    for role in roles:
        if not isinstance(role, dict):
            continue
        role_id = str(role.get("id", f"role-{len(parsed_roles) + 1}"))
        requested_count = max(1, int(role.get("count", 1)))
        count = max(1, round(requested_count * density_multiplier))
        count = min(count, asset_limit - len(placements))
        if count <= 0:
            break
        explicit_ids = [str(item) for item in role.get("assetIds", [])]
        existing = _scene_object_match(
            role,
            explicit_ids,
            scene_context,
            library_root,
            records_by_id,
        )
        if existing:
            parsed_roles.append(
                {"id": role_id, "kind": "existing", "scene_object": existing}
            )
            if role.get("primary") and not primary_alias:
                primary_alias = str(existing.get("path", ""))
            continue
        role_placements: list[dict[str, Any]] = []
        for item_index in range(count):
            selected, alternatives = _select_asset(
                role,
                item_index,
                library_root,
                records_by_id,
            )
            if not selected:
                if not role.get("optional", False):
                    errors.append(f"No asset matched required role: {role_id}")
                continue
            relation = str(role.get("relation", "near")).lower()
            if relation not in {"near", "left", "right", "front", "behind", "on"}:
                relation = "near"
            distance = max(0.0, float(role.get("distance", 2.0)))
            layout = str(role.get("layout", "single"))
            alias = f"{role_id}-{item_index + 1}"
            placement = {
                "alias": alias,
                "role": role_id,
                "asset_id": selected.get("assetId"),
                "display_name": selected.get("displayName"),
                "required": not role.get("optional", False),
                "reference": primary_alias,
                "relation": relation,
                "distance": distance,
                "layout": layout,
                "layout_index": item_index,
                "ground_snap": bool(role.get("groundSnap", True)),
                "avoid_collisions": bool(role.get("avoidCollisions", True)),
                "face_reference": bool(role.get("faceReference", False)),
                "minimum_clearance": max(
                    0.0, float(role.get("minimumClearance", 0.0))
                ),
                "preview_position": _preview_position(
                    item_index, relation, distance, layout, center
                ),
                "alternatives": [
                    {
                        "asset_id": item.get("assetId"),
                        "display_name": item.get("displayName"),
                        "score": item.get("score"),
                        "confidence": item.get("confidence"),
                    }
                    for item in alternatives[:5]
                ],
                "relationEvidence": [],
                "compiledConstraints": [],
            }
            placements.append(placement)
            role_placements.append(placement)
            if role.get("primary") and not primary_alias:
                primary_alias = f"@{alias}"
        parsed_roles.append(
            {"id": role_id, "kind": "asset", "placements": role_placements}
        )

    warnings: list[str] = []
    surface_coverage = _expand_surface_coverage(
        placements,
        records_by_id,
        center,
        size,
        asset_limit,
        constraints,
        warnings,
        errors,
    )
    if surface_coverage:
        for parsed_role in parsed_roles:
            if parsed_role.get("kind") != "asset":
                continue
            role_id = str(parsed_role.get("id", ""))
            parsed_role["placements"] = [
                item for item in placements if str(item.get("role", "")) == role_id
            ]
    if bool(constraints.get("expandRelations", True)) and len(placements) < asset_limit:
        companions = _append_manual_companions(
            placements,
            asset_limit,
            center,
            library_root,
            records_by_id,
        )
        if companions:
            parsed_roles.append(
                {
                    "id": "graph-companion",
                    "kind": "asset",
                    "placements": companions,
                }
            )

    _compile_selected_relations(placements, library_root, records_by_id)
    _apply_semantic_placement(
        placements,
        records_by_id,
        scene_context,
        intent,
        errors,
    )
    placements, dependencies_resolved = _order_placements_by_dependencies(placements)
    if not dependencies_resolved:
        warnings.append(
            "A relation reference cycle was detected; original order was retained for the cycle"
        )
    if len(placements) >= asset_limit:
        warnings.append("Plan reached max_assets and was truncated")
    plan = {
        "status": "preview",
        "intent": intent,
        "parser": parser,
        "recipe_id": recipe.get("id") if recipe else None,
        "recipe_name": recipe.get("displayName") if recipe else None,
        "reference_object": reference_object or None,
        "region_center": {"x": center[0], "y": center[1], "z": center[2]},
        "region_size": {"x": size[0], "y": size[1], "z": size[2]},
        "density": density,
        "constraints": constraints,
        "surface_coverage": surface_coverage,
        "scene_token": scene_context.get("scene_token"),
        "scene_path": scene_context.get("scene_path"),
        "roles": parsed_roles,
        "placements": placements,
        "asset_count": len(placements),
        "errors": errors,
        "warnings": warnings,
        "can_apply": bool(placements) and not errors,
    }
    plan_id = get_asset_scene_plan_store().put(plan)
    return {**plan, "plan_id": plan_id, "success": True}
