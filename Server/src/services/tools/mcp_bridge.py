"""
MCP Bridge Tool for the Unified MCP for Unity system.
Allows invoking tools from other MCP servers.
Group: bridge

Migrated from Coplay MCP Server's invoke_mcp_tool.
"""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from core.error_codes import UnifiedErrorCode, make_error
from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)

# Registry of connected MCP servers
_mcp_clients: dict[str, Any] = {}


def register_mcp_bridge_tools(mcp: FastMCP) -> None:
    """Register MCP Bridge tools with the MCP server."""

    @mcp.tool(tags=make_group_tags("bridge"))
    async def invoke_mcp_tool(
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on another MCP server.

        This enables cross-system integration by calling tools from
        other connected MCP servers (e.g., filesystem, database, web).

        Args:
            server_name: Name of the target MCP server.
            tool_name: Name of the tool to invoke.
            arguments: Arguments to pass to the tool.
        """
        try:
            client = _mcp_clients.get(server_name)
            if client is None:
                config_path = os.environ.get("UNITY_MCP_BRIDGE_CONFIG")
                servers = json.loads(Path(config_path).read_text(encoding="utf-8-sig")).get("mcpServers", {}) if config_path else {}
                if server_name not in servers:
                    return make_error(UnifiedErrorCode.TOOL_NOT_FOUND, message=f"MCP server '{server_name}' is not connected or configured")
                from fastmcp import Client
                async with Client({"mcpServers": {server_name: servers[server_name]}}) as connected:
                    result = await connected.call_tool(tool_name, arguments or {})
            else:
                result = await client.call_tool(tool_name, arguments or {})
            payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            if hasattr(result, "structured_content") and not isinstance(payload, dict):
                payload = {"content": [item.model_dump(mode="json") for item in result.content],
                           "structured_content": result.structured_content, "is_error": result.is_error}
            failed = bool(getattr(result, "is_error", False) or getattr(result, "isError", False))
            if isinstance(payload, dict):
                failed = failed or bool(payload.get("isError") or payload.get("is_error")) or payload.get("success") is False
                structured = payload.get("structuredContent", payload.get("structured_content"))
                if isinstance(structured, dict):
                    failed = failed or structured.get("success") is False or structured.get("status") in {"failed", "error"}
                for item in payload.get("content", []):
                    if isinstance(item, dict) and item.get("type") == "text":
                        try:
                            value = json.loads(item.get("text", ""))
                        except (ValueError, TypeError):
                            continue
                        if isinstance(value, dict):
                            failed = failed or value.get("success") is False or value.get("status") in {"failed", "error"}
            return {"success": not failed, "server": server_name, "tool": tool_name, "result": payload}
        except Exception as e:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Failed to invoke {server_name}/{tool_name}: {e}",
            )


def register_mcp_client(name: str, client: Any) -> None:
    """Register an MCP client for bridge invocation."""
    _mcp_clients[name] = client
    logger.info(f"Registered MCP client: {name}")


def unregister_mcp_client(name: str) -> None:
    """Unregister an MCP client."""
    _mcp_clients.pop(name, None)
    logger.info(f"Unregistered MCP client: {name}")
