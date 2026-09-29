"""Preview and apply reusable Unity Prefab exports into the asset library."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from services.asset_library_service import (
    DEFAULT_LIBRARY_ROOT,
    build_placement_profile,
    index_asset_library_records,
    validate_asset_library,
)
from services.asset_graph_service import build_asset_graph


PLAN_TTL_SECONDS = 3600.0
MAX_PREFABS = 200
BUNDLE_METADATA_FILENAME = ".asset-library-bundle.json"

_CATEGORY_FOLDERS = {
    "animal": "Animals",
    "character": "Characters",
    "environment": "Environment",
    "prop": "Props",
    "vehicle": "Vehicles",
}
_BLOCKING_EXTENSIONS = {".cs", ".dll", ".asmdef", ".asmref", ".unity"}
_BINARY_SAFE_EXTENSIONS = {
    ".fbx", ".obj", ".png", ".jpg", ".jpeg", ".tga", ".psd",
    ".exr", ".hdr", ".wav", ".mp3", ".ogg", ".mp4", ".mov",
}
_REWRITE_TEXT_EXTENSIONS = {
    ".anim", ".asset", ".controller", ".mat", ".overridecontroller",
    ".playable", ".prefab", ".shader", ".shadergraph",
    ".shadersubgraph", ".meta",
}
_GUID_LINE = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
_GUID_REFERENCE = re.compile(r"\bguid:\s*([0-9a-fA-F]{32})\b")
_TEXT_GUID_REFERENCE_EXTENSIONS = {
    ".anim", ".asset", ".controller", ".mat", ".overridecontroller",
    ".playable", ".prefab", ".unity",
}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_bundle_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
    cleaned = cleaned.rstrip(" .")
    if not cleaned:
        raise ValueError("bundle_name must contain a valid folder name")
    return cleaned[:100]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if normalized:
        return normalized[:48]
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _read_meta_guid(path: Path) -> str:
    match = _GUID_LINE.search(path.read_text(encoding="utf-8"))
    return match.group(1).lower() if match else ""


def _hash_file_pair(asset_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (asset_path, Path(str(asset_path) + ".meta")):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _hash_dependencies(paths: list[str], snapshots: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode("utf-8"))
        digest.update(snapshots[path].encode("ascii"))
    return digest.hexdigest()


def _vector3_list(value: Any, default: list[float]) -> list[float]:
    if isinstance(value, dict):
        values = [value.get(axis) for axis in "xyz"]
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        values = list(value)
    else:
        return list(default)
    try:
        result = [float(item) for item in values]
    except (TypeError, ValueError):
        return list(default)
    if not all(math.isfinite(item) for item in result):
        return list(default)
    return result


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _relation_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _manifest_paths(root: Path) -> list[Path]:
    paths = set(root.glob("asset.json"))
    paths.update(root.glob("*.asset.json"))
    return sorted(paths, key=lambda path: path.name)


def _existing_manifests(target: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not target.is_dir():
        return records
    for path in _manifest_paths(target):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        source_guid = str(data.get("sourcePrefabGuid", "")).lower()
        if source_guid:
            records[source_guid] = data
    return records


class AssetExportPlanStore:
    def __init__(self, ttl_seconds: float = PLAN_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._plans: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, plan: dict[str, Any]) -> str:
        plan_id = uuid.uuid4().hex
        payload = dict(plan)
        payload["plan_id"] = plan_id
        payload["created_at"] = time.time()
        payload["expires_at"] = payload["created_at"] + self.ttl_seconds
        with self._lock:
            self._cleanup_locked()
            self._plans[plan_id] = payload
        return plan_id

    def get(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_locked()
            plan = self._plans.get(plan_id)
            return dict(plan) if plan else None

    def _cleanup_locked(self) -> None:
        now = time.time()
        expired = [
            plan_id for plan_id, plan in self._plans.items()
            if float(plan.get("expires_at", 0)) <= now
        ]
        for plan_id in expired:
            self._plans.pop(plan_id, None)


_PLAN_STORE = AssetExportPlanStore()


def get_asset_export_plan_store() -> AssetExportPlanStore:
    return _PLAN_STORE


def build_asset_export_preview(
    unity_analysis: dict[str, Any],
    bundle_name: str,
    category: str = "environment",
    intent: str = "",
    metadata_overrides: dict[str, Any] | None = None,
    library_root: Path | str = DEFAULT_LIBRARY_ROOT,
    replace_bundle: bool = False,
) -> dict[str, Any]:
    """Build a read-only export plan from Unity dependency analysis."""
    bundle_name = _safe_bundle_name(bundle_name)
    category = re.sub(r"[^a-z0-9_-]", "", category.strip().lower())
    if not category:
        raise ValueError("category must contain an ASCII category name")
    prefabs = list(unity_analysis.get("prefabs") or [])
    dependencies = list(unity_analysis.get("dependencies") or [])
    if len(prefabs) > MAX_PREFABS:
        raise ValueError(f"At most {MAX_PREFABS} Prefabs may be exported at once")

    project_root = Path(str(unity_analysis.get("project_path", ""))).resolve()
    assets_root = (project_root / "Assets").resolve()
    if not assets_root.is_dir():
        raise ValueError(f"Unity project Assets directory not found: {assets_root}")

    category_folder = _CATEGORY_FOLDERS.get(category, category.title())
    target = Path(library_root).resolve() / category_folder / bundle_name
    bundle_id = f"{category}-{_slug(bundle_name)}"
    overrides = metadata_overrides or {}
    blocking = set(str(item) for item in unity_analysis.get("blocking_dependencies", []))
    errors = [str(item) for item in unity_analysis.get("errors", [])]
    conflicts: list[str] = []
    snapshots: dict[str, str] = {}
    dependency_by_path: dict[str, dict[str, Any]] = {}
    guid_paths: dict[str, list[str]] = {}
    total_bytes = 0

    for dependency in dependencies:
        path = str(dependency.get("path", "")).replace("\\", "/")
        if not path.startswith("Assets/"):
            errors.append(f"Dependency is outside Assets: {path}")
            continue
        absolute = (project_root / Path(path)).resolve()
        meta = Path(str(absolute) + ".meta")
        if not _is_within(absolute, assets_root):
            errors.append(f"Dependency escapes Assets: {path}")
            continue
        extension = absolute.suffix.lower()
        if extension in _BLOCKING_EXTENSIONS:
            blocking.add(path)
        if not absolute.is_file():
            errors.append(f"Dependency file is missing: {path}")
            continue
        if not meta.is_file():
            errors.append(f"Dependency meta file is missing: {path}.meta")
            continue
        if extension not in _BINARY_SAFE_EXTENSIONS and extension not in _REWRITE_TEXT_EXTENSIONS:
            try:
                if b"\x00" in absolute.read_bytes()[:8192]:
                    blocking.add(path)
            except OSError:
                errors.append(f"Dependency could not be inspected: {path}")
                continue
        guid = _read_meta_guid(meta)
        if not guid:
            errors.append(f"Dependency meta GUID is invalid: {path}.meta")
            continue
        guid_paths.setdefault(guid, []).append(path)
        snapshots[path] = _hash_file_pair(absolute)
        total_bytes += absolute.stat().st_size + meta.stat().st_size
        dependency_by_path[path] = {
            **dependency,
            "path": path,
            "guid": guid,
            "absolute_path": str(absolute),
            "output_path": f"Source/{path}",
        }

    for guid, paths in guid_paths.items():
        if len(paths) > 1:
            conflicts.append(f"Duplicate source GUID {guid}: {', '.join(paths)}")

    package_guids = {
        str(dependency.get("guid", "")).lower()
        for dependency in unity_analysis.get("package_dependencies", [])
        if isinstance(dependency, dict)
        and re.fullmatch(
            r"[0-9a-fA-F]{32}", str(dependency.get("guid", ""))
        )
    }
    source_guids = set(guid_paths)
    for dependency in dependency_by_path.values():
        absolute = Path(str(dependency["absolute_path"]))
        if absolute.suffix.lower() not in _TEXT_GUID_REFERENCE_EXTENSIONS:
            continue
        try:
            text = absolute.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(
                f"Dependency text references could not be inspected: "
                f"{dependency['path']}"
            )
            continue
        for referenced_guid in sorted(
            {match.lower() for match in _GUID_REFERENCE.findall(text)}
        ):
            if (
                referenced_guid.startswith("0000000000000000")
                or referenced_guid in source_guids
                or referenced_guid in package_guids
            ):
                continue
            errors.append(
                "Unresolved source Unity GUID reference in "
                f"{dependency['path']}: {referenced_guid}"
            )

    existing = _existing_manifests(target)
    entries: list[dict[str, Any]] = []
    change_counts = {"added": 0, "changed": 0, "unchanged": 0}
    seen_asset_ids: set[str] = set()

    for prefab in prefabs:
        source_path = str(prefab.get("path", "")).replace("\\", "/")
        source_guid = str(prefab.get("guid", "")).lower()
        dependency_paths = [
            str(path).replace("\\", "/")
            for path in prefab.get("dependency_paths", [])
            if str(path).replace("\\", "/") in dependency_by_path
        ]
        if source_path not in dependency_paths and source_path in dependency_by_path:
            dependency_paths.append(source_path)
        model_paths = [
            path for path in dependency_paths
            if str(dependency_by_path[path].get("type", "")) == "model"
        ]
        material_paths = [
            path for path in dependency_paths
            if str(dependency_by_path[path].get("type", "")) == "material"
        ]
        override = overrides.get(source_path) or overrides.get(source_guid) or overrides.get(str(prefab.get("name", ""))) or {}
        requested_model = str(override.get("modelPath", ""))
        requested_material = str(override.get("materialPath", ""))
        if requested_model:
            if requested_model not in model_paths:
                errors.append(
                    f"metadata modelPath is not a dependency of {source_path}: "
                    f"{requested_model}"
                )
                continue
            model_paths = [requested_model]
        if requested_material:
            if requested_material not in material_paths:
                errors.append(
                    f"metadata materialPath is not a dependency of {source_path}: "
                    f"{requested_material}"
                )
                continue
            material_paths = [requested_material]
        if not source_guid or source_path not in dependency_by_path:
            errors.append(f"Prefab dependency metadata is incomplete: {source_path}")
            continue
        if not model_paths:
            errors.append(f"Prefab has no reusable model dependency: {source_path}")
            continue
        if not material_paths:
            errors.append(f"Prefab has no material dependency: {source_path}")
            continue

        source_hash = _hash_dependencies(dependency_paths, snapshots)
        previous = existing.get(source_guid, {})
        clean_name = re.sub(r"^(SM_|PF_)", "", str(prefab.get("name") or Path(source_path).stem))
        clean_name = re.sub(r"[_-]+", " ", clean_name).strip()
        asset_id = str(
            override.get("id")
            or previous.get("id")
            or f"{category}-{_slug(bundle_name)}-{source_guid[:12]}"
        ).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,127}", asset_id):
            errors.append(f"Invalid generated asset id for {source_path}: {asset_id}")
            continue
        if asset_id in seen_asset_ids:
            errors.append(f"Duplicate generated asset id: {asset_id}")
            continue
        seen_asset_ids.add(asset_id)

        display_name = str(override.get("displayName") or previous.get("displayName") or clean_name)
        bounds = _vector3_list(prefab.get("bounds_size"), [1.0, 1.0, 1.0])
        scale = _vector3_list(prefab.get("default_scale"), [1.0, 1.0, 1.0])
        if any(value <= 0 for value in bounds):
            errors.append(f"Prefab has invalid renderer/collider bounds: {source_path}")
            continue
        aliases = _string_list(override.get("aliases")) or [str(prefab.get("name", "")), clean_name]
        tags = _string_list(override.get("tags")) or [category, "Prefab", "3D资产"]
        description = str(
            override.get("description")
            or previous.get("description")
            or f"可复用 Unity Prefab：{display_name}。{intent}".strip()
        )
        use_cases = _string_list(override.get("useCases")) or ([intent] if intent.strip() else [])
        semantic_attributes = _dict_value(
            override.get(
                "semanticAttributes",
                previous.get("semanticAttributes", {}),
            )
        )
        placement_geometry = _dict_value(prefab.get("placement_geometry"))
        profile_seed = {
            "id": asset_id,
            "displayName": display_name,
            "category": category,
            "bounds": {"x": bounds[0], "y": bounds[1], "z": bounds[2]},
            "placementRadius": max(bounds[0], bounds[2]) / 2.0,
            "tags": tags,
            "aliases": aliases,
            "description": description,
            "useCases": use_cases,
        }
        placement_profile = build_placement_profile(
            profile_seed,
            {
                **_dict_value(previous.get("placementProfile", {})),
                **_dict_value(override.get("placementProfile", {})),
            },
            placement_geometry,
        )
        relations = _relation_list(
            override.get("relations", previous.get("relations", []))
        )
        change = "added"
        if previous:
            change = (
                "unchanged"
                if str(previous.get("sourceDependencyHash", "")) == source_hash
                else "changed"
            )
        change_counts[change] += 1
        entries.append({
            "asset_id": asset_id,
            "display_name": display_name,
            "source_prefab_path": source_path,
            "source_prefab_guid": source_guid,
            "source_dependency_hash": source_hash,
            "dependency_paths": sorted(set(dependency_paths)),
            "model_path": model_paths[0],
            "material_path": material_paths[0],
            "default_scale": scale,
            "bounds": {"x": bounds[0], "y": bounds[1], "z": bounds[2]},
            "ground_offset": float(override.get("groundOffset", previous.get("groundOffset", 0.0))),
            "forward_axis": str(override.get("forwardAxis", previous.get("forwardAxis", "+Z"))),
            "tags": tags,
            "aliases": aliases,
            "description": description,
            "use_cases": use_cases,
            "variant_group": override.get("variantGroup", previous.get("variantGroup")),
            "variant_color": override.get("variantColor", previous.get("variantColor")),
            "semantic_attributes": semantic_attributes,
            "placement_profile": placement_profile,
            "placement_analysis": placement_geometry,
            "relations": relations,
            "change": change,
        })

    can_export = bool(entries) and not errors and not blocking and not conflicts
    plan = {
        "status": "preview",
        "can_export": can_export,
        "bundle_id": bundle_id,
        "bundle_name": bundle_name,
        "category": category,
        "intent": intent,
        "project_root": str(project_root),
        "library_root": str(Path(library_root).resolve()),
        "target_path": str(target),
        "replace_bundle": bool(replace_bundle),
        "prefab_count": len(entries),
        "dependency_count": len(dependency_by_path),
        "estimated_bytes": total_bytes,
        "entries": entries,
        "dependencies": list(dependency_by_path.values()),
        "source_snapshots": snapshots,
        "blocking_dependencies": sorted(blocking),
        "package_dependencies": list(unity_analysis.get("package_dependencies", [])),
        "errors": errors,
        "conflicts": conflicts,
        "changes": change_counts,
        "next_action": (
            "Call apply_asset_library_export with plan_id to publish this preview."
            if can_export else
            "Resolve blocking_dependencies, errors, and conflicts, then preview again."
        ),
    }
    plan_id = get_asset_export_plan_store().put(plan)
    return {**plan, "plan_id": plan_id}


def _deterministic_guid(bundle_id: str, source_guid: str) -> str:
    return hashlib.md5(f"{bundle_id}:{source_guid}".encode("utf-8")).hexdigest()


def _rewrite_guids(path: Path, guid_map: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for source_guid, target_guid in guid_map.items():
        text = re.sub(
            rf"(?i)\b{re.escape(source_guid)}\b",
            target_guid,
            text,
        )
    path.write_text(text, encoding="utf-8", newline="")


def _atomic_publish(staging: Path, target: Path) -> Path | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.parent / f".{target.name}.backup-{uuid.uuid4().hex}"
    if target.exists():
        target.rename(backup)
    try:
        staging.rename(target)
        return backup if backup.exists() else None
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise


def apply_asset_export_plan(
    plan_id: str,
    progress: Callable[[str, float], None] | None = None,
) -> dict[str, Any]:
    """Apply a previewed plan with staging, validation, publish, and indexing."""
    plan = get_asset_export_plan_store().get(plan_id)
    if not plan:
        raise KeyError("Asset export plan was not found or has expired")
    if not plan.get("can_export"):
        raise ValueError("Asset export plan is blocked and cannot be applied")

    def report(phase: str, value: float) -> None:
        if progress:
            progress(phase, value)

    report("verify_source", 0.05)
    project_root = Path(plan["project_root"]).resolve()
    for source_path, expected_hash in plan["source_snapshots"].items():
        actual = _hash_file_pair((project_root / Path(source_path)).resolve())
        if actual != expected_hash:
            raise RuntimeError(
                f"Source changed after preview; preview again: {source_path}"
            )

    target = Path(plan["target_path"]).resolve()
    staging = target.parent / f".{target.name}.export-{uuid.uuid4().hex}"
    backup: Path | None = None
    if target.exists() and not plan.get("replace_bundle", False):
        shutil.copytree(target, staging, copy_function=shutil.copy2)
    else:
        staging.mkdir(parents=True)

    try:
        report("copy_dependencies", 0.25)
        copied_paths: list[Path] = []
        source_guid_paths: dict[str, str] = {}
        for dependency in plan["dependencies"]:
            source = Path(dependency["absolute_path"]).resolve()
            relative_output = Path(str(dependency["output_path"]).replace("/", "\\"))
            destination = (staging / relative_output).resolve()
            if not _is_within(destination, staging):
                raise ValueError(f"Dependency output escapes staging: {relative_output}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            source_meta = Path(str(source) + ".meta")
            destination_meta = Path(str(destination) + ".meta")
            shutil.copy2(source_meta, destination_meta)
            copied_paths.extend([destination, destination_meta])
            source_guid_paths[str(dependency["guid"]).lower()] = str(dependency["path"])

        existing_map: dict[str, str] = {}
        metadata_path = staging / BUNDLE_METADATA_FILENAME
        if metadata_path.is_file():
            try:
                existing_map = json.loads(
                    metadata_path.read_text(encoding="utf-8")
                ).get("sourceGuidMap", {})
            except (OSError, ValueError):
                existing_map = {}
        guid_map = {
            source_guid: str(existing_map.get(source_guid) or _deterministic_guid(
                str(plan["bundle_id"]), source_guid
            )).lower()
            for source_guid in source_guid_paths
        }

        report("remap_guids", 0.5)
        for path in copied_paths:
            if path.suffix.lower() in _REWRITE_TEXT_EXTENSIONS:
                _rewrite_guids(path, guid_map)

        report("write_manifests", 0.66)
        for entry in plan["entries"]:
            prefab_dependency = next(
                dependency for dependency in plan["dependencies"]
                if dependency["path"] == entry["source_prefab_path"]
            )
            model_dependency = next(
                dependency for dependency in plan["dependencies"]
                if dependency["path"] == entry["model_path"]
            )
            material_dependency = next(
                dependency for dependency in plan["dependencies"]
                if dependency["path"] == entry["material_path"]
            )
            bounds = entry["bounds"]
            manifest: dict[str, Any] = {
                "schemaVersion": 3,
                "id": entry["asset_id"],
                "displayName": entry["display_name"],
                "category": plan["category"],
                "bundleId": plan["bundle_id"],
                "bundleDisplayName": plan["bundle_name"],
                "prefab": prefab_dependency["output_path"],
                "model": model_dependency["output_path"],
                "material": material_dependency["output_path"],
                "sourceModelGuid": guid_map[str(model_dependency["guid"]).lower()],
                "sourcePrefabGuid": entry["source_prefab_guid"],
                "sourceAssetPath": entry["source_prefab_path"],
                "sourceDependencyHash": entry["source_dependency_hash"],
                "defaultScale": entry["default_scale"],
                "groundOffset": entry["ground_offset"],
                "forwardAxis": entry["forward_axis"],
                "placementRadius": round(
                    max(float(bounds["x"]), float(bounds["z"])) / 2.0, 4
                ),
                "bounds": bounds,
                "tags": entry["tags"],
                "aliases": entry["aliases"],
                "description": entry["description"],
                "useCases": entry["use_cases"],
                "semanticAttributes": entry["semantic_attributes"],
                "placementProfile": entry["placement_profile"],
                "relations": entry["relations"],
            }
            if entry.get("variant_group"):
                manifest["variantGroup"] = entry["variant_group"]
            if entry.get("variant_color"):
                manifest["variantColor"] = entry["variant_color"]
            (staging / f"{entry['asset_id']}.asset.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

        metadata_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "bundleId": plan["bundle_id"],
                    "displayName": plan["bundle_name"],
                    "sourceProject": str(project_root),
                    "sourceGuidMap": guid_map,
                    "sourceGuidPaths": source_guid_paths,
                    "packageDependencies": plan["package_dependencies"],
                    "updatedAt": time.time(),
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        report("validate_staging", 0.76)
        staging_validation = validate_asset_library(staging)
        if not staging_validation.get("valid"):
            raise RuntimeError(
                "Staged asset bundle validation failed: "
                + json.dumps(staging_validation, ensure_ascii=False)
            )

        report("publish", 0.84)
        backup = _atomic_publish(staging, target)
        full_validation = validate_asset_library(plan["library_root"])
        if not full_validation.get("valid"):
            if target.exists():
                shutil.rmtree(target)
            if backup and backup.exists():
                backup.rename(target)
            raise RuntimeError(
                "Published library validation failed: "
                + json.dumps(full_validation, ensure_ascii=False)
            )
        if backup and backup.exists():
            shutil.rmtree(backup)
            backup = None

        report("index", 0.92)
        try:
            index_result = index_asset_library_records(
                [entry["asset_id"] for entry in plan["entries"]],
                library_root=plan["library_root"],
            )
            status = "applied"
            index_error = None
        except Exception as exc:
            status = "applied_index_pending"
            index_result = None
            index_error = str(exc)

        report("graph", 0.97)
        try:
            graph_result = build_asset_graph(library_root=plan["library_root"])
            graph_error = None
        except Exception as exc:
            graph_result = None
            graph_error = str(exc)
            if status == "applied":
                status = "applied_graph_pending"
            elif status == "applied_index_pending":
                status = "applied_index_graph_pending"

        report("ready", 1.0)
        return {
            "status": status,
            "success": True,
            "plan_id": plan_id,
            "bundle_id": plan["bundle_id"],
            "bundle_path": str(target),
            "asset_count": len(plan["entries"]),
            "dependency_count": len(plan["dependencies"]),
            "changes": plan["changes"],
            "validation": full_validation,
            "index": index_result,
            "index_error": index_error,
            "graph": graph_result,
            "graph_error": graph_error,
        }
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup and backup.exists() and target.exists():
            shutil.rmtree(backup)
