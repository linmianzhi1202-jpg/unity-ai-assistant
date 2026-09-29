"""
Unified MCP for Unity — Server Entry Point.

FastMCP server with stdio and http transport modes.
Connects to Unity Editor via TCP PluginHub.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

# Windows asyncio fix
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from core.config import config
from services.tools import register_all_tools, configure_tools

# ── Logging Setup ──────────────────────────────────────────────────

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format=config.log_format,
    stream=None,  # Avoid stdout (used by MCP stdio)
    force=True,
)
logger = logging.getLogger("unified-mcp-unity")

# Rotating file handler for persistent logs
try:
    from logging.handlers import RotatingFileHandler

    _log_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "UnityMCP", "Logs",
    )
    os.makedirs(_log_dir, exist_ok=True)
    _fh = RotatingFileHandler(
        os.path.join(_log_dir, "unified_mcp_server.log"),
        maxBytes=512 * 1024, backupCount=2, encoding="utf-8",
    )
    _fh.setFormatter(logging.Formatter(config.log_format))
    _fh.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.addHandler(_fh)
    logger.propagate = False
except Exception as exc:
    logger.debug("Failed to configure file handler", exc_info=exc)

# Quiet noisy third-party loggers
for _noisy in ("httpx", "urllib3", "mcp.server.lowlevel.server"):
    try:
        logging.getLogger(_noisy).setLevel(logging.WARNING)
    except Exception:
        pass


# ── Server Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Handle server startup and shutdown."""
    logger.info("Unified MCP for Unity Server starting up")

    unsupported = [name for name in ("acl_enabled", "encryption_enabled", "audit_log_enabled") if getattr(config, name)]
    if unsupported:
        raise ValueError(f"Unsupported security features: {', '.join(unsupported)}")
    register_all_tools(server)
    await configure_tools(server)

    # ── Cross-validate tool_action_registry.json against Unity ─────
    try:
        from services.tools import validate_registry_on_startup
        validator_task = asyncio.create_task(validate_registry_on_startup())
    except Exception as e:
        logger.debug(f"Startup validator not available: {e}")

    try:
        yield {"config": config}
    finally:
        if "validator_task" in locals():
            validator_task.cancel()
            await asyncio.gather(validator_task, return_exceptions=True)
        from services.tools.unity_bridge import close_bridge
        close_bridge()

    logger.info("Unified MCP for Unity Server shutting down")


# ── Create FastMCP Instance ────────────────────────────────────────

mcp = FastMCP(
    "unified-mcp-unity",
    version="1.0.0",
    lifespan=server_lifespan,
)

# ── Custom REST Health Endpoint ─────────────────────────────────────
# FastMCP resources require MCP protocol; this provides a plain HTTP
# GET endpoint for browser-based health checks.
# CORS headers are set manually since FastMCP doesn't support Starlette
# CORSMiddleware directly.

@mcp.custom_route("/health", methods=["GET", "OPTIONS"])
async def rest_health_check(request):
    """REST health endpoint with Unity connection status."""
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Max-Age": "86400",
    }

    # Handle preflight
    if request.method == "OPTIONS":
        return JSONResponse({"status": "ok"}, headers=cors_headers)

    unity_connected = False
    try:
        from services.tools.unity_bridge import get_bridge
        bridge = get_bridge()
        unity_connected = bridge.is_connected
    except Exception:
        pass

    return JSONResponse({
        "status": "healthy",
        "version": "1.0.0",
        "transport": config.transport_mode,
        "unity_connected": unity_connected,
    }, headers=cors_headers)


# ── Health Check (HTTP mode) ───────────────────────────────────────

@mcp.resource("mcpforunity://health")
def health_check() -> dict[str, Any]:
    """Server health status."""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "transport": config.transport_mode,
        "acl_enabled": config.acl_enabled,
        "encryption_enabled": config.encryption_enabled,
    }


# ── Unity Editor State Resource ────────────────────────────────────

@mcp.resource(
    "mcpforunity://editor/state",
    name="editor_state",
    mime_type="application/json",
)
async def editor_state() -> str:
    """Current Unity Editor state, excluding scene hierarchy."""
    try:
        from services.tools.unity_bridge import send_to_unity

        result = await send_to_unity("manage_editor", {"action": "get_editor_state"})
        if result.get("status") != "success":
            payload = {
                "status": "error",
                "error": result.get("error", "Unknown Unity editor state error"),
            }
        else:
            payload = result.get("result", {})
    except Exception as ex:
        logger.error(f"Failed to read Unity editor state resource: {ex}")
        payload = {
            "status": "error",
            "error": str(ex),
            "message": f"Failed to connect to Unity: {ex}",
        }

    return json.dumps(payload, ensure_ascii=False)


