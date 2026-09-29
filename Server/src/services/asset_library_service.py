"""External Unity asset library indexing, search, and project import."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np


COLLECTION_NAME = "unity_asset_library"
DEFAULT_EMBEDDING_PROVIDER = "bge-m3"
LOCAL_HASH_DIMENSION = 512
INDEX_SCHEMA_VERSION = 2
_SERVER_DIR = Path(__file__).resolve().parents[2]
_WORKSPACE_DIR = _SERVER_DIR.parent.parent
DEFAULT_LIBRARY_ROOT = Path(
    os.environ.get("UNITY_ASSET_LIBRARY_ROOT", _WORKSPACE_DIR / "UnityAssetLibrary")
)
DEFAULT_INDEX_DIR = Path(
    os.environ.get(
        "UNITY_ASSET_LIBRARY_INDEX_DIR",
        _SERVER_DIR / "data" / "asset_library" / "chroma_db",
    )
)
DEFAULT_REGISTRY_PATH = _SERVER_DIR / "data" / "asset_library" / "assets.json"
INDEX_STATE_FILENAME = "active_index.json"
IMPORT_METADATA_FILENAME = ".asset-library-import.json"
ASSET_RERANK_VERSION = "deterministic-v2"

_CATEGORY_LABELS = {
    "animal": ["动物", "生物"],
    "character": ["人物", "角色"],
    "environment": ["环境", "建筑", "场景"],
    "prop": ["道具", "物件"],
    "vehicle": ["载具", "交通工具"],
}


_GUID_PATTERN = re.compile(r"\bguid:\s*([0-9a-fA-F]{32})\b")
_META_GUID_PATTERN = re.compile(
    r"^guid:\s*([0-9a-fA-F]{32})\s*$",
    re.MULTILINE,
)
_TEXT_ASSET_SUFFIXES = {
    ".anim",
    ".asset",
    ".controller",
    ".mat",
    ".overridecontroller",
    ".playable",
    ".prefab",
    ".unity",
}

_ASSET_RECORD_CACHE: dict[
    Path,
    tuple[tuple[int, int, int], tuple["AssetRecord", ...]],
] = {}
_ASSET_RECORD_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class AssetRecord:
    asset_id: str
    manifest_path: Path
    root_path: Path
    data: dict[str, Any]
    document: str

    def metadata(self) -> dict[str, Any]:
        semantic = self.data.get("semanticAttributes", {})
        placement = self.data.get("placementProfile", {})
        return {
            "asset_id": self.asset_id,
            "display_name": str(self.data.get("displayName", "")),
            "category": str(self.data.get("category", "")),
            "library_path": str(self.root_path),
            "manifest_path": str(self.manifest_path),
            "prefab": str(self.data.get("prefab", "")),
            "model": str(self.data.get("model", "")),
            "material": str(self.data.get("material", "")),
            "source_model_guid": str(self.data.get("sourceModelGuid", "")),
            "default_scale": json.dumps(
                self.data.get("defaultScale", []), ensure_ascii=False
            ),
            "bounds": json.dumps(
                self.data.get("bounds", {}), ensure_ascii=False
            ),
            "tags": json.dumps(
                self.data.get("tags", []), ensure_ascii=False
            ),
            "aliases": json.dumps(
                self.data.get("aliases", []), ensure_ascii=False
            ),
            "semantic_attributes": json.dumps(semantic, ensure_ascii=False),
            "placement_profile": json.dumps(placement, ensure_ascii=False),
            "variant_group": str(self.data.get("variantGroup", "")),
        }

    def public_dict(self) -> dict[str, Any]:
        result = dict(self.data)
        bounds = self.data.get("bounds", {})
        try:
            default_radius = max(
                float(bounds.get("x", 0)),
                float(bounds.get("z", 0)),
            ) / 2.0
        except (TypeError, ValueError):
            default_radius = 0.0
        result.setdefault("groundOffset", 0.0)
        result.setdefault("forwardAxis", "+Z")
        result.setdefault("placementRadius", default_radius)
        result.update(
            {
                "assetId": self.asset_id,
                "libraryPath": str(self.root_path),
                "manifestPath": str(self.manifest_path),
                "prefabAbsolutePath": str(
                    _resolve_child_path(self.root_path, str(self.data["prefab"]))
                ),
            }
        )
        return result


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _resolve_child_path(parent: Path, relative_path: str) -> Path:
    candidate = (parent / relative_path).resolve()
    if not _is_within(candidate, parent):
        raise ValueError(f"Path escapes asset root: {relative_path}")
    return candidate


def _string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _infer_size_class(data: dict[str, Any]) -> str:
    bounds = data.get("bounds", {})
    try:
        largest = max(float(bounds.get(axis, 0.0)) for axis in "xyz")
    except (TypeError, ValueError):
        return "medium"
    if largest < 0.5:
        return "tiny"
    if largest < 2.0:
        return "small"
    if largest < 8.0:
        return "medium"
    if largest < 20.0:
        return "large"
    return "huge"


_PLACEMENT_ROLES = {"surface", "occupant", "roadside", "background", "obstacle"}
_SURFACE_TYPES = {"road", "bridge", "platform", "terrain", "ground"}


def _placement_terms(data: dict[str, Any]) -> str:
    values = [
        str(data.get("id", "")),
        str(data.get("displayName", "")),
        str(data.get("description", "")),
        *_string_list(data, "tags"),
        *_string_list(data, "aliases"),
        *_string_list(data, "useCases"),
    ]
    return " ".join(values).lower()


def _placement_identity_terms(data: dict[str, Any]) -> str:
    values = [
        str(data.get("id", "")),
        str(data.get("displayName", "")),
        *_string_list(data, "tags"),
        *_string_list(data, "aliases"),
    ]
    return " ".join(values).lower()


def infer_placement_role(data: dict[str, Any]) -> str:
    terms = _placement_identity_terms(data)
    category = str(data.get("category", "")).lower()
    if category in {"character", "animal", "vehicle"}:
        return "occupant"
    if any(term in terms for term in ("tree", "树", "lantern", "灯笼", "石灯", "banner", "旗幡", "旗帜")):
        return "roadside"
    if any(term in terms for term in ("cliff", "mountain", "山崖", "悬崖", "峭壁", "山体", "远景")):
        return "background"
    if any(term in terms for term in ("road", "道路", "路面", "桥", "bridge", "platform", "平台", "台基")):
        return "surface"
    bounds = data.get("bounds", {})
    try:
        largest = max(float(bounds.get(axis, 0.0)) for axis in "xyz")
    except (TypeError, ValueError):
        largest = 0.0
    if category == "environment" and largest >= 8.0:
        return "background"
    return "obstacle"


def infer_surface_type(data: dict[str, Any]) -> str | None:
    terms = _placement_identity_terms(data)
    if any(term in terms for term in ("road", "道路", "路面", "石板路")):
        return "road"
    if any(term in terms for term in ("bridge", "桥")):
        return "bridge"
    if any(term in terms for term in ("platform", "平台", "台基")):
        return "platform"
    if any(term in terms for term in ("terrain", "地形")):
        return "terrain"
    return None


def build_placement_profile(
    data: dict[str, Any],
    existing: dict[str, Any] | None = None,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a backward-compatible semantic placement profile."""
    existing = dict(existing) if isinstance(existing, dict) else {}
    geometry = dict(geometry) if isinstance(geometry, dict) else {}
    role = str(existing.get("placementRole", "")).strip().lower()
    if role not in _PLACEMENT_ROLES:
        role = infer_placement_role(data)
    surface_type = str(existing.get("surfaceType", "")).strip().lower()
    if surface_type not in _SURFACE_TYPES and role == "surface":
        surface_type = infer_surface_type(data) or ""
    elif role != "surface":
        surface_type = ""

    bounds = data.get("bounds", {}) if isinstance(data.get("bounds"), dict) else {}
    width = max(0.0, float(bounds.get("x", 0.0) or 0.0))
    height = max(0.0, float(bounds.get("y", 0.0) or 0.0))
    depth = max(0.0, float(bounds.get("z", 0.0) or 0.0))
    radius = max(width, depth) / 2.0
    defaults = {
        "placementRole": role,
        "allowedSurfaceTypes": {
            "surface": ["terrain", "ground"],
            "occupant": ["road", "bridge", "platform", "terrain", "ground"],
            "roadside": ["terrain", "ground", "roadside"],
            "background": ["terrain", "ground", "background"],
            "obstacle": ["ground", "terrain", "platform"],
        }[role],
        "groundingMode": "bounds_bottom",
        "pivotToContact": geometry.get("pivot_to_contact", [0.0, 0.0, 0.0]),
        "contactPoints": geometry.get("contact_points", [[0.0, 0.0, 0.0]]),
        "maxSlopeDegrees": {
            "surface": 15.0,
            "occupant": 25.0,
            "roadside": 35.0,
            "background": 30.0,
            "obstacle": 25.0,
        }[role],
        "footprint": {"x": width, "z": depth},
        "minSpacing": float(data.get("placementRadius", radius) or radius),
        "preferredDistance": {
            "surface": 0.0,
            "occupant": min(2.0, max(0.75, radius)),
            "roadside": max(1.5, radius),
            "background": max(8.0, radius),
            "obstacle": max(0.5, radius),
        }[role],
        "allowedZones": {
            "surface": ["anchor"],
            "occupant": ["top"],
            "roadside": ["left_side", "right_side"],
            "background": ["left_outer", "right_outer", "backdrop"],
            "obstacle": ["top", "near"],
        }[role],
        "forbiddenZones": (
            ["top", "centerline"] if role in {"roadside", "background"} else []
        ),
        "orientationMode": "path" if role in {"occupant", "roadside"} else "free",
        "repeatable": role in {"roadside", "background", "obstacle"},
        "layoutHints": [],
    }
    if surface_type:
        defaults["surfaceType"] = surface_type
        defaults["surfaceGeometry"] = {
            "topOffset": float(geometry.get("top_offset", height)),
            "centerlineAxis": geometry.get("centerline_axis", "+Z"),
            "forward": geometry.get("forward", [0.0, 0.0, 1.0]),
            "effectiveWidth": float(geometry.get("effective_width", width)),
            "effectiveLength": float(geometry.get("effective_length", depth)),
            "hasCollider": bool(geometry.get("has_collider", False)),
            "proxySurface": not bool(geometry.get("has_collider", False)),
            "zones": ["top", "left_side", "right_side", "end"],
        }
    defaults.update(existing)
    return defaults


