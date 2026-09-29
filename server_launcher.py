#!/usr/bin/env python3
"""
Unified MCP for Unity — Portable Server Launcher.

This launcher is placed at the project root (unified-mcp-unity/).
It auto-detects its own location and:
  1. Adds Server/src to sys.path
  2. Changes the working directory to Server/src
  3. Sets environment variables for transport, etc.
  4. Delegates to Server/src/main.py::main()

This eliminates the hardcoded absolute path in CodeBuddy's mcp.json.
The mcp.json only needs the *absolute path to this launcher file*,
which the install script generates automatically.

Usage (from CodeBuddy mcp.json):
  {
    "command": "python",
    "args": ["<absolute-path-to-this-file>"],
    "env": { "PYTHONIOENCODING": "utf-8" }
  }

The launcher also accepts CLI arguments identical to main.py:
  python server_launcher.py --transport http --http-port 8080
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resolve_project_root() -> Path:
    """Resolve the project root directory (where this launcher lives)."""
    return Path(__file__).resolve().parent


def _ensure_encoding():
    """Ensure UTF-8 encoding on Windows."""
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("PYTHONUTF8", "1")
        if sys.stdout.encoding != "utf-8":
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except Exception:
                pass
        if sys.stderr.encoding != "utf-8":
            try:
                sys.stderr.reconfigure(encoding="utf-8")
            except Exception:
                pass
        # Windows asyncio fix
        import asyncio
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass


def _setup_paths(project_root: Path) -> Path:
    """Add Server/src to sys.path so that 'from core.config import config' works."""
    server_src = (project_root / "Server" / "src").resolve()
    if not server_src.is_dir():
        # Fallback: maybe this file is inside Server/src? (unlikely but safe)
        alt_src = project_root / "src"
        if alt_src.is_dir() and (alt_src / "main.py").exists():
            server_src = alt_src

    if str(server_src) not in sys.path:
        sys.path.insert(0, str(server_src))

    return server_src


def _print_startup_info(project_root: Path, server_src: Path):
    """Print diagnostic info on startup."""
    print(f"[Unity AI Assistant] Product root : {project_root}", file=sys.stderr)
    print(f"[Unity AI Assistant] Server src  : {server_src}", file=sys.stderr)
    print(f"[Unity AI Assistant] Python       : {sys.version}", file=sys.stderr)


def main():
    """Entry point — delegates to Server/src/main.py::main() after setup."""
    # 1. Resolve paths
    project_root = _resolve_project_root()
    server_src = _setup_paths(project_root)

    # 2. Ensure encoding
    _ensure_encoding()

    # 3. Set transport default (can be overridden by env or CLI)
    os.environ.setdefault("UNITY_MCP_TRANSPORT", "stdio")

    # 4. Change working directory to Server/src
    #    (RAG tools use __file__-relative paths, but cwd matters for other things)
    os.chdir(str(server_src))

    # 5. (optional) Set project root as env for other consumers
    os.environ["UNIFIED_MCP_PROJECT_ROOT"] = str(project_root)

    _print_startup_info(project_root, server_src)

    # 6. Delegate to the real main
    from main import main as real_main
    real_main()


if __name__ == "__main__":
    main()