# ── Server Info Resource ───────────────────────────────────────────

@mcp.resource("mcpforunity://server/info")
def server_info() -> dict[str, Any]:
    """Server information and configuration."""
    from services.tools.tool_group_map import get_all_groups, get_full_map
    return {
        "name": "unified-mcp-unity",
        "version": "1.0.0",
        "tool_groups": sorted(get_all_groups()),
        "tool_count": len(get_full_map()),
        "enabled_groups": config.enabled_tool_groups,
        "rag_model": config.rag_model,
        "rag_timeout": config.rag_timeout,
        "unity_project_path": config.unity_project_path,
        "transport": config.transport_mode,
    }


# ── CLI Entry Point ────────────────────────────────────────────────

class _StdioOutput:
    """Keep the transport's binary stdout; send incidental text output to stderr."""
    def __init__(self, stream):
        self.buffer = stream.buffer
        self.encoding = stream.encoding

    def write(self, text):
        return sys.stderr.write(text)

    def flush(self):
        return sys.stderr.flush()

    def isatty(self):
        return False


def main() -> None:
    """Entry point for uvx and console scripts."""
    parser = argparse.ArgumentParser(
        description="Unified MCP for Unity Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  UNITY_MCP_TRANSPORT          Transport: stdio or http (default: stdio)
  UNITY_MCP_HTTP_HOST          HTTP host (default: 127.0.0.1)
  UNITY_MCP_HTTP_PORT          HTTP port (default: 6500)
  UNITY_MCP_ACL_ENABLED        Enable ACL (true/false)
  UNITY_MCP_ACL_CONFIG_PATH    ACL config file path
  UNITY_MCP_ENCRYPTION_ENABLED Enable encryption (true/false)
  UNITY_MCP_ENCRYPTION_KEY_PATH Encryption key file path
  UNITY_MCP_ENABLED_GROUPS     Comma-separated tool groups (default: all)

Examples:
  # stdio mode (for CodeBuddy / Claude Code)
  python -m src.main

  # HTTP mode (for remote access)
  python -m src.main --transport http --http-port 8080

  # With ACL enabled
  python -m src.main --acl-enabled --acl-config-path ./acl.json
        """,
    )
    parser.add_argument(
        "--transport", type=str, choices=["stdio", "http"],
        default=None, help="Transport mode (default: from env or stdio)",
    )
    parser.add_argument(
        "--http-host", type=str, default=None,
        help="HTTP server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--http-port", type=int, default=None,
        help="HTTP server port (default: 6500)",
    )
    parser.add_argument(
        "--acl-enabled", action="store_true", default=False,
        help="Enable ACL access control",
    )
    parser.add_argument(
        "--acl-config-path", type=str, default=None,
        help="Path to ACL configuration JSON file",
    )
    parser.add_argument(
        "--encryption-enabled", action="store_true", default=False,
        help="Enable AES-256-GCM encryption",
    )
    parser.add_argument(
        "--encryption-key-path", type=str, default=None,
        help="Path to encryption key file",
    )
    parser.add_argument(
        "--enabled-groups", type=str, default=None,
        help="Comma-separated list of enabled tool groups (default: all)",
    )

    args = parser.parse_args()

    # Apply CLI args to config

    if args.transport:
        config.transport_mode = args.transport
    if args.http_host:
        config.http_host = args.http_host
    if args.http_port:
        config.mcp_port = args.http_port
    if args.acl_enabled:
        config.acl_enabled = True
    if args.acl_config_path:
        config.acl_config_path = args.acl_config_path
    if args.encryption_enabled:
        config.encryption_enabled = True
    if args.encryption_key_path:
        config.encryption_key_path = args.encryption_key_path
    if args.enabled_groups:
        config.enabled_tool_groups = [g.strip() for g in args.enabled_groups.split(",")]

    # Start server
    if config.transport_mode == "http":
        host = config.http_host
        port = config.mcp_port
        logger.info(f"Starting HTTP server on {host}:{port}")
        mcp.run(transport="http", host=host, port=port)
    else:
        logger.info("Starting stdio server")
        protocol_stdout = sys.stdout
        sys.stdout = _StdioOutput(protocol_stdout)
        try:
            mcp.run(transport="stdio")
        finally:
            sys.stdout = protocol_stdout


if __name__ == "__main__":
    main()
