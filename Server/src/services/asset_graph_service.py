"""Deterministic, cached asset graph with auditable manual overrides."""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from services.asset_library_service import (
    DEFAULT_LIBRARY_ROOT,
    AssetRecord,
    load_asset_records,
)


_SERVER_DIR = Path(__file__).resolve().parents[2]
DEFAULT_GRAPH_PATH = _SERVER_DIR / "data" / "asset_library" / "asset_graph.json"
DEFAULT_RECIPES_PATH = _SERVER_DIR / "data" / "asset_library" / "scene_recipes.json"
DEFAULT_MANUAL_RELATIONS_PATH = (
    _SERVER_DIR / "data" / "asset_library" / "manual_relations.json"
)

DEFAULT_RELATION_TYPES = {
    "variant_of",
    "pairs_with",
    "part_of",
    "placed_near",
    "placed_on",
    "supports",
    "lines_path",
    "faces",
    "avoid_overlap",
    "part_of_recipe",
}
MANUAL_RELATION_TYPES = {
    "pairs_with",
    "placed_near",
    "placed_on",
    "supports",
    "lines_path",
    "faces",
    "avoid_overlap",
}
RETRIEVAL_RELATION_TYPES = {
    "pairs_with",
    "placed_near",
    "placed_on",
    "supports",
    "lines_path",
}
CONSTRAINT_RELATION_TYPES = {
    "placed_near",
    "placed_on",
    "lines_path",
    "faces",
    "avoid_overlap",
}
SYMMETRIC_RELATION_TYPES = {"pairs_with", "placed_near", "avoid_overlap"}
_ORIGIN_PRIORITY = {"auto": 0, "recipe": 1, "manifest": 2, "manual": 3}


def relation_policy(relation_type: str) -> dict[str, bool]:
    return {
        "retrieval": relation_type in RETRIEVAL_RELATION_TYPES,
        "constraint": relation_type in CONSTRAINT_RELATION_TYPES,
    }


