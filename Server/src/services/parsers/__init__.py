"""
Parsers package for the Unified MCP for Unity system.

Provides standalone (editor-free) parsers for Unity-specific file formats.
"""

from services.parsers.unitypackage_models import (
    AssetType,
    TEXT_ASSET_TYPES,
    UnityPackageAsset,
    UnityPackageInfo,
    classification_counts,
    detect_asset_type,
    extension_from_path,
    is_text_asset,
)
from services.parsers.unitypackage_parser import UnityPackageParser

__all__ = [
    # Models
    "AssetType",
    "TEXT_ASSET_TYPES",
    "UnityPackageAsset",
    "UnityPackageInfo",
    "classification_counts",
    "detect_asset_type",
    "extension_from_path",
    "is_text_asset",
    # Parser
    "UnityPackageParser",
]