def _normalize_manifest(data: dict[str, Any]) -> dict[str, Any]:
    """Expose older manifests through the schema-v3 runtime view."""
    normalized = dict(data)
    tags = _string_list(normalized, "tags")
    category = str(normalized.get("category", "")).strip().lower()

    semantic = normalized.get("semanticAttributes")
    semantic = dict(semantic) if isinstance(semantic, dict) else {}
    semantic.setdefault(
        "style", [tag for tag in tags if tag in {"国风", "中式", "东方"}]
    )
    semantic.setdefault(
        "era", [tag for tag in tags if tag in {"古代", "历史"}]
    )
    semantic.setdefault("function", _string_list(normalized, "useCases"))
    semantic.setdefault("colors", [])
    semantic.setdefault("materials", [])
    semantic.setdefault("sizeClass", _infer_size_class(normalized))
    normalized["semanticAttributes"] = semantic

    placement = normalized.get("placementProfile")
    placement = dict(placement) if isinstance(placement, dict) else {}
    # Keep the legacy field readable while the planner consumes the typed list.
    if "allowedSurfaceTypes" not in placement and placement.get("allowedSurfaces"):
        placement["allowedSurfaceTypes"] = list(placement["allowedSurfaces"])
    normalized["placementProfile"] = build_placement_profile(
        normalized,
        placement,
    )
    if not isinstance(normalized.get("relations"), list):
        normalized["relations"] = []
    normalized["schemaVersion"] = max(
        3, int(normalized.get("schemaVersion", 1) or 1)
    )
    return normalized


def _build_document(data: dict[str, Any]) -> str:
    category = str(data.get("category", "")).strip()
    labels = _CATEGORY_LABELS.get(category, [])
    bounds = data.get("bounds", {})
    scale = data.get("defaultScale", [])
    semantic = data.get("semanticAttributes", {})
    placement = data.get("placementProfile", {})
    parts = [
        f"资产名称: {data.get('displayName', '')}",
        f"资产ID: {data.get('id', '')}",
        f"类别: {category} {' '.join(labels)}",
        f"别名: {' '.join(_string_list(data, 'aliases'))}",
        f"标签: {' '.join(_string_list(data, 'tags'))}",
        f"描述: {data.get('description', '')}",
        f"适用场景: {' '.join(_string_list(data, 'useCases'))}",
        f"语义属性: {json.dumps(semantic, ensure_ascii=False, sort_keys=True)}",
        f"摆放属性: {json.dumps(placement, ensure_ascii=False, sort_keys=True)}",
        f"Prefab: {data.get('prefab', '')}",
        f"模型: {data.get('model', '')}",
        f"默认缩放: {scale}",
        f"包围盒尺寸: x={bounds.get('x')} y={bounds.get('y')} z={bounds.get('z')}",
    ]
    return "\n".join(parts)


def _manifest_paths(root: Path) -> list[Path]:
    """Return standalone and bundle-entry manifests without duplicates."""
    paths = {
        path for path in root.rglob("asset.json")
        if not _is_hidden_library_path(root, path)
    }
    paths.update(
        path for path in root.rglob("*.asset.json")
        if not _is_hidden_library_path(root, path)
    )
    return sorted(paths, key=lambda path: path.as_posix())


def _is_hidden_library_path(root: Path, path: Path) -> bool:
    """Ignore atomic-publish staging/backup directories during library scans."""
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return any(part.startswith(".") for part in relative.parts[:-1])


