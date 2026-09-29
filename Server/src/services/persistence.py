"""
Persistence Layer for Unified MCP for Unity.
Provides file-system direct-write fallback for critical asset operations
that may fail through TCP Bridge (timeouts, domain reloads, etc.).

Key features:
1. Direct YAML .asset file writer for ScriptableObject assets
2. Direct .mat file writer for Material assets
3. File-based asset creation for scripts and prefabs
4. Git auto-commit integration for all persistence operations
5. Change tracking log for audit purposes

Usage:
    from services.persistence import PersistenceLayer
    persistence = PersistenceLayer(project_root="E:/MyUnityProject")
    await persistence.save_so_asset(data, "Assets/Data/Config.asset")
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# YAML generation helpers
_YAML_HEADER = "%YAML 1.1\n%TAG !u! tag:unity3d.com,2011:\n"


class PersistenceLayer:
    """File-system persistence layer with Git integration.

    Provides redundant persistence paths for critical Unity asset operations
    that may be unreliable through the TCP Bridge alone.
    """

    def __init__(self, project_root: str, git_enabled: bool = True):
        self.project_root = Path(project_root)
        self.git_enabled = git_enabled
        self._log_dir = self.project_root / "Logs" / "persistence"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._change_log: list[dict[str, Any]] = []

    # ── Asset Writers ────────────────────────────────────────────

    def write_asset_yaml(self, asset_path: str, mono_script_guid: str, fields: dict[str, Any]) -> bool:
        """Write a Unity .asset YAML file directly to disk.

        Args:
            asset_path: Path relative to project root (e.g., 'Assets/Data/Config.asset')
            mono_script_guid: The .meta GUID of the MonoScript/C# type
            fields: Dict of field_name -> value pairs to serialize

        Returns:
            True if written successfully, False otherwise.
        """
        try:
            full_path = self.project_root / asset_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            lines = [_YAML_HEADER]

            # Object header
            asset_guid = _generate_guid()
            file_id = _generate_file_id()
            lines.append(f"--- !u!114 &{file_id}")
            lines.append("MonoBehaviour:")
            lines.append("  m_ObjectHideFlags: 0")
            lines.append("  m_CorrespondingSourceObject: {fileID: 0}")
            lines.append("  m_PrefabInstance: {fileID: 0}")
            lines.append("  m_PrefabAsset: {fileID: 0}")
            lines.append(f"  m_GameObject: {{fileID: 0}}")
            lines.append("  m_Enabled: 1")
            lines.append("  m_EditorHideFlags: 0")
            lines.append(f"  m_Script: {{fileID: 11500000, guid: {mono_script_guid}, type: 3}}")
            lines.append(f"  m_Name: {Path(asset_path).stem}")
            lines.append("  m_EditorClassIdentifier: ")

            # Serialize fields
            for key, value in fields.items():
                serialized = _serialize_field_value(key, value)
                lines.append(f"  {key}: {serialized}")

            content = "\n".join(lines) + "\n"

            # Write .asset file
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Write .meta file
            meta_content = _generate_asset_meta(asset_guid)
            meta_path = str(full_path) + ".meta"
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(meta_content)

            logger.info(f"[Persistence] Wrote .asset: {asset_path}")
            self._track_change(asset_path, "create_asset")
            return True

        except Exception as ex:
            logger.error(f"[Persistence] Failed to write .asset {asset_path}: {ex}")
            return False

    def write_material_yaml(self, material_path: str, shader_name: str = "Standard",
                            color: list[float] | None = None) -> bool:
        """Write a Unity .mat file directly to disk.

        Args:
            material_path: Path relative to project root (e.g., 'Assets/Materials/MyMat.mat')
            shader_name: Shader name (default: 'Standard')
            color: [r, g, b, a] or None for white

        Returns:
            True if written successfully.
        """
        try:
            if color is None:
                color = [1.0, 1.0, 1.0, 1.0]

            full_path = self.project_root / material_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            mat_guid = _generate_guid()
            mat_file_id = _generate_file_id()

            lines = [_YAML_HEADER]
            lines.append(f"--- !u!21 &{mat_file_id}")
            lines.append("Material:")
            lines.append("  serializedVersion: 8")
            lines.append("  m_ObjectHideFlags: 0")
            lines.append("  m_CorrespondingSourceObject: {fileID: 0}")
            lines.append("  m_PrefabInstance: {fileID: 0}")
            lines.append("  m_PrefabAsset: {fileID: 0}")
            lines.append(f"  m_Name: {Path(material_path).stem}")
            lines.append(f"  m_Shader: {{fileID: 0, guid: 00000000000000000000000000000000, type: 0}}")
            lines.append("  m_ValidKeywords: []")
            lines.append("  m_InvalidKeywords: []")
            lines.append("  m_LightmapFlags: 4")
            lines.append("  m_EnableInstancingVariants: 0")
            lines.append("  m_DoubleSidedGI: 0")
            lines.append(f"  m_CustomRenderQueue: -1")
            lines.append(f"  stringTagMap: {{}}")
            lines.append("  disabledShaderPasses: []")
            lines.append("  m_SavedProperties:")
            lines.append("    serializedVersion: 3")
            lines.append("    m_TexEnvs: []")
            lines.append("    m_Ints: []")
            lines.append("    m_Floats:")
            lines.append(f"    - _Color_a: {color[3]}")
            lines.append(f"    - _Color: {{r: {color[0]}, g: {color[1]}, b: {color[2]}, a: {color[3]}}}")
            lines.append("    - _Glossiness: 0.5")
            lines.append("    - _Metallic: 0")
            lines.append("    m_Colors:")
            lines.append(f"    - _Color: {{r: {color[0]}, g: {color[1]}, b: {color[2]}, a: {color[3]}}}")

            content = "\n".join(lines) + "\n"
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            meta_content = _generate_asset_meta(mat_guid)
            with open(str(full_path) + ".meta", "w", encoding="utf-8") as f:
                f.write(meta_content)

            logger.info(f"[Persistence] Wrote .mat: {material_path}")
            self._track_change(material_path, "create_material")
            return True

        except Exception as ex:
            logger.error(f"[Persistence] Failed to write .mat {material_path}: {ex}")
            return False

    def write_script_file(self, script_path: str, content: str) -> bool:
        """Write a C# script file to disk.

        Args:
            script_path: Path relative to project root
            content: C# script content

        Returns:
            True if written successfully.
        """
        try:
            full_path = self.project_root / script_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"[Persistence] Wrote script: {script_path}")
            self._track_change(script_path, "create_script")
            return True

        except Exception as ex:
            logger.error(f"[Persistence] Failed to write script {script_path}: {ex}")
            return False

    def write_json_file(self, json_path: str, data: dict[str, Any]) -> bool:
        """Write a JSON data file to disk.

        Args:
            json_path: Path relative to project root
            data: Dict to serialize as JSON

        Returns:
            True if written successfully.
        """
        try:
            full_path = self.project_root / json_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            with open(full_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"[Persistence] Wrote JSON: {json_path}")
            self._track_change(json_path, "write_json")
            return True

        except Exception as ex:
            logger.error(f"[Persistence] Failed to write JSON {json_path}: {ex}")
            return False

    def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists in the project."""
        return (self.project_root / relative_path).exists()

    # ── Git Integration ───────────────────────────────────────────

    def git_commit_changes(self, message: str = "Auto-persist: asset changes") -> bool:
        """Auto-commit tracked changes via Git.

        Args:
            message: Commit message

        Returns:
            True if committed successfully, False otherwise.
        """
        if not self.git_enabled:
            return False

        try:
            # git add all tracked paths
            result_add = subprocess.run(
                ["git", "add", "-A"],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )

            # Check if there are staged changes
            result_status = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(self.project_root),
                capture_output=True, timeout=10,
            )

            if result_status.returncode == 0:
                return True  # No changes to commit

            # Commit
            result_commit = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.project_root),
                capture_output=True, text=True, timeout=30,
            )

            if result_commit.returncode == 0:
                logger.info(f"[Persistence] Git committed: {message}")
                return True
            else:
                logger.warning(f"[Persistence] Git commit failed: {result_commit.stderr}")
                return False

        except FileNotFoundError:
            logger.debug("[Persistence] Git not available — skipping auto-commit")
            return False
        except Exception as ex:
            logger.error(f"[Persistence] Git error: {ex}")
            return False

    # ── Internal Helpers ──────────────────────────────────────────

    def _track_change(self, path: str, operation: str) -> None:
        """Record a change in the persistence log."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "operation": operation,
        }
        self._change_log.append(entry)

    def flush_change_log(self) -> None:
        """Write the change log to disk."""
        if self._change_log:
            log_path = self._log_dir / f"persistence_log_{datetime.now():%Y%m%d_%H%M%S}.json"
            try:
                with open(log_path, "w", encoding="utf-8") as f:
                    json.dump(self._change_log, f, indent=2, ensure_ascii=False)
                self._change_log.clear()
            except Exception as ex:
                logger.error(f"[Persistence] Failed to flush change log: {ex}")


# ── Global Singleton ──────────────────────────────────────────────

_persistence_instance: PersistenceLayer | None = None


def get_persistence(project_root: str | None = None) -> PersistenceLayer:
    """Get or create the global PersistenceLayer instance."""
    global _persistence_instance
    if _persistence_instance is None and project_root:
        _persistence_instance = PersistenceLayer(project_root)
    return _persistence_instance


def set_persistence(instance: PersistenceLayer) -> None:
    """Set the global persistence instance."""
    global _persistence_instance
    _persistence_instance = instance


# ── Helper Functions ──────────────────────────────────────────────

def _generate_guid() -> str:
    """Generate a Unity-compatible GUID (32 hex chars)."""
    return uuid.uuid4().hex


def _generate_file_id() -> int:
    """Generate a Unity YAML fileID (positive integer)."""
    return abs(hash(str(uuid.uuid4()))) % 9_000_000_000 + 1_000_000_000


def _serialize_field_value(key: str, value: Any) -> str:
    """Serialize a Python value to Unity YAML format."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return str(value)
    if isinstance(value, dict):
        return str(value)
    return str(value)


def _generate_asset_meta(guid: str) -> str:
    """Generate a .meta file for a Unity asset."""
    return (
        "fileFormatVersion: 2\n"
        f"guid: {guid}\n"
        "NativeFormatImporter:\n"
        "  externalObjects: {}\n"
        "  mainObjectFileID: 0\n"
        "  userData: \n"
        "  assetBundleName: \n"
        "  assetBundleVariant: \n"
    )