def graph_path_for_library(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> Path:
    root = Path(library_root).resolve()
    if root == Path(DEFAULT_LIBRARY_ROOT).resolve():
        return DEFAULT_GRAPH_PATH.resolve()
    return root / ".asset-library-graph.json"


def manual_relations_path_for_library(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> Path:
    root = Path(library_root).resolve()
    if root == Path(DEFAULT_LIBRARY_ROOT).resolve():
        return DEFAULT_MANUAL_RELATIONS_PATH.resolve()
    return root / ".asset-library-manual-relations.json"


def _resolve_graph_path(
    graph_path: Path | str | None,
    library_root: Path | str,
) -> Path:
    return (
        Path(graph_path).resolve()
        if graph_path is not None
        else graph_path_for_library(library_root)
    )


def _resolve_manual_path(
    manual_relations_path: Path | str | None,
    library_root: Path | str,
) -> Path:
    return (
        Path(manual_relations_path).resolve()
        if manual_relations_path is not None
        else manual_relations_path_for_library(library_root)
    )


def load_scene_recipes(
    recipes_path: Path | str = DEFAULT_RECIPES_PATH,
) -> list[dict[str, Any]]:
    path = Path(recipes_path).resolve()
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    recipes = data.get("recipes", []) if isinstance(data, dict) else []
    return [dict(item) for item in recipes if isinstance(item, dict)]


def _empty_manual_payload() -> dict[str, Any]:
    return {"schemaVersion": 1, "relations": []}


def load_manual_relations(
    manual_relations_path: Path | str = DEFAULT_MANUAL_RELATIONS_PATH,
) -> dict[str, Any]:
    path = Path(manual_relations_path).resolve()
    if not path.is_file():
        return _empty_manual_payload()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("relations", []), list):
        raise ValueError("manual_relations.json must contain a relations array")
    return {"schemaVersion": int(data.get("schemaVersion", 1)), "relations": data.get("relations", [])}


def _edge_key(edge: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(edge.get("source", "")),
        str(edge.get("target", "")),
        str(edge.get("type", "")),
    )


def _add_edge(
    edges: dict[tuple[str, str, str], dict[str, Any]],
    source: str,
    target: str,
    relation_type: str,
    *,
    weight: float = 0.5,
    origin: str = "auto",
    metadata: dict[str, Any] | None = None,
) -> None:
    if not source or not target or source == target:
        return
    policy = relation_policy(relation_type)
    edge = {
        "source": source,
        "target": target,
        "type": relation_type,
        "weight": max(0.0, min(1.0, float(weight))),
        "origin": origin,
        "retrievalEligible": policy["retrieval"],
        "constraintEligible": policy["constraint"],
    }
    if metadata:
        edge["metadata"] = metadata
    key = _edge_key(edge)
    previous = edges.get(key)
    previous_priority = _ORIGIN_PRIORITY.get(str((previous or {}).get("origin", "auto")), 0)
    priority = _ORIGIN_PRIORITY.get(origin, 0)
    if (
        previous is None
        or priority > previous_priority
        or (priority == previous_priority and edge["weight"] >= previous["weight"])
    ):
        edges[key] = edge


def _endpoint_key(endpoint: dict[str, Any]) -> str:
    if endpoint.get("assetId"):
        return f"asset:{endpoint['assetId']}"
    return f"variant:{endpoint.get('variantGroup', '')}"


def _normalize_endpoint(value: Any, field: str) -> dict[str, str]:
    if isinstance(value, str) and value.strip():
        return {"assetId": value.strip()}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must contain assetId or variantGroup")
    asset_id = str(value.get("assetId", "")).strip()
    variant = str(value.get("variantGroup", "")).strip()
    if bool(asset_id) == bool(variant):
        raise ValueError(f"{field} must contain exactly one of assetId or variantGroup")
    return {"assetId": asset_id} if asset_id else {"variantGroup": variant}


def _stable_relation_id(source: dict[str, str], target: dict[str, str], relation_type: str) -> str:
    raw = f"{_endpoint_key(source)}\0{relation_type}\0{_endpoint_key(target)}"
    return "manual-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normalize_manual_relation(raw: dict[str, Any]) -> dict[str, Any]:
    source = _normalize_endpoint(raw.get("source"), "source")
    target = _normalize_endpoint(raw.get("target"), "target")
    relation_type = str(raw.get("type", "")).strip()
    if relation_type not in MANUAL_RELATION_TYPES:
        raise ValueError(f"Unsupported manual relation type: {relation_type}")
    if source == target:
        raise ValueError("Manual relation source and target must differ")
    try:
        weight = float(raw.get("weight", 1.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Manual relation weight must be numeric") from exc
    if not 0.0 <= weight <= 1.0:
        raise ValueError("Manual relation weight must be between 0 and 1")
    spatial = raw.get("spatial", {})
    spatial = dict(spatial) if isinstance(spatial, dict) else {}
    for key in ("minDistance", "maxDistance", "yawOffset"):
        if key not in spatial:
            continue
        try:
            spatial[key] = float(spatial[key])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"spatial.{key} must be numeric") from exc
    if float(spatial.get("minDistance", 0.0)) < 0:
        raise ValueError("spatial.minDistance must be non-negative")
    if "maxDistance" in spatial and float(spatial["maxDistance"]) < float(spatial.get("minDistance", 0.0)):
        raise ValueError("spatial.maxDistance must be >= minDistance")
    bidirectional = bool(raw.get("bidirectional", relation_type in SYMMETRIC_RELATION_TYPES))
    if relation_type in SYMMETRIC_RELATION_TYPES:
        bidirectional = True
    return {
        "id": str(raw.get("id", "")).strip() or _stable_relation_id(source, target, relation_type),
        "source": source,
        "target": target,
        "type": relation_type,
        "weight": weight,
        "bidirectional": bidirectional,
        "enabled": bool(raw.get("enabled", True)),
        "note": str(raw.get("note", "")).strip(),
        "spatial": spatial,
    }


def _manual_catalog(records: list[AssetRecord]) -> tuple[set[str], dict[str, list[str]]]:
    asset_ids = {record.asset_id for record in records}
    variants: dict[str, list[str]] = {}
    for record in records:
        variant = str(record.data.get("variantGroup", "")).strip()
        if variant:
            variants.setdefault(variant, []).append(record.asset_id)
    return asset_ids, variants


def _expand_endpoint(
    endpoint: dict[str, str],
    asset_ids: set[str],
    variants: dict[str, list[str]],
) -> list[str]:
    if endpoint.get("assetId"):
        asset_id = endpoint["assetId"]
        return [asset_id] if asset_id in asset_ids else []
    return sorted(variants.get(endpoint.get("variantGroup", ""), []))


def validate_manual_relations(
    payload: dict[str, Any],
    records: list[AssetRecord] | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    records = records if records is not None else load_asset_records(library_root)
    asset_ids, variants = _manual_catalog(records)
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    expanded_edges: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, str]] = set()
    raw_relations = payload.get("relations", []) if isinstance(payload, dict) else []
    if not isinstance(raw_relations, list):
        return {"valid": False, "errors": ["relations must be an array"], "warnings": [], "relations": [], "expandedEdges": []}
    for index, raw in enumerate(raw_relations):
        if not isinstance(raw, dict):
            errors.append(f"relations[{index}] must be an object")
            continue
        try:
            relation = _normalize_manual_relation(raw)
        except ValueError as exc:
            errors.append(f"relations[{index}]: {exc}")
            continue
        if relation["id"] in seen_ids:
            errors.append(f"Duplicate manual relation id: {relation['id']}")
            continue
        seen_ids.add(relation["id"])
        sources = _expand_endpoint(relation["source"], asset_ids, variants)
        targets = _expand_endpoint(relation["target"], asset_ids, variants)
        if not sources:
            errors.append(f"{relation['id']}: source endpoint matches no assets")
        if not targets:
            errors.append(f"{relation['id']}: target endpoint matches no assets")
        if not relation["enabled"]:
            normalized.append(relation)
            continue
        for source in sources:
            for target in targets:
                if source == target:
                    warnings.append(f"{relation['id']}: skipped self edge {source}")
                    continue
                key = (source, target, relation["type"])
                if key in seen_keys:
                    errors.append(f"{relation['id']}: duplicate expanded edge {source}->{target}:{relation['type']}")
                    continue
                seen_keys.add(key)
                expanded_edges.append({**relation, "sourceAssetId": source, "targetAssetId": target})
                if relation["bidirectional"]:
                    reverse = (target, source, relation["type"])
                    if reverse not in seen_keys:
                        seen_keys.add(reverse)
                        expanded_edges.append({**relation, "sourceAssetId": target, "targetAssetId": source})
        normalized.append(relation)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "relations": normalized,
        "expandedEdges": expanded_edges,
    }


