"""
Computer Tools for the Unified MCP for Unity system.
Provides MCP tools for file system operations on the Unity project.
Group: computer

Migrated from Coplay MCP Server's general_computer_tool_tools.
"""

from __future__ import annotations

import logging
import asyncio
import zipfile
import xml.etree.ElementTree as ET
from core.config import config
from services.tools.unity_bridge import get_bridge
import re
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from core.error_codes import UnifiedErrorCode, make_error
from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


async def _project_path(value: str | None) -> Path:
    path = Path(value or ".").expanduser()
    if path.is_absolute():
        return path
    root = config.unity_project_path
    if not root:
        root = (await get_bridge().get_unity_info())["project_path"]
    return (Path(root) / path).resolve()


def register_computer_tools(mcp: FastMCP) -> None:
    """Register Computer tools with the MCP server."""
    group = "computer"

    @mcp.tool(tags=make_group_tags("computer"))
    async def read_project_file(
        path: str,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        """Read a file from the Unity project.

        Supports text files and can extract content from PDF/DOCX files
        if appropriate libraries are available.

        Args:
            path: File path relative to the Unity project root.
            encoding: File encoding (default: utf-8).
        """
        try:
            file_path = await _project_path(path)
            if not file_path.exists():
                return make_error(
                    UnifiedErrorCode.UNITY_ASSET_NOT_FOUND,
                    message=f"File not found: {path}",
                )

            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                def extract_pdf():
                    import pdfplumber
                    with pdfplumber.open(file_path) as document:
                        return "\n".join(page.extract_text() or "" for page in document.pages)
                content = await asyncio.to_thread(extract_pdf)
            elif suffix == ".docx":
                def extract_docx():
                    with zipfile.ZipFile(file_path) as archive:
                        body = ET.fromstring(archive.read("word/document.xml"))
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    return "\n".join("".join(node.text or "" for node in paragraph.findall(".//w:t", ns)) for paragraph in body.findall(".//w:p", ns))
                content = await asyncio.to_thread(extract_docx)
            elif suffix == ".doc":
                return make_error(UnifiedErrorCode.PARAM_INVALID, message="Legacy binary .doc is unsupported; save as .docx first")
            else:
                content = await asyncio.to_thread(file_path.read_text, encoding=encoding)
            return {"success": True, "path": path, "content": content, "size": len(content)}

        except Exception as e:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Failed to read file: {e}",
            )

    @mcp.tool(tags=make_group_tags("computer"))
    async def search_project_files(
        pattern: str,
        path: str | None = None,
        file_glob: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Search file contents in the Unity project using regex patterns.

        Uses Python regex syntax for pattern matching.

        Args:
            pattern: Regex pattern to search for.
            path: Directory to search in (default: project root).
            file_glob: File glob pattern to filter (e.g., "*.cs", "*.shader").
            max_results: Maximum number of results to return.
        """
        try:
            search_root = await _project_path(path)
            if not search_root.exists():
                return make_error(
                    UnifiedErrorCode.UNITY_ASSET_NOT_FOUND,
                    message=f"Directory not found: {path}",
                )

            results = []
            compiled = re.compile(pattern, re.IGNORECASE)

            glob_pattern = file_glob or "*"
            for file_path in search_root.rglob(glob_pattern):
                if file_path.is_dir():
                    continue
                if ".git" in file_path.parts or "node_modules" in file_path.parts:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(content.splitlines(), 1):
                        if compiled.search(line):
                            results.append({
                                "file": str(file_path),
                                "line": i,
                                "content": line.strip()[:200],
                            })
                            if len(results) >= max_results:
                                break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break

            return {"success": True, "pattern": pattern, "count": len(results), "results": results}

        except re.error as e:
            return make_error(
                UnifiedErrorCode.PARAM_INVALID,
                message=f"Invalid regex pattern: {e}",
            )
        except Exception as e:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Search failed: {e}",
            )

    @mcp.tool(tags=make_group_tags("computer"))
    async def list_code_definitions(
        path: str | None = None,
        file_glob: str = "*.cs",
    ) -> dict[str, Any]:
        """List code definition names (classes, methods, properties) in project files.

        Args:
            path: Directory to search in (default: project root).
            file_glob: File pattern to search (default: *.cs).
        """
        try:
            search_root = await _project_path(path)
            if not search_root.is_dir():
                raise FileNotFoundError(f"Directory not found: {search_root}")
            pattern = re.compile(
                r"^\s*(public|private|protected|internal)?\s*"
                r"(class|struct|interface|enum|void|\w+)\s+"
                r"(\w+)",
                re.MULTILINE,
            )

            definitions = []
            for file_path in search_root.rglob(file_glob):
                if ".git" in file_path.parts:
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for match in pattern.finditer(content):
                        definitions.append({
                            "file": str(file_path),
                            "name": match.group(3),
                            "type": match.group(2),
                        })
                except Exception:
                    continue

            return {"success": True, "count": len(definitions), "definitions": definitions}

        except Exception as e:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Failed to list definitions: {e}",
            )

    @mcp.tool(tags=make_group_tags("computer"))
    async def list_project_files(
        path: str | None = None,
        recursive: bool = True,
    ) -> dict[str, Any]:
        """List files in a project directory.

        Args:
            path: Directory path (default: project root).
            recursive: Whether to list recursively.
        """
        try:
            dir_path = await _project_path(path)
            if not dir_path.exists():
                return make_error(
                    UnifiedErrorCode.UNITY_ASSET_NOT_FOUND,
                    message=f"Directory not found: {path}",
                )

            files = []
            method = dir_path.rglob if recursive else dir_path.glob
            for p in method("*"):
                if ".git" in p.parts or "node_modules" in p.parts:
                    continue
                if p.is_file():
                    stat = p.stat()
                    files.append({
                        "path": str(p),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })

            return {"success": True, "path": str(dir_path), "count": len(files), "files": files}

        except Exception as e:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Failed to list files: {e}",
            )