def load_asset_records(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> list[AssetRecord]:
    root = Path(library_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Unity asset library not found: {root}")

    manifest_paths = _manifest_paths(root)
    stats = [path.stat() for path in manifest_paths]
    signature = (
        len(manifest_paths),
        max((stat.st_mtime_ns for stat in stats), default=0),
        sum(stat.st_size for stat in stats),
    )
    with _ASSET_RECORD_CACHE_LOCK:
        cached = _ASSET_RECORD_CACHE.get(root)
        if cached is not None and cached[0] == signature:
            return list(cached[1])

    records: list[AssetRecord] = []
    seen_ids: set[str] = set()
    for manifest_path in manifest_paths:
        resolved_manifest = manifest_path.resolve()
        if not _is_within(resolved_manifest, root):
            continue
        with resolved_manifest.open("r", encoding="utf-8") as handle:
            data = _normalize_manifest(json.load(handle))

        asset_id = str(data.get("id", "")).strip()
        if not asset_id:
            raise ValueError(f"Missing asset id: {resolved_manifest}")
        if asset_id in seen_ids:
            raise ValueError(f"Duplicate asset id '{asset_id}': {resolved_manifest}")
        seen_ids.add(asset_id)

        asset_root = resolved_manifest.parent
        for key in ("prefab", "model", "material"):
            relative_path = str(data.get(key, "")).strip()
            if not relative_path:
                raise ValueError(f"Missing '{key}' in {resolved_manifest}")
            dependency = _resolve_child_path(asset_root, relative_path)
            if not dependency.is_file():
                raise FileNotFoundError(
                    f"Missing {key} for {asset_id}: {dependency}"
                )

        records.append(
            AssetRecord(
                asset_id=asset_id,
                manifest_path=resolved_manifest,
                root_path=asset_root,
                data=data,
                document=_build_document(data),
            )
        )
    with _ASSET_RECORD_CACHE_LOCK:
        _ASSET_RECORD_CACHE[root] = (signature, tuple(records))
    return records


def write_registry(
    records: list[AssetRecord],
    registry_path: Path | str = DEFAULT_REGISTRY_PATH,
) -> Path:
    path = Path(registry_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "collection": COLLECTION_NAME,
        "assetCount": len(records),
        "assets": [record.public_dict() for record in records],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _local_hash_embeddings(texts: list[str]) -> np.ndarray:
    """Create deterministic offline vectors from character n-grams."""
    vectors = np.zeros((len(texts), LOCAL_HASH_DIMENSION), dtype=np.float32)
    for row, text in enumerate(texts):
        normalized = " ".join(text.lower().split())
        features: list[str] = []
        for size in (1, 2, 3):
            features.extend(
                normalized[index : index + size]
                for index in range(max(0, len(normalized) - size + 1))
            )
        for feature in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8"), digest_size=8
            ).digest()
            value = int.from_bytes(digest, "little")
            column = value % LOCAL_HASH_DIMENSION
            sign = 1.0 if value & 1 else -1.0
            vectors[row, column] += sign
        norm = float(np.linalg.norm(vectors[row]))
        if norm:
            vectors[row] /= norm
    return vectors


def create_embeddings(
    texts: list[str],
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    show_progress_bar: bool = False,
) -> np.ndarray:
    if provider == "local-hash":
        return _local_hash_embeddings(texts)
    if provider == "bge-m3":
        from services.rag.embedding_manager import get_embedding_manager

        return get_embedding_manager().encode(
            texts,
            batch_size=min(16, max(1, len(texts))),
            show_progress_bar=show_progress_bar,
        )
    raise ValueError("embedding provider must be 'local-hash' or 'bge-m3'")


def _index_state_path(index_dir: Path | str) -> Path:
    return Path(index_dir).resolve() / INDEX_STATE_FILENAME


def load_asset_index_state(
    index_dir: Path | str = DEFAULT_INDEX_DIR,
) -> dict[str, Any]:
    path = _index_state_path(index_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            collection = str(data.get("active_collection", "")).strip()
            if collection:
                return data
        except (OSError, ValueError):
            pass
    return {
        "schema_version": 1,
        "active_collection": COLLECTION_NAME,
        "embedding_provider": "local-hash",
        "index_schema_version": 1,
    }


def _write_asset_index_state(
    index_dir: Path | str,
    *,
    collection_name: str,
    embedding_provider: str,
    evaluation: dict[str, Any],
) -> Path:
    path = _index_state_path(index_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_collection": collection_name,
                "embedding_provider": embedding_provider,
                "index_schema_version": INDEX_SCHEMA_VERSION,
                "evaluation": evaluation,
                "activated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    return path


def active_asset_collection_name(
    index_dir: Path | str = DEFAULT_INDEX_DIR,
) -> str:
    return str(load_asset_index_state(index_dir)["active_collection"])


def _shadow_collection_name(provider: str) -> str:
    safe_provider = re.sub(r"[^a-z0-9]+", "_", provider.lower()).strip("_")
    return f"{COLLECTION_NAME}_{safe_provider}_v{INDEX_SCHEMA_VERSION}"


def _evaluate_asset_collection(
    collection: Any,
    records: list[AssetRecord],
    provider: str,
    limit: int = 50,
) -> dict[str, Any]:
    sample = records[: max(1, min(limit, len(records)))]
    if not sample:
        return {"passed": True, "query_count": 0, "top1_accuracy": 1.0}
    queries = [str(record.data.get("displayName", record.asset_id)) for record in sample]
    embeddings = create_embeddings(queries, provider)
    correct = 0
    for record, embedding in zip(sample, embeddings):
        result = collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=1,
            include=[],
        )
        ids = result.get("ids", [[]])[0]
        if ids and ids[0] == record.asset_id:
            correct += 1
    accuracy = correct / len(sample)
    return {
        "passed": accuracy >= 0.95,
        "query_count": len(sample),
        "top1_correct": correct,
        "top1_accuracy": round(accuracy, 4),
        "threshold": 0.95,
    }


def index_asset_library(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    rebuild: bool = False,
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER,
    progress: Callable[[str], None] | None = None,
    shadow: bool = True,
    activate: bool = True,
    evaluation_limit: int = 50,
) -> dict[str, Any]:
    def report(message: str) -> None:
        if progress:
            progress(message)

    report("[1/6] Scanning asset.json manifests...")
    records = load_asset_records(library_root)
    report(f"      Found {len(records)} valid assets.")

    report("[2/6] Writing the readable asset registry...")
    registry_path = write_registry(records)
    report(f"      Registry: {registry_path}")

    import chromadb

    report("[3/6] Opening the dedicated ChromaDB collection...")
    persist_path = Path(index_dir).resolve()
    persist_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_path))
    current_state = load_asset_index_state(persist_path)
    active_name = str(current_state["active_collection"])
    target_name = (
        _shadow_collection_name(embedding_provider)
        if rebuild and shadow
        else active_name
    )
    if rebuild:
        try:
            client.delete_collection(target_name)
        except Exception:
            pass

    try:
        collection = client.get_collection(target_name)
        current_provider = (collection.metadata or {}).get("embedding_provider")
        if collection.count() == 0 and current_provider != embedding_provider:
            client.delete_collection(COLLECTION_NAME)
            collection = client.create_collection(
                target_name,
                metadata={
                    "embedding_provider": embedding_provider,
                    "schema_version": INDEX_SCHEMA_VERSION,
                },
            )
        elif current_provider != embedding_provider:
            raise ValueError(
                f"Collection uses embedding provider '{current_provider}', "
                f"requested '{embedding_provider}'. Run with rebuild=True."
            )
    except ValueError:
        raise
    except Exception:
        collection = client.create_collection(
            target_name,
            metadata={
                "embedding_provider": embedding_provider,
                "schema_version": INDEX_SCHEMA_VERSION,
            },
        )

    if records:
        report(
            f"[4/6] Creating vectors with '{embedding_provider}' "
            f"for {len(records)} assets..."
        )
        documents = [record.document for record in records]
        embeddings = create_embeddings(
            documents, embedding_provider, show_progress_bar=True
        )
        report("[5/6] Upserting assets into ChromaDB...")
        collection.upsert(
            ids=[record.asset_id for record in records],
            documents=documents,
            metadatas=[record.metadata() for record in records],
            embeddings=embeddings.tolist(),
        )
    else:
        report("[4/6] No assets found; skipping vector creation.")
        report("[5/6] Nothing to upsert.")

    report("[6/6] Evaluating the candidate index...")
    evaluation = _evaluate_asset_collection(
        collection,
        records,
        embedding_provider,
        limit=evaluation_limit,
    )
    state_path: Path | None = None
    activated = False
    if activate and evaluation["passed"]:
        state_path = _write_asset_index_state(
            persist_path,
            collection_name=target_name,
            embedding_provider=embedding_provider,
            evaluation=evaluation,
        )
        activated = True
    elif activate:
        report("Candidate index did not meet the activation threshold; keeping the old index.")

    report(f"Done. Collection now contains {collection.count()} assets.")

    return {
        "success": True,
        "collection": target_name,
        "previous_collection": active_name,
        "active_collection": target_name if activated else active_name,
        "activated": activated,
        "state_path": str(state_path) if state_path else None,
        "evaluation": evaluation,
        "embedding_provider": embedding_provider,
        "asset_count": len(records),
        "indexed_count": collection.count(),
        "library_root": str(Path(library_root).resolve()),
        "index_dir": str(persist_path),
        "registry_path": str(registry_path),
        "assets": [
            {
                "asset_id": record.asset_id,
                "display_name": record.data.get("displayName", ""),
                "category": record.data.get("category", ""),
            }
            for record in records
        ],
    }


def index_asset_library_records(
    asset_ids: list[str] | set[str],
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Incrementally upsert selected records using the collection's provider."""
    wanted = {str(asset_id).strip() for asset_id in asset_ids if str(asset_id).strip()}
    records = load_asset_records(library_root)
    selected = [record for record in records if record.asset_id in wanted]
    missing_requested = sorted(wanted - {record.asset_id for record in selected})
    if missing_requested:
        raise KeyError(
            f"Asset ids not found for indexing: {', '.join(missing_requested)}"
        )

    registry_path = write_registry(records)
    if progress:
        progress(f"Writing {len(selected)} changed asset vectors...")

    import chromadb

    persist_path = Path(index_dir).resolve()
    persist_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_path))
    collection_name = active_asset_collection_name(persist_path)
    try:
        collection = client.get_collection(collection_name)
        provider = (collection.metadata or {}).get(
            "embedding_provider", DEFAULT_EMBEDDING_PROVIDER
        )
    except Exception:
        provider = DEFAULT_EMBEDDING_PROVIDER
        collection = client.create_collection(
            collection_name,
            metadata={
                "embedding_provider": provider,
                "schema_version": INDEX_SCHEMA_VERSION,
            },
        )

    try:
        existing_ids = set(collection.get().get("ids", []))
    except Exception:
        existing_ids = set()
    selected_ids = {record.asset_id for record in selected}
    missing_records = [
        record
        for record in records
        if record.asset_id not in existing_ids
        and record.asset_id not in selected_ids
    ]
    selected.extend(missing_records)
    if progress and missing_records:
        progress(
            f"Also backfilling {len(missing_records)} records missing from "
            "the existing collection."
        )

    if selected:
        documents = [record.document for record in selected]
        embeddings = create_embeddings(
            documents, provider, show_progress_bar=True
        )
        collection.upsert(
            ids=[record.asset_id for record in selected],
            documents=documents,
            metadatas=[record.metadata() for record in selected],
            embeddings=embeddings.tolist(),
        )
    return {
        "success": True,
        "collection": collection_name,
        "embedding_provider": provider,
        "upserted_count": len(selected),
        "backfilled_count": len(missing_records),
        "indexed_count": collection.count(),
        "registry_path": str(registry_path),
    }