@dataclass(frozen=True)
class AssetGraphIndex:
    payload: dict[str, Any]
    nodes: dict[str, dict[str, Any]]
    outgoing: dict[str, tuple[dict[str, Any], ...]]
    incoming: dict[str, tuple[dict[str, Any], ...]]
    signature: tuple[int, int]


_GRAPH_CACHE: dict[Path, AssetGraphIndex] = {}
_GRAPH_CACHE_LOCK = threading.Lock()


def invalidate_asset_graph_cache(graph_path: Path | str | None = None) -> None:
    with _GRAPH_CACHE_LOCK:
        if graph_path is None:
            _GRAPH_CACHE.clear()
        else:
            _GRAPH_CACHE.pop(Path(graph_path).resolve(), None)


def build_asset_graph(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    graph_path: Path | str | None = None,
    recipes_path: Path | str = DEFAULT_RECIPES_PATH,
    manual_relations_path: Path | str | None = None,
) -> dict[str, Any]:
    records = load_asset_records(library_root)
    recipes = load_scene_recipes(recipes_path)
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    by_variant: dict[str, list[str]] = {}
    manual_path = _resolve_manual_path(manual_relations_path, library_root)

    for record in records:
        data = record.data
        nodes[record.asset_id] = {
            "id": record.asset_id,
            "type": "asset",
            "displayName": data.get("displayName", ""),
            "category": data.get("category", ""),
            "tags": data.get("tags", []),
            "semanticAttributes": data.get("semanticAttributes", {}),
            "placementProfile": data.get("placementProfile", {}),
        }
        bundle_id = str(data.get("bundleId", "")).strip()
        if bundle_id:
            bundle_node = f"bundle:{bundle_id}"
            nodes.setdefault(bundle_node, {"id": bundle_node, "type": "bundle", "displayName": data.get("bundleDisplayName", bundle_id)})
            _add_edge(edges, record.asset_id, bundle_node, "part_of", weight=1.0)
        variant = str(data.get("variantGroup", "")).strip()
        if variant:
            variant_node = f"variant:{variant}"
            nodes.setdefault(variant_node, {"id": variant_node, "type": "variant_group", "displayName": variant})
            by_variant.setdefault(variant_node, []).append(record.asset_id)
            _add_edge(edges, record.asset_id, variant_node, "variant_of", weight=1.0)
        for relation in data.get("relations", []):
            if isinstance(relation, dict):
                _add_edge(
                    edges,
                    record.asset_id,
                    str(relation.get("targetAssetId", "")),
                    str(relation.get("type", "pairs_with")),
                    weight=float(relation.get("weight", 1.0)),
                    origin="manifest" if relation.get("source") != "manual" else "manual",
                    metadata=dict(relation.get("metadata", {})) if isinstance(relation.get("metadata"), dict) else None,
                )

    for members in by_variant.values():
        for source in members:
            for target in members:
                if source != target:
                    _add_edge(edges, source, target, "variant_of", weight=0.85)

    for recipe in recipes:
        recipe_id = str(recipe.get("id", "")).strip()
        if not recipe_id:
            continue
        recipe_node = f"recipe:{recipe_id}"
        nodes[recipe_node] = {"id": recipe_node, "type": "recipe", "displayName": recipe.get("displayName", recipe_id), "keywords": recipe.get("keywords", [])}
        primary_assets: list[str] = []
        for role in recipe.get("roles", []) if isinstance(recipe.get("roles", []), list) else []:
            if not isinstance(role, dict):
                continue
            assets = [str(asset_id) for asset_id in role.get("assetIds", []) if str(asset_id) in nodes]
            if role.get("primary"):
                primary_assets.extend(assets)
            relation = str(role.get("graphRelation", "pairs_with"))
            for asset_id in assets:
                _add_edge(edges, asset_id, recipe_node, "part_of_recipe", weight=1.0, origin="recipe", metadata={"role": role.get("id", "")})
                for primary in primary_assets:
                    if asset_id != primary:
                        _add_edge(edges, primary, asset_id, relation, weight=float(role.get("relationWeight", 0.9)), origin="recipe")

    manual_payload = load_manual_relations(manual_path)
    manual_validation = validate_manual_relations(manual_payload, records, library_root)
    if not manual_validation["valid"]:
        raise ValueError("Invalid manual asset relations: " + "; ".join(manual_validation["errors"]))
    for expanded in manual_validation["expandedEdges"]:
        relation = expanded
        metadata = {
            "manualRelationId": relation["id"],
            "note": relation.get("note", ""),
            **relation.get("spatial", {}),
        }
        _add_edge(
            edges,
            str(relation["sourceAssetId"]),
            str(relation["targetAssetId"]),
            str(relation["type"]),
            weight=float(relation["weight"]),
            origin="manual",
            metadata=metadata,
        )

    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "assetCount": len(records),
        "recipeCount": len(recipes),
        "manualRelationCount": len([item for item in manual_validation["relations"] if item["enabled"]]),
        "nodes": sorted(nodes.values(), key=lambda item: item["id"]),
        "edges": sorted(edges.values(), key=_edge_key),
    }
    path = _resolve_graph_path(graph_path, library_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    invalidate_asset_graph_cache(path)
    return {
        "success": True,
        "graph_path": str(path),
        "manual_relations_path": str(manual_path),
        "asset_count": len(records),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "manual_relation_count": payload["manualRelationCount"],
        "recipe_count": len(recipes),
    }


def load_asset_graph_index(
    graph_path: Path | str | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> AssetGraphIndex:
    path = _resolve_graph_path(graph_path, library_root)
    if not path.is_file():
        build_asset_graph(library_root=library_root, graph_path=path)
    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    with _GRAPH_CACHE_LOCK:
        cached = _GRAPH_CACHE.get(path)
        if cached is not None and cached.signature == signature:
            return cached
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = {str(node.get("id", "")): node for node in payload.get("nodes", []) if node.get("id")}
    outgoing_lists: dict[str, list[dict[str, Any]]] = {}
    incoming_lists: dict[str, list[dict[str, Any]]] = {}
    for edge in payload.get("edges", []):
        outgoing_lists.setdefault(str(edge.get("source", "")), []).append(edge)
        incoming_lists.setdefault(str(edge.get("target", "")), []).append(edge)
    index = AssetGraphIndex(
        payload=payload,
        nodes=nodes,
        outgoing={key: tuple(value) for key, value in outgoing_lists.items()},
        incoming={key: tuple(value) for key, value in incoming_lists.items()},
        signature=signature,
    )
    with _GRAPH_CACHE_LOCK:
        _GRAPH_CACHE[path] = index
    return index


def load_asset_graph(
    graph_path: Path | str | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    return load_asset_graph_index(graph_path, library_root).payload


def compile_relation_constraint(edge: dict[str, Any]) -> dict[str, Any] | None:
    relation_type = str(edge.get("type", ""))
    if relation_type not in CONSTRAINT_RELATION_TYPES:
        return None
    metadata = edge.get("metadata", {}) if isinstance(edge.get("metadata"), dict) else {}
    result: dict[str, Any] = {"type": relation_type, "source": edge.get("source"), "target": edge.get("target")}
    if relation_type == "faces":
        result.update({"faceReference": True, "yawOffset": float(metadata.get("yawOffset", 0.0))})
    elif relation_type == "avoid_overlap":
        result.update({"avoidCollisions": True, "minimumClearance": max(0.0, float(metadata.get("minDistance", 0.0)))})
    elif relation_type == "placed_on":
        result.update({"relation": "on"})
    elif relation_type == "placed_near":
        result.update({"relation": "near", "minDistance": max(0.0, float(metadata.get("minDistance", 0.0))), "maxDistance": metadata.get("maxDistance")})
    elif relation_type == "lines_path":
        result.update({"layout": "line", "spacing": max(0.0, float(metadata.get("minDistance", 0.0)))})
    return result


def get_asset_relations(
    asset_id: str,
    relation_types: Iterable[str] | None = None,
    depth: int = 1,
    graph_path: Path | str | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    origins: Iterable[str] | None = None,
    include_constraints: bool = False,
    direction: str = "outgoing",
) -> dict[str, Any]:
    index = load_asset_graph_index(graph_path, library_root)
    allowed = {str(item).strip() for item in (relation_types or DEFAULT_RELATION_TYPES) if str(item).strip()}
    allowed_origins = {str(item).strip() for item in origins or [] if str(item).strip()}
    if asset_id not in index.nodes:
        raise KeyError(f"Asset graph node not found: {asset_id}")
    if direction not in {"outgoing", "incoming", "both"}:
        raise ValueError("direction must be outgoing, incoming, or both")
    queue = deque([(asset_id, 0)])
    visited = {asset_id}
    results: list[dict[str, Any]] = []
    max_depth = max(1, min(int(depth), 3))
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= max_depth:
            continue
        candidates: list[tuple[dict[str, Any], str]] = []
        if direction in {"outgoing", "both"}:
            candidates.extend((edge, str(edge.get("target", ""))) for edge in index.outgoing.get(current, ()))
        if direction in {"incoming", "both"}:
            candidates.extend((edge, str(edge.get("source", ""))) for edge in index.incoming.get(current, ()))
        for edge, neighbor in candidates:
            if str(edge.get("type", "")) not in allowed:
                continue
            if allowed_origins and str(edge.get("origin", "")) not in allowed_origins:
                continue
            item = {**edge, "depth": current_depth + 1, "targetNode": index.nodes.get(str(edge.get("target", ""))), "neighborNode": index.nodes.get(neighbor)}
            if include_constraints:
                item["compiledConstraint"] = compile_relation_constraint(edge)
            results.append(item)
            if neighbor and neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, current_depth + 1))
    return {
        "success": True,
        "asset_id": asset_id,
        "depth": max_depth,
        "direction": direction,
        "origins": sorted(allowed_origins),
        "relation_types": sorted(allowed),
        "relation_count": len(results),
        "relations": results,
    }


def graph_expansion_scores(
    seed_scores: dict[str, float],
    graph_path: Path | str | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    index = load_asset_graph_index(graph_path, library_root)
    expanded: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for source, source_score in seed_scores.items():
        for edge in index.outgoing.get(source, ()):
            if not edge.get("retrievalEligible", str(edge.get("type", "")) in RETRIEVAL_RELATION_TYPES):
                continue
            target = str(edge.get("target", ""))
            if not target or str((index.nodes.get(target) or {}).get("type")) != "asset":
                continue
            relation = str(edge.get("type", ""))
            bonus = min(5.0, float(source_score) * float(edge.get("weight", 0.0)) * 0.05)
            if bonus <= 0:
                continue
            expanded[target] = max(expanded.get(target, 0.0), bonus)
            reasons.setdefault(target, []).append(f"relation:{relation}:{source}")
    return expanded, reasons


class AssetRelationPlanStore:
    def __init__(self, ttl_seconds: float = 1800.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._plans: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, plan: dict[str, Any]) -> str:
        plan_id = uuid.uuid4().hex
        now = time.time()
        payload = {**plan, "plan_id": plan_id, "created_at": now, "expires_at": now + self.ttl_seconds}
        with self._lock:
            self._cleanup(now)
            self._plans[plan_id] = payload
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup(time.time())
            value = self._plans.get(plan_id)
            return dict(value) if value else None

    def _cleanup(self, now: float) -> None:
        for key in [key for key, value in self._plans.items() if float(value.get("expires_at", 0)) <= now]:
            self._plans.pop(key, None)


_RELATION_PLAN_STORE = AssetRelationPlanStore()


def get_asset_relation_plan_store() -> AssetRelationPlanStore:
    return _RELATION_PLAN_STORE


def _file_token(path: Path) -> str:
    content = path.read_bytes() if path.is_file() else b""
    return hashlib.sha256(content).hexdigest()


def _apply_relation_changes(payload: dict[str, Any], changes: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    relations = {str(item.get("id", "")): dict(item) for item in payload.get("relations", []) if isinstance(item, dict) and item.get("id")}
    summary: list[dict[str, Any]] = []
    for change in changes:
        operation = str(change.get("op", "")).strip().lower()
        if operation == "upsert":
            relation = _normalize_manual_relation(dict(change.get("relation", {})))
            status = "updated" if relation["id"] in relations else "added"
            relations[relation["id"]] = relation
            summary.append({"op": operation, "id": relation["id"], "status": status})
        elif operation == "delete":
            relation_id = str(change.get("id", "")).strip()
            existed = relations.pop(relation_id, None) is not None
            summary.append({"op": operation, "id": relation_id, "status": "deleted" if existed else "unchanged"})
        elif operation in {"enable", "disable"}:
            relation_id = str(change.get("id", "")).strip()
            if relation_id not in relations:
                raise ValueError(f"Manual relation not found: {relation_id}")
            relations[relation_id]["enabled"] = operation == "enable"
            summary.append({"op": operation, "id": relation_id, "status": operation + "d"})
        else:
            raise ValueError("Relation change op must be upsert, delete, enable, or disable")
    return {"schemaVersion": 1, "relations": sorted(relations.values(), key=lambda item: item["id"])}, summary


def list_manual_asset_relations(
    asset_id: str = "",
    relation_type: str = "",
    enabled: bool | None = None,
    manual_relations_path: Path | str = DEFAULT_MANUAL_RELATIONS_PATH,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    path = Path(manual_relations_path).resolve()
    payload = load_manual_relations(path)
    records = load_asset_records(library_root)
    asset_ids, variants = _manual_catalog(records)
    validation = validate_manual_relations(
        payload,
        records=records,
        library_root=library_root,
    )
    relations = []
    for relation in validation["relations"]:
        sources = _expand_endpoint(relation["source"], asset_ids, variants)
        targets = _expand_endpoint(relation["target"], asset_ids, variants)
        relations.append(
            {
                **relation,
                "sourceAssets": sources,
                "targetAssets": targets,
                "invalidEndpoints": [
                    endpoint
                    for endpoint, values in (
                        ("source", sources),
                        ("target", targets),
                    )
                    if not values
                ],
                "retrievalEligible": relation_policy(relation["type"])["retrieval"],
                "constraintEligible": relation_policy(relation["type"])["constraint"],
            }
        )
    if asset_id:
        relations = [item for item in relations if item["source"].get("assetId") == asset_id or item["target"].get("assetId") == asset_id]
    if relation_type:
        relations = [item for item in relations if item["type"] == relation_type]
    if enabled is not None:
        relations = [item for item in relations if item["enabled"] is enabled]
    return {"success": True, "path": str(path), "count": len(relations), "relations": relations, "valid": validation["valid"], "errors": validation["errors"], "warnings": validation["warnings"]}


def preview_asset_relation_changes(
    changes: list[dict[str, Any]],
    manual_relations_path: Path | str = DEFAULT_MANUAL_RELATIONS_PATH,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    path = Path(manual_relations_path).resolve()
    current = load_manual_relations(path)
    try:
        candidate, summary = _apply_relation_changes(current, changes)
        validation = validate_manual_relations(candidate, library_root=library_root)
    except ValueError as exc:
        return {
            "success": True,
            "status": "preview",
            "can_apply": False,
            "errors": [str(exc)],
            "blocking_reasons": [str(exc)],
            "conflicts": [],
            "warnings": [],
            "changes": [],
        }
    plan = {"manual_relations_path": str(path), "library_root": str(Path(library_root).resolve()), "source_token": _file_token(path), "candidate": candidate, "changes": summary, "validation": validation}
    plan_id = get_asset_relation_plan_store().put(plan)
    return {
        "success": True,
        "status": "preview",
        "plan_id": plan_id,
        "can_apply": validation["valid"],
        "changes": summary,
        "errors": validation["errors"],
        "blocking_reasons": validation["errors"],
        "conflicts": [],
        "warnings": validation["warnings"],
        "expanded_edges": validation["expandedEdges"],
    }


def apply_asset_relation_changes(plan_id: str) -> dict[str, Any]:
    plan = get_asset_relation_plan_store().get(plan_id)
    if not plan:
        raise KeyError("Relation change plan not found or expired")
    path = Path(plan["manual_relations_path"]).resolve()
    library_root = Path(plan["library_root"]).resolve()
    if _file_token(path) != plan["source_token"]:
        raise RuntimeError("Manual relations changed after preview; preview again")
    if not plan["validation"]["valid"]:
        raise ValueError("Relation change plan contains validation errors")
    graph_path = graph_path_for_library(library_root)
    old_manual = path.read_bytes() if path.is_file() else None
    old_graph = graph_path.read_bytes() if graph_path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        temp.write_text(json.dumps(plan["candidate"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        graph_result = build_asset_graph(library_root=library_root, graph_path=graph_path, manual_relations_path=path)
    except Exception:
        if old_manual is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(old_manual)
        if old_graph is None:
            graph_path.unlink(missing_ok=True)
        else:
            graph_path.write_bytes(old_graph)
        invalidate_asset_graph_cache(graph_path)
        raise
    return {"success": True, "status": "applied", "plan_id": plan_id, "changes": plan["changes"], "manual_relations_path": str(path), "graph": graph_result}
