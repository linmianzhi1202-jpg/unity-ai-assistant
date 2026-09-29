"""
Package Tools for the Unified MCP for Unity system.
Provides MCP tools for Unity Package Manager operations.
Group: core

Migrated from Coplay MCP Server's package_tool_tools.py.

v1.1.0 - Added standalone .unitypackage parser tools (parse/inspect/extract).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_package_tools(mcp: FastMCP) -> None:
    """Register Package tools with the MCP server.

    Includes:
    - 7 Unity-proxy package manager tools (core group)
    - 3 standalone .unitypackage parser tools (package_parser group)
    """
    group = "core"








    # ═══════════════════════════════════════════════════════════════
    # Standalone .unitypackage Parser Tools  (v1.1.0)
    # These work WITHOUT a Unity Editor — pure Python tar.gz parsing.
    # Group: package_parser
    # ═══════════════════════════════════════════════════════════════

    _PARSER_GROUP = "package_parser"

    @mcp.tool(tags=make_group_tags(_PARSER_GROUP))
    async def parse_unitypackage(
        filepath: str,
    ) -> dict[str, Any]:
        """Parse a .unitypackage file and return the complete asset manifest.

        Works completely standalone — no Unity Editor required.  Reads the
        tar.gz archive, builds the hash→path mapping, classifies every asset
        by type, and returns a structured summary.

        Args:
            filepath: Absolute path to the .unitypackage file on disk.

        Returns:
            A dict with keys:
            - ``success`` (bool)
            - ``summary`` — ``UnityPackageInfo`` as dict (file_path, total_assets,
              total_folders, total_size, total_entries, classification)
            - ``assets`` — list of asset dicts, each containing:
              guid, original_path, asset_type, size, has_preview, content_preview
            - ``error`` (str, only on failure)
        """
        try:
            from services.parsers.unitypackage_parser import UnityPackageParser, UnityPackageParseError

            with UnityPackageParser(filepath) as pkg:
                summary = pkg.summarize()
                assets = pkg.list_assets()

            return {
                "success": True,
                "summary": {
                    "file_path": summary.file_path,
                    "total_assets": summary.total_assets,
                    "total_folders": summary.total_folders,
                    "total_size": summary.total_size,
                    "total_entries": summary.total_entries,
                    "classification": summary.classification,
                },
                "assets": [
                    {
                        "guid": a.guid,
                        "original_path": a.original_path,
                        "asset_type": a.asset_type.name,
                        "size": a.size,
                        "has_preview": a.has_preview,
                        "content_preview": a.content_preview,
                    }
                    for a in assets
                ],
            }
        except UnityPackageParseError as ex:
            return {"success": False, "error": str(ex)}
        except Exception as ex:
            logger.exception("parse_unitypackage failed for %s", filepath)
            return {"success": False, "error": str(ex)}

    @mcp.tool(tags=make_group_tags(_PARSER_GROUP))
    async def inspect_unitypackage(
        filepath: str,
        asset_identifier: str,
    ) -> dict[str, Any]:
        """Inspect a single asset inside a .unitypackage, returning its
        metadata and full text content (when applicable).

        Args:
            filepath: Absolute path to the .unitypackage file on disk.
            asset_identifier: Either the 32-char hex GUID, or the original
                asset path (e.g. ``Assets/Scripts/MyScript.cs``).

        Returns:
            A dict with keys:
            - ``success`` (bool)
            - ``asset`` — metadata dict (guid, original_path, asset_type, size, has_preview)
            - ``content`` — full decoded text for text assets, or ``null`` for binary/folders
            - ``content_size`` — content byte count (0 for folders)
            - ``error`` (str, only on failure)
        """
        try:
            from services.parsers.unitypackage_parser import UnityPackageParser, UnityPackageParseError
            from services.parsers.unitypackage_models import is_text_asset

            with UnityPackageParser(filepath) as pkg:
                asset = pkg.get_asset(asset_identifier)
                if asset is None:
                    return {
                        "success": False,
                        "error": f"Asset not found: {asset_identifier}",
                    }

                content = None
                content_size = 0
                if not (asset.asset_type.name == "FOLDER"):
                    raw = pkg.get_content(asset_identifier)
                    if raw is not None:
                        content_size = len(raw) if isinstance(raw, bytes) else len(raw.encode("utf-8"))
                        if is_text_asset(asset.asset_type):
                            content = raw if isinstance(raw, str) else None
                        else:
                            # Binary: report size but don't return bytes
                            content = None

            return {
                "success": True,
                "asset": {
                    "guid": asset.guid,
                    "original_path": asset.original_path,
                    "asset_type": asset.asset_type.name,
                    "size": asset.size,
                    "has_preview": asset.has_preview,
                },
                "content": content,
                "content_size": content_size,
            }
        except UnityPackageParseError as ex:
            return {"success": False, "error": str(ex)}
        except Exception as ex:
            logger.exception("inspect_unitypackage failed")
            return {"success": False, "error": str(ex)}

    @mcp.tool(tags=make_group_tags(_PARSER_GROUP))
    async def extract_unitypackage_assets(
        filepath: str,
        output_dir: str,
        type_filter: str | None = None,
    ) -> dict[str, Any]:
        """Extract text assets from a .unitypackage to a directory on disk.

        Preserves the original ``Assets/...`` directory structure under
        ``output_dir``.  Only extracts text-typed assets (scripts, shaders,
        YAML, JSON) — binary assets like textures are skipped.

        Args:
            filepath: Absolute path to the .unitypackage file on disk.
            output_dir: Destination directory (created if it does not exist).
            type_filter: Comma-separated AssetType names to extract
                (e.g. ``"CSHARP_SCRIPT,SHADER"``).  If omitted, extracts all
                text types.

        Returns:
            A dict with keys:
            - ``success`` (bool)
            - ``extracted_count`` — number of files written
            - ``output_dir`` — absolute output directory path
            - ``error`` (str, only on failure)
        """
        try:
            from services.parsers.unitypackage_parser import UnityPackageParser, UnityPackageParseError
            from services.parsers.unitypackage_models import AssetType, TEXT_ASSET_TYPES

            # Resolve type filter
            types: list[AssetType] | None = None
            if type_filter:
                type_names = [t.strip() for t in type_filter.split(",") if t.strip()]
                types = []
                for tn in type_names:
                    try:
                        types.append(AssetType[tn.upper()])
                    except KeyError:
                        valid = ", ".join(t.name for t in AssetType)
                        return {
                            "success": False,
                            "error": f"Unknown AssetType '{tn}'. Valid: {valid}",
                        }

            abs_output = os.path.abspath(output_dir)

            with UnityPackageParser(filepath) as pkg:
                count = pkg.extract_text_assets(abs_output, types=types)

            return {
                "success": True,
                "extracted_count": count,
                "output_dir": abs_output,
            }
        except UnityPackageParseError as ex:
            return {"success": False, "error": str(ex)}
        except Exception as ex:
            logger.exception("extract_unitypackage_assets failed")
            return {"success": False, "error": str(ex)}