def _search_text(record: AssetRecord) -> str:
    values = [
        record.asset_id,
        str(record.data.get("displayName", "")),
        str(record.data.get("description", "")),
        *_string_list(record.data, "aliases"),
        *_string_list(record.data, "tags"),
        *_string_list(record.data, "useCases"),
        *_CATEGORY_LABELS.get(str(record.data.get("category", "")), []),
    ]
    return " ".join(values).lower()


def _lexical_score(query: str, record: AssetRecord) -> float:
    normalized = query.strip().lower()
    if not normalized:
        return 0.0
    score = 0.0
    display_name = str(record.data.get("displayName", "")).lower()
    if normalized == display_name or normalized == record.asset_id.lower():
        score += 100.0
    if display_name and display_name in normalized:
        score += 40.0
    aliases = [alias.lower() for alias in _string_list(record.data, "aliases")]
    for alias in aliases:
        if normalized == alias:
            score += 80.0
        elif alias in normalized or (len(normalized) >= 2 and normalized in alias):
            score += 25.0
    for tag in _string_list(record.data, "tags"):
        if tag.lower() in normalized:
            score += 10.0
    searchable = _search_text(record)
    for token in normalized.replace(",", " ").replace("，", " ").split():
        if token in searchable:
            score += 2.0
    # Chinese queries are commonly written without spaces. Character n-grams
    # keep lexical fallback useful when the vector index is unavailable or stale.
    compact_query = re.sub(r"[^\w]+", "", normalized, flags=re.UNICODE)
    compact_searchable = re.sub(
        r"[^\w]+", "", searchable, flags=re.UNICODE
    )
    for size, weight in ((2, 1.5), (3, 3.0)):
        query_grams = {
            compact_query[index : index + size]
            for index in range(max(0, len(compact_query) - size + 1))
        }
        searchable_grams = {
            compact_searchable[index : index + size]
            for index in range(max(0, len(compact_searchable) - size + 1))
        }
        score += min(30.0, len(query_grams & searchable_grams) * weight)
    # Names and aliases are substantially stronger evidence than description
    # n-grams, especially for compact Chinese queries such as "古代木水桶".
    identity_values = [display_name, *aliases]
    for identity in identity_values:
        compact_identity = re.sub(r"[^\w]+", "", identity, flags=re.UNICODE)
        if not compact_identity:
            continue
        for size, weight in ((2, 3.0), (3, 8.0)):
            query_grams = {
                compact_query[index : index + size]
                for index in range(max(0, len(compact_query) - size + 1))
            }
            identity_grams = {
                compact_identity[index : index + size]
                for index in range(max(0, len(compact_identity) - size + 1))
            }
            score += min(36.0, len(query_grams & identity_grams) * weight)
    return score


def _variant_cue_score(query: str, record: AssetRecord) -> tuple[float, list[str]]:
    normalized = query.lower()
    searchable = _search_text(record)
    score = 0.0
    reasons: list[str] = []
    cue_groups = {
        "large": (["大型", "巨大", "巨型", "高耸"], ["大型", "巨大", "巨型", "高耸", "参天"]),
        "preset": (["组合", "整套", "快速搭建"], ["组合", "预设", "preset"]),
        "wide": (["宽阔", "宽大"], ["宽阔", "宽大", "横展", "宽冠"]),
        "yellow": (["金黄", "黄色", "金色"], ["金黄", "黄色", "金色"]),
        "purple": (["紫红", "紫色"], ["紫红", "紫色"]),
        "red": (["橙红", "红色"], ["橙红", "红色"]),
        "green": (["青绿", "绿色", "青色"], ["青绿", "绿色", "青色"]),
    }
    for name, (query_terms, asset_terms) in cue_groups.items():
        if any(term in normalized for term in query_terms) and any(
            term in searchable for term in asset_terms
        ):
            score += 1.0
            reasons.append(f"variant_cue:{name}")
    for marker in ("一型", "二型", "三型", "四型", "五型", "六型"):
        if marker in normalized and marker in searchable:
            score += 1.0
            reasons.append(f"variant_cue:{marker}")
    return min(1.0, score / 2.0), reasons


def _normalize_scores(values: dict[str, float]) -> dict[str, float]:
    maximum = max(values.values(), default=0.0)
    if maximum <= 0:
        return {key: 0.0 for key in values}
    return {key: max(0.0, value) / maximum for key, value in values.items()}


def _matches_asset_filters(
    record: AssetRecord,
    filters: dict[str, Any],
) -> bool:
    if not filters:
        return True
    data = record.data
    included = {str(item) for item in filters.get("assetIds", [])}
    excluded = {str(item) for item in filters.get("excludeAssetIds", [])}
    if included and record.asset_id not in included:
        return False
    if record.asset_id in excluded:
        return False
    required_tags = {
        str(item).strip().lower() for item in filters.get("tags", [])
        if str(item).strip()
    }
    tags = {item.lower() for item in _string_list(data, "tags")}
    if required_tags and not required_tags.issubset(tags):
        return False
    semantic = data.get("semanticAttributes", {})
    size_class = str(filters.get("sizeClass", "")).strip().lower()
    if size_class and str(semantic.get("sizeClass", "")).lower() != size_class:
        return False
    colors = {
        str(item).strip().lower() for item in filters.get("colors", [])
        if str(item).strip()
    }
    asset_colors = {
        str(item).strip().lower() for item in semantic.get("colors", [])
        if str(item).strip()
    }
    if colors and not colors.intersection(asset_colors):
        return False
    bounds = data.get("bounds", {})
    for filter_key, comparator in (
        ("minBounds", lambda actual, expected: actual >= expected),
        ("maxBounds", lambda actual, expected: actual <= expected),
    ):
        expected_bounds = filters.get(filter_key)
        if not isinstance(expected_bounds, dict):
            continue
        for axis in "xyz":
            if axis not in expected_bounds:
                continue
            try:
                if not comparator(
                    float(bounds.get(axis, 0.0)),
                    float(expected_bounds[axis]),
                ):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _attribute_score(query: str, record: AssetRecord) -> tuple[float, list[str]]:
    normalized = query.lower()
    data = record.data
    semantic = data.get("semanticAttributes", {})
    score = 0.0
    reasons: list[str] = []
    for field in ("style", "era", "function", "colors", "materials"):
        value = semantic.get(field, [])
        values = value if isinstance(value, list) else [value]
        matches = [str(item) for item in values if str(item) and str(item).lower() in normalized]
        if matches:
            score += min(12.0, len(matches) * 4.0)
            reasons.append(f"attribute:{field}={','.join(matches)}")
    size_class = str(semantic.get("sizeClass", ""))
    size_aliases = {
        "tiny": ["微小", "小件"],
        "small": ["小型", "较小"],
        "medium": ["中型"],
        "large": ["大型", "较大"],
        "huge": ["巨型", "高耸", "巨大"],
    }
    if any(alias in normalized for alias in size_aliases.get(size_class, [])):
        score += 6.0
        reasons.append(f"attribute:sizeClass={size_class}")
    return score, reasons


def _confidence(score: float, next_score: float, exact: bool) -> float:
    if exact:
        return 1.0
    gap = max(0.0, score - next_score)
    return round(min(0.99, 0.25 + min(score, 80.0) / 160.0 + min(gap, 30.0) / 60.0), 4)


def search_asset_library(
    query: str,
    category: str = "",
    top_k: int = 5,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    index_dir: Path | str = DEFAULT_INDEX_DIR,
    use_vector: bool = True,
    filters: dict[str, Any] | None = None,
    expand_relations: bool = False,
    diversify_variants: bool = False,
    candidate_count: int = 30,
) -> dict[str, Any]:
    records = load_asset_records(library_root)
    filters = filters or {}
    if category:
        wanted = category.strip().lower()
        records = [
            record
            for record in records
            if str(record.data.get("category", "")).lower() == wanted
            or wanted
            in _CATEGORY_LABELS.get(str(record.data.get("category", "")), [])
        ]

    records = [record for record in records if _matches_asset_filters(record, filters)]

    lexical_scores = {
        record.asset_id: _lexical_score(query, record) for record in records
    }
    attribute_scores: dict[str, float] = {}
    variant_scores: dict[str, float] = {}
    reasons: dict[str, list[str]] = {}
    for record in records:
        attribute_score, attribute_reasons = _attribute_score(query, record)
        variant_score, variant_reasons = _variant_cue_score(query, record)
        attribute_scores[record.asset_id] = attribute_score
        variant_scores[record.asset_id] = variant_score
        reasons[record.asset_id] = attribute_reasons + variant_reasons
        if lexical_scores[record.asset_id] > 0:
            reasons[record.asset_id].append("lexical_match")
    distances: dict[str, float] = {}
    vector_scores: dict[str, float] = {}
    graph_scores: dict[str, float] = {}
    vector_error = ""

    if use_vector and records:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(Path(index_dir).resolve()))
            collection_name = active_asset_collection_name(index_dir)
            collection = client.get_collection(collection_name)
            if collection.count() > 0:
                provider = (collection.metadata or {}).get(
                    "embedding_provider", DEFAULT_EMBEDDING_PROVIDER
                )
                embedding = create_embeddings([query], provider)[0]
                kwargs: dict[str, Any] = {
                    "query_embeddings": [embedding.tolist()],
                    "n_results": min(
                        max(1, int(candidate_count)), collection.count()
                    ),
                    "include": ["distances"],
                }
                if category and category.isascii():
                    kwargs["where"] = {"category": category}
                raw = collection.query(**kwargs)
                for asset_id, distance in zip(
                    raw.get("ids", [[]])[0],
                    raw.get("distances", [[]])[0],
                ):
                    if asset_id not in lexical_scores:
                        continue
                    distances[asset_id] = float(distance)
                    vector_score = 1.0 / (1.0 + max(0.0, float(distance)))
                    vector_scores[asset_id] = vector_score
                    reasons.setdefault(asset_id, []).append("vector_match")
        except Exception as exc:
            vector_error = str(exc)

    asset_ids = [record.asset_id for record in records]
    lexical_normalized = _normalize_scores(lexical_scores)
    vector_normalized = _normalize_scores(
        {asset_id: vector_scores.get(asset_id, 0.0) for asset_id in asset_ids}
    )
    attribute_combined = {
        asset_id: attribute_scores.get(asset_id, 0.0)
        + variant_scores.get(asset_id, 0.0) * 12.0
        for asset_id in asset_ids
    }
    attribute_normalized = _normalize_scores(attribute_combined)
    preliminary_scores = {
        asset_id: (
            lexical_normalized.get(asset_id, 0.0) * 45.0
            + vector_normalized.get(asset_id, 0.0) * 30.0
            + attribute_normalized.get(asset_id, 0.0) * 20.0
        )
        for asset_id in asset_ids
    }

    if expand_relations and preliminary_scores:
        try:
            from services.asset_graph_service import graph_expansion_scores

            seeds = dict(
                sorted(
                    preliminary_scores.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:10]
            )
            graph_scores, graph_reasons = graph_expansion_scores(
                seeds,
                library_root=library_root,
            )
            for asset_id, bonus in graph_scores.items():
                if asset_id in preliminary_scores and bonus > 0:
                    reasons.setdefault(asset_id, []).extend(
                        graph_reasons.get(asset_id, [])
                    )
        except Exception as exc:
            reasons.setdefault("_graph", []).append(str(exc))

    graph_normalized = _normalize_scores(
        {asset_id: graph_scores.get(asset_id, 0.0) for asset_id in asset_ids}
    )
    scores = {
        asset_id: preliminary_scores.get(asset_id, 0.0)
        + graph_normalized.get(asset_id, 0.0) * 5.0
        for asset_id in asset_ids
    }

    by_id = {record.asset_id: record for record in records}
    normalized_query = query.strip().lower()
    exact_matches = {
        asset_id
        for asset_id, record in by_id.items()
        if normalized_query
        in {
            asset_id.lower(),
            str(record.data.get("displayName", "")).strip().lower(),
        }
    }
    ranked_ids = sorted(
        by_id,
        key=lambda asset_id: (
            asset_id in exact_matches,
            scores.get(asset_id, 0.0),
            -distances.get(asset_id, 999.0),
        ),
        reverse=True,
    )

    if diversify_variants:
        diversified: list[str] = []
        deferred: list[str] = []
        seen_variants: set[str] = set()
        for asset_id in ranked_ids:
            variant = str(by_id[asset_id].data.get("variantGroup", ""))
            if variant and variant in seen_variants:
                deferred.append(asset_id)
                continue
            diversified.append(asset_id)
            if variant:
                seen_variants.add(variant)
        ranked_ids = diversified + deferred

    ranked_ids = ranked_ids[: max(1, min(top_k, 20))]

    results = []
    for index, asset_id in enumerate(ranked_ids):
        record = by_id[asset_id]
        item = record.public_dict()
        item["score"] = round(scores.get(asset_id, 0.0), 4)
        item["lexicalScore"] = round(lexical_scores.get(asset_id, 0.0), 4)
        item["vectorScore"] = round(vector_scores.get(asset_id, 0.0), 4)
        item["attributeScore"] = round(attribute_scores.get(asset_id, 0.0), 4)
        item["variantCueScore"] = round(variant_scores.get(asset_id, 0.0), 4)
        item["graphScore"] = round(graph_scores.get(asset_id, 0.0), 4)
        item["normalizedScores"] = {
            "lexical": round(lexical_normalized.get(asset_id, 0.0), 6),
            "vector": round(vector_normalized.get(asset_id, 0.0), 6),
            "attribute": round(attribute_normalized.get(asset_id, 0.0), 6),
            "graph": round(graph_normalized.get(asset_id, 0.0), 6),
            "weightedTotal": round(scores.get(asset_id, 0.0), 6),
        }
        item["rerankVersion"] = ASSET_RERANK_VERSION
        next_score = (
            scores.get(ranked_ids[index + 1], 0.0)
            if index + 1 < len(ranked_ids)
            else 0.0
        )
        exact = asset_id in exact_matches
        item["confidence"] = (
            _confidence(item["score"], next_score, exact)
            if index == 0
            else round(min(0.95, 0.15 + item["score"] / 100.0), 4)
        )
        item["matchReasons"] = reasons.get(asset_id, [])
        item["vectorDistance"] = (
            round(distances[asset_id], 6) if asset_id in distances else None
        )
        results.append(item)

    return {
        "success": True,
        "query": query,
        "category": category or None,
        "result_count": len(results),
        "results": results,
        "vector_search_used": bool(distances),
        "vector_error": vector_error or None,
        "filters": filters,
        "relations_expanded": expand_relations,
        "active_collection": active_asset_collection_name(index_dir),
        "rerankVersion": ASSET_RERANK_VERSION,
        "scoreWeights": {
            "lexical": 0.45,
            "vector": 0.30,
            "attribute": 0.20,
            "graph": 0.05,
        },
    }


def get_asset_record(
    asset_id: str,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> AssetRecord:
    for record in load_asset_records(library_root):
        if record.asset_id == asset_id:
            return record
    raise KeyError(f"Asset not found in library: {asset_id}")


def _read_meta_guid(path: Path) -> str:
    try:
        match = _META_GUID_PATTERN.search(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return ""
    return match.group(1).lower() if match else ""


def find_project_guid_conflicts(
    source_root: Path | str,
    project_assets_root: Path | str,
    excluded_root: Path | str | None = None,
) -> dict[str, Any]:
    """Find source Unity GUIDs already used elsewhere in a project."""
    source = Path(source_root).resolve()
    assets_root = Path(project_assets_root).resolve()
    excluded = Path(excluded_root).resolve() if excluded_root else None

    source_guid_paths: dict[str, list[Path]] = {}
    for meta_path in source.rglob("*.meta"):
        guid = _read_meta_guid(meta_path)
        if guid:
            source_guid_paths.setdefault(guid, []).append(meta_path.resolve())

    duplicate_source_guids = {
        guid: paths
        for guid, paths in source_guid_paths.items()
        if len(paths) > 1
    }
    if duplicate_source_guids:
        details = "; ".join(
            f"{guid}: {', '.join(str(path) for path in paths)}"
            for guid, paths in sorted(duplicate_source_guids.items())
        )
        raise ValueError(f"Source asset contains duplicate Unity GUIDs: {details}")

    conflicts: list[dict[str, Any]] = []
    scanned_meta_count = 0
    wanted_guids = set(source_guid_paths)
    if wanted_guids:
        for meta_path in assets_root.rglob("*.meta"):
            resolved_meta = meta_path.resolve()
            if excluded and _is_within(resolved_meta, excluded):
                continue
            scanned_meta_count += 1
            guid = _read_meta_guid(resolved_meta)
            if guid not in wanted_guids:
                continue
            conflicts.append(
                {
                    "guid": guid,
                    "source_meta_paths": [
                        str(path) for path in source_guid_paths[guid]
                    ],
                    "project_meta_path": str(resolved_meta),
                }
            )

    return {
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "source_guid_count": len(source_guid_paths),
        "scanned_project_meta_count": scanned_meta_count,
    }


def _prefab_root_scale(path: Path) -> list[float] | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    scale_values: dict[str, float] = {}
    pattern = re.compile(
        r"propertyPath:\s*m_LocalScale\.([xyz])\s*\r?\n"
        r"\s*value:\s*([-+0-9.eE]+)"
    )
    for axis, value in pattern.findall(text):
        try:
            scale_values[axis] = float(value)
        except ValueError:
            pass
    if all(axis in scale_values for axis in "xyz"):
        return [scale_values["x"], scale_values["y"], scale_values["z"]]

    inline = re.search(
        r"m_LocalScale:\s*\{\s*x:\s*([-+0-9.eE]+),\s*"
        r"y:\s*([-+0-9.eE]+),\s*z:\s*([-+0-9.eE]+)\s*\}",
        text,
    )
    if inline:
        return [float(value) for value in inline.groups()]
    return None


def validate_asset_library(
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    """Validate manifests, files, Unity GUIDs, and placement metadata."""
    root = Path(library_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Unity asset library not found: {root}")

    guid_paths: dict[str, list[Path]] = {}
    for meta_path in root.rglob("*.meta"):
        if _is_hidden_library_path(root, meta_path):
            continue
        guid = _read_meta_guid(meta_path)
        if guid:
            guid_paths.setdefault(guid, []).append(meta_path.resolve())

    global_errors: list[str] = []
    duplicate_guids = {
        guid: paths for guid, paths in guid_paths.items() if len(paths) > 1
    }
    for guid, paths in sorted(duplicate_guids.items()):
        global_errors.append(
            f"Duplicate GUID {guid}: "
            + ", ".join(str(path) for path in paths)
        )

    assets: list[dict[str, Any]] = []
    seen_ids: dict[str, Path] = {}
    required_fields = (
        "schemaVersion",
        "id",
        "displayName",
        "category",
        "prefab",
        "model",
        "material",
        "sourceModelGuid",
        "defaultScale",
        "bounds",
    )

    for manifest_path in _manifest_paths(root):
        asset_errors: list[str] = []
        warnings: list[str] = []
        manifest_path = manifest_path.resolve()
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            assets.append(
                {
                    "asset_id": None,
                    "manifest_path": str(manifest_path),
                    "valid": False,
                    "errors": [f"Invalid manifest JSON: {exc}"],
                    "warnings": [],
                }
            )
            continue

        asset_id = str(data.get("id", "")).strip()
        for field in required_fields:
            if field not in data or data[field] in ("", None):
                asset_errors.append(f"Missing required field: {field}")

        if asset_id:
            if asset_id in seen_ids:
                asset_errors.append(
                    f"Duplicate asset id also used by {seen_ids[asset_id]}"
                )
            else:
                seen_ids[asset_id] = manifest_path

        asset_root = manifest_path.parent
        resolved_paths: dict[str, Path] = {}
        for field in ("prefab", "model", "material"):
            relative = str(data.get(field, "")).strip()
            if not relative:
                continue
            try:
                resolved = _resolve_child_path(asset_root, relative)
                resolved_paths[field] = resolved
                if not resolved.is_file():
                    asset_errors.append(f"Missing {field} file: {resolved}")
            except ValueError as exc:
                asset_errors.append(str(exc))

        scale = data.get("defaultScale")
        if (
            not isinstance(scale, list)
            or len(scale) != 3
            or not all(
                isinstance(value, (int, float))
                and math.isfinite(float(value))
                and float(value) > 0
                for value in scale
            )
        ):
            asset_errors.append(
                "defaultScale must contain 3 finite positive numbers"
            )

        bounds = data.get("bounds")
        if (
            not isinstance(bounds, dict)
            or not all(
                isinstance(bounds.get(axis), (int, float))
                and math.isfinite(float(bounds[axis]))
                and float(bounds[axis]) > 0
                for axis in "xyz"
            )
        ):
            asset_errors.append(
                "bounds must contain finite positive x, y, and z values"
            )

        source_guid = str(data.get("sourceModelGuid", "")).lower()
        if source_guid and not re.fullmatch(r"[0-9a-f]{32}", source_guid):
            asset_errors.append("sourceModelGuid must be a 32-character hex GUID")
        model_path = resolved_paths.get("model")
        if model_path and model_path.is_file():
            model_guid = _read_meta_guid(Path(str(model_path) + ".meta"))
            if not model_guid:
                asset_errors.append(f"Missing or invalid model meta: {model_path}.meta")
            elif source_guid and source_guid != model_guid:
                asset_errors.append(
                    "sourceModelGuid does not match the model .meta GUID"
                )

        referenced_guids: set[str] = set()
        for path in asset_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _TEXT_ASSET_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            referenced_guids.update(
                match.lower() for match in _GUID_PATTERN.findall(text)
            )
        allowed_external_guids: set[str] = set()
        bundle_metadata_path = asset_root / ".asset-library-bundle.json"
        if bundle_metadata_path.is_file():
            try:
                bundle_metadata = json.loads(
                    bundle_metadata_path.read_text(encoding="utf-8")
                )
                for dependency in bundle_metadata.get(
                    "packageDependencies", []
                ):
                    if isinstance(dependency, dict):
                        guid = str(dependency.get("guid", "")).lower()
                        if re.fullmatch(r"[0-9a-f]{32}", guid):
                            allowed_external_guids.add(guid)
            except (OSError, ValueError):
                warnings.append("Bundle metadata could not be read")
        unresolved = sorted(
            guid
            for guid in referenced_guids
            if not guid.startswith("0000000000000000")
            and guid not in guid_paths
            and guid not in allowed_external_guids
        )
        for guid in unresolved:
            asset_errors.append(f"Unresolved Unity GUID reference: {guid}")

        prefab_path = resolved_paths.get("prefab")
        prefab_scale = (
            _prefab_root_scale(prefab_path)
            if prefab_path and prefab_path.is_file()
            else None
        )
        if prefab_scale and any(
            abs(value - 1.0) > 0.0001 for value in prefab_scale
        ):
            warnings.append(
                "Prefab root scale is not [1, 1, 1]; keep defaultScale "
                "synchronized or normalize in a future asset revision"
            )
        if (
            prefab_scale
            and isinstance(scale, list)
            and len(scale) == 3
            and all(isinstance(value, (int, float)) for value in scale)
            and any(
                abs(prefab_scale[index] - float(scale[index])) > 0.0001
                for index in range(3)
            )
        ):
            warnings.append(
                f"Prefab root scale {prefab_scale} differs from "
                f"defaultScale {scale}"
            )

        for field, default in (
            ("groundOffset", 0.0),
            ("forwardAxis", "+Z"),
            ("placementRadius", "bounds-based"),
        ):
            if field not in data:
                warnings.append(
                    f"{field} is missing; runtime default will be {default}"
                )

        assets.append(
            {
                "asset_id": asset_id or None,
                "display_name": data.get("displayName"),
                "manifest_path": str(manifest_path),
                "valid": not asset_errors,
                "errors": asset_errors,
                "warnings": warnings,
                "prefab_root_scale": prefab_scale,
                "resolved_guid_count": len(referenced_guids) - len(unresolved),
                "unresolved_guid_count": len(unresolved),
            }
        )

    error_count = len(global_errors) + sum(
        len(asset["errors"]) for asset in assets
    )
    warning_count = sum(len(asset["warnings"]) for asset in assets)
    return {
        "success": True,
        "valid": error_count == 0,
        "library_root": str(root),
        "asset_count": len(assets),
        "error_count": error_count,
        "warning_count": warning_count,
        "global_errors": global_errors,
        "duplicate_guid_count": len(duplicate_guids),
        "assets": assets,
    }


def normalize_unity_project_root(path: Path | str) -> Path:
    project_path = Path(path).expanduser().resolve()
    if project_path.name.lower() == "assets":
        project_path = project_path.parent
    if not (project_path / "Assets").is_dir():
        raise ValueError(f"Unity project Assets directory not found: {project_path}")
    if not (project_path / "ProjectSettings").is_dir():
        raise ValueError(f"Unity ProjectSettings directory not found: {project_path}")
    return project_path


def _asset_source_files(root: Path) -> list[Path]:
    return [
        path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file() and path.name != IMPORT_METADATA_FILENAME
    ]


def calculate_asset_content_hash(
    root: Path | str,
    relative_paths: list[Path] | None = None,
) -> str:
    """Hash asset-relative file names and bytes in deterministic order."""
    resolved_root = Path(root).resolve()
    if relative_paths is None:
        relative_paths = [
            path.relative_to(resolved_root)
            for path in _asset_source_files(resolved_root)
        ]

    digest = hashlib.sha256()
    for relative_path in sorted(relative_paths, key=lambda item: item.as_posix()):
        path = _resolve_child_path(resolved_root, relative_path.as_posix())
        if not path.is_file():
            raise FileNotFoundError(f"Asset hash input not found: {path}")
        encoded_path = relative_path.as_posix().encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _read_import_metadata(target_root: Path) -> dict[str, Any]:
    path = target_root / IMPORT_METADATA_FILENAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_import_metadata(
    target_root: Path,
    asset_id: str,
    content_hash: str,
    import_key: str | None = None,
) -> None:
    payload = {
        "schemaVersion": 1,
        "assetId": asset_id,
        "importKey": import_key or asset_id,
        "contentHash": content_hash,
        "importedAt": datetime.now(timezone.utc).isoformat(),
    }
    (target_root / IMPORT_METADATA_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _replace_asset_directory(
    source_root: Path,
    target_root: Path,
    asset_id: str,
    content_hash: str,
    import_key: str | None = None,
) -> None:
    target_root.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staging = target_root.parent / f".{target_root.name}.import-{token}"
    backup = target_root.parent / f".{target_root.name}.backup-{token}"
    try:
        shutil.copytree(source_root, staging, copy_function=shutil.copy2)
        _write_import_metadata(
            staging,
            asset_id,
            content_hash,
            import_key=import_key,
        )
        if target_root.exists():
            target_root.rename(backup)
        staging.rename(target_root)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target_root.exists() and backup.exists():
            shutil.rmtree(target_root)
        if backup.exists() and not target_root.exists():
            backup.rename(target_root)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and target_root.exists():
            shutil.rmtree(backup)


def _matching_existing_project_prefab(
    record: AssetRecord,
    guid_scan: dict[str, Any],
    project_root: Path,
) -> Path | None:
    """Reuse an identical source asset pack already installed in a project."""
    conflicts = guid_scan.get("conflicts", [])
    source_guid_count = int(guid_scan.get("source_guid_count", 0))
    if source_guid_count <= 0 or len(conflicts) != source_guid_count:
        return None

    source_prefab = _resolve_child_path(
        record.root_path, str(record.data["prefab"])
    )
    source_prefab_meta = Path(str(source_prefab) + ".meta").resolve()
    matched_prefab: Path | None = None

    for conflict in conflicts:
        source_meta_paths = [
            Path(path).resolve()
            for path in conflict.get("source_meta_paths", [])
        ]
        if len(source_meta_paths) != 1:
            return None
        source_meta = source_meta_paths[0]
        project_meta = Path(str(conflict.get("project_meta_path", ""))).resolve()
        source_asset = Path(str(source_meta)[:-5])
        project_asset = Path(str(project_meta)[:-5])
        if (
            not source_meta.is_file()
            or not project_meta.is_file()
            or not source_asset.is_file()
            or not project_asset.is_file()
            or source_meta.read_bytes() != project_meta.read_bytes()
            or source_asset.read_bytes() != project_asset.read_bytes()
        ):
            return None
        if source_meta == source_prefab_meta:
            matched_prefab = project_asset

    if matched_prefab is None or not _is_within(matched_prefab, project_root):
        return None
    return matched_prefab


def _manifest_source_project_prefab(
    record: AssetRecord,
    project_root: Path,
) -> Path | None:
    """Resolve the original project Prefab recorded by export workflow v2."""
    source_path = str(record.data.get("sourceAssetPath", "")).replace("\\", "/")
    source_guid = str(record.data.get("sourcePrefabGuid", "")).lower()
    if (
        not source_path.startswith("Assets/")
        or not re.fullmatch(r"[0-9a-f]{32}", source_guid)
    ):
        return None
    candidate = (project_root / Path(source_path)).resolve()
    assets_root = (project_root / "Assets").resolve()
    if not _is_within(candidate, assets_root) or not candidate.is_file():
        return None
    meta_path = Path(str(candidate) + ".meta")
    if not meta_path.is_file() or _read_meta_guid(meta_path) != source_guid:
        return None
    return candidate


def import_asset_to_project(
    asset_id: str,
    unity_project_root: Path | str,
    destination_folder: str = "Assets/AIAssetLibrary",
    overwrite: bool = False,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
) -> dict[str, Any]:
    record = get_asset_record(asset_id, library_root)
    project_root = normalize_unity_project_root(unity_project_root)

    relative_destination = Path(destination_folder.replace("\\", "/"))
    if relative_destination.is_absolute() or ".." in relative_destination.parts:
        raise ValueError("destination_folder must be a relative path inside Assets")
    if (
        not relative_destination.parts
        or relative_destination.parts[0].lower() != "assets"
    ):
        raise ValueError("destination_folder must start with 'Assets'")

    category = str(record.data.get("category", "uncategorized"))
    display_name = str(record.data.get("displayName", record.asset_id))
    import_key = str(record.data.get("bundleId", record.asset_id)).strip()
    bundle_display_name = str(
        record.data.get("bundleDisplayName", display_name)
    ).strip()
    if not import_key:
        import_key = record.asset_id
    if not bundle_display_name:
        bundle_display_name = display_name
    target_root = (
        project_root / relative_destination / category / bundle_display_name
    ).resolve()
    assets_root = (project_root / "Assets").resolve()
    if not _is_within(target_root, assets_root):
        raise ValueError(f"Import target escapes Unity Assets: {target_root}")

    target_existed = target_root.exists()

    source_files = _asset_source_files(record.root_path)
    relative_source_files = [
        path.relative_to(record.root_path) for path in source_files
    ]
    source_hash = calculate_asset_content_hash(
        record.root_path,
        relative_source_files,
    )
    copied_file_count = 0
    copied_byte_count = 0
    metadata_created = False
    changed = False
    update_available = False
    warning = ""
    guid_scan = {
        "conflict_count": 0,
        "conflicts": [],
        "source_guid_count": 0,
        "scanned_project_meta_count": 0,
    }

    if not target_existed:
        existing_source_prefab = _manifest_source_project_prefab(
            record, project_root
        )
        if existing_source_prefab is not None:
            return {
                "success": True,
                "asset_id": asset_id,
                "display_name": display_name,
                "bundle_id": import_key,
                "already_imported": True,
                "reused_existing_asset": True,
                "changed": False,
                "update_available": False,
                "content_hash": source_hash,
                "metadata_created": False,
                "copied_file_count": 0,
                "copied_byte_count": 0,
                "guid_conflict_count": 0,
                "guid_conflicts": [],
                "source_guid_count": 0,
                "scanned_project_meta_count": 0,
                "source_path": str(record.root_path),
                "target_path": str(existing_source_prefab.parent),
                "target_asset_path": existing_source_prefab.parent.relative_to(
                    project_root
                ).as_posix(),
                "prefab_asset_path": existing_source_prefab.relative_to(
                    project_root
                ).as_posix(),
                "meta_files_preserved": True,
                "warning": None,
            }

    target_matches = False
    if target_existed:
        import_metadata = _read_import_metadata(target_root)
        target_matches = (
            (
                import_metadata.get("importKey", import_metadata.get("assetId"))
                == import_key
            )
            and import_metadata.get("contentHash") == source_hash
        )
        if not target_matches and not import_metadata:
            try:
                target_matches = (
                    calculate_asset_content_hash(
                        target_root,
                        relative_source_files,
                    )
                    == source_hash
                )
            except (FileNotFoundError, OSError):
                target_matches = False
            if target_matches:
                _write_import_metadata(
                    target_root,
                    asset_id,
                    source_hash,
                    import_key=import_key,
                )
                metadata_created = True

        if not target_matches and not import_metadata:
            existing_keys: set[str] = set()
            existing_ids: set[str] = set()
            for manifest_path in _manifest_paths(target_root):
                try:
                    manifest_data = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError):
                    continue
                existing_ids.add(str(manifest_data.get("id", "")))
                existing_keys.add(
                    str(
                        manifest_data.get(
                            "bundleId", manifest_data.get("id", "")
                        )
                    )
                )
            if import_key not in existing_keys and asset_id not in existing_ids:
                raise FileExistsError(
                    f"Import target already exists and is not asset or bundle "
                    f"'{import_key}': {target_root}"
                )

    if not target_existed:
        guid_scan = find_project_guid_conflicts(
            record.root_path,
            assets_root,
            excluded_root=target_root,
        )
        if guid_scan["conflict_count"]:
            existing_prefab = _matching_existing_project_prefab(
                record,
                guid_scan,
                project_root,
            )
            if existing_prefab is not None:
                return {
                    "success": True,
                    "asset_id": asset_id,
                    "display_name": display_name,
                    "bundle_id": import_key,
                    "already_imported": True,
                    "reused_existing_asset": True,
                    "changed": False,
                    "update_available": False,
                    "content_hash": source_hash,
                    "metadata_created": False,
                    "copied_file_count": 0,
                    "copied_byte_count": 0,
                    "guid_conflict_count": 0,
                    "guid_conflicts": [],
                    "source_guid_count": guid_scan["source_guid_count"],
                    "scanned_project_meta_count": guid_scan[
                        "scanned_project_meta_count"
                    ],
                    "source_path": str(record.root_path),
                    "target_path": str(existing_prefab.parent),
                    "target_asset_path": existing_prefab.parent.relative_to(
                        project_root
                    ).as_posix(),
                    "prefab_asset_path": existing_prefab.relative_to(
                        project_root
                    ).as_posix(),
                    "meta_files_preserved": True,
                    "warning": None,
                }
            conflict_paths = ", ".join(
                conflict["project_meta_path"]
                for conflict in guid_scan["conflicts"]
            )
            raise ValueError(
                "Unity GUID conflict detected outside the import target: "
                f"{conflict_paths}"
            )
        _replace_asset_directory(
            record.root_path,
            target_root,
            asset_id,
            source_hash,
            import_key=import_key,
        )
        changed = True
        copied_file_count = len(source_files)
        copied_byte_count = sum(path.stat().st_size for path in source_files)
    elif not target_matches:
        update_available = True
        if overwrite:
            guid_scan = find_project_guid_conflicts(
                record.root_path,
                assets_root,
                excluded_root=target_root,
            )
            if guid_scan["conflict_count"]:
                conflict_paths = ", ".join(
                    conflict["project_meta_path"]
                    for conflict in guid_scan["conflicts"]
                )
                raise ValueError(
                    "Unity GUID conflict detected outside the import target: "
                    f"{conflict_paths}"
                )
            _replace_asset_directory(
                record.root_path,
                target_root,
                asset_id,
                source_hash,
                import_key=import_key,
            )
            changed = True
            update_available = False
            copied_file_count = len(source_files)
            copied_byte_count = sum(path.stat().st_size for path in source_files)
        else:
            warning = (
                "The library asset has changed. Re-run with overwrite=True "
                "to update the imported copy."
            )

    source_prefab = _resolve_child_path(
        record.root_path, str(record.data["prefab"])
    )
    relative_prefab = source_prefab.relative_to(record.root_path)
    project_prefab = target_root / relative_prefab
    if not project_prefab.is_file():
        raise FileNotFoundError(f"Imported prefab not found: {project_prefab}")

    return {
        "success": True,
        "asset_id": asset_id,
        "display_name": display_name,
        "bundle_id": import_key,
        "already_imported": target_existed,
        "reused_existing_asset": False,
        "changed": changed,
        "update_available": update_available,
        "content_hash": source_hash,
        "metadata_created": metadata_created,
        "copied_file_count": copied_file_count,
        "copied_byte_count": copied_byte_count,
        "guid_conflict_count": guid_scan["conflict_count"],
        "guid_conflicts": guid_scan["conflicts"],
        "source_guid_count": guid_scan["source_guid_count"],
        "scanned_project_meta_count": guid_scan["scanned_project_meta_count"],
        "source_path": str(record.root_path),
        "target_path": str(target_root),
        "target_asset_path": target_root.relative_to(project_root).as_posix(),
        "prefab_asset_path": project_prefab.relative_to(project_root).as_posix(),
        "meta_files_preserved": True,
        "warning": warning or None,
    }
