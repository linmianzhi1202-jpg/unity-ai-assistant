"""
ToolRouter — shared routing layer between Python MCP tools and Unity ToolDispatcher.

Loads tool_action_registry.json as the single source of truth for all
Python MCP tool name → Unity (tool, action) mappings.

Usage:
    from services.tools.tool_router import get_router

    router = get_router()
    result = await router.send_tool("get_unity_editor_state")
    # Equivalent to: send_to_unity("manage_editor", {"action": "get_editor_state"})

Extensibility:
    Adding a new tool requires ONLY an entry in tool_action_registry.json
    plus the corresponding Unity-side switch case. The router handles everything else.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from services.tools.unity_bridge import send_to_unity as _send_to_unity

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "tool_action_registry.json")

# ── Singleton ──────────────────────────────────────────────────────────
_router_instance: Optional["ToolRouter"] = None


class ToolRoute:
    """A single routing entry for one MCP tool."""

    def __init__(self, mcp_name: str, mapping: dict) -> None:
        self.mcp_name = mcp_name
        self.unity_tool = mapping["unity_tool"]
        self.unity_action = mapping["unity_action"]
        self.description = mapping.get("description", "")

    def build_args(self, extra_args: dict | None = None) -> dict:
        """Build the full arguments dict for unity_bridge.send_to_unity."""
        args: dict = {"action": self.unity_action} if self.unity_action is not None else {}
        if extra_args:
            args.update(extra_args)
        return args

    def __repr__(self) -> str:
        return f"ToolRoute({self.mcp_name!r} → {self.unity_tool}/{self.unity_action})"


class ToolRouter:
    """Loads the shared tool_action_registry.json and provides automatic routing.

    Architectural role:
        Python MCP Tool functions call router.send_tool("tool_name", extra_args)
        instead of manually hard-coding send_to_unity("unity_tool", {"action": "xxx"}).
        This eliminates the Python/C# mapping drift that caused P0 bugs.
    """

    def __init__(self, registry_path: str = _REGISTRY_PATH) -> None:
        self._registry_path = registry_path
        self._routes: dict[str, ToolRoute] = {}
        self._load_registry()

    # ── Registry loading ───────────────────────────────────────────

    def _load_registry(self) -> None:
        try:
            with open(self._registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as ex:
            raise ValueError(f"Failed to load tool registry: {ex}") from ex

        version = data.get("version", "unknown")
        mappings = data.get("mappings", {})

        for mcp_name, mapping in mappings.items():
            self._routes[mcp_name] = ToolRoute(mcp_name, mapping)

        logger.info(
            f"ToolRouter loaded {len(self._routes)} routes from v{version} "
            f"({self._registry_path})"
        )

    def reload(self) -> None:
        """Hot-reload the registry (useful during development)."""
        self._routes.clear()
        self._load_registry()

    # ── Route resolution ───────────────────────────────────────────

    def resolve(self, mcp_tool_name: str) -> ToolRoute | None:
        """Return the route for an MCP tool name, or None if unknown."""
        route = self._routes.get(mcp_tool_name)
        if route is None:
            logger.warning(
                f"Unknown MCP tool: {mcp_tool_name!r}. "
                f"Available: {sorted(self._routes.keys())}"
            )
        return route

    def has_route(self, mcp_tool_name: str) -> bool:
        return mcp_tool_name in self._routes

    # ── Unified send ───────────────────────────────────────────────

    async def send_tool(
        self,
        mcp_tool_name: str,
        extra_args: dict | None = None,
    ) -> dict[str, Any]:
        """Send an MCP tool call to Unity with automatic routing.

        Args:
            mcp_tool_name: The MCP tool name as defined in the registry (e.g. "get_unity_editor_state").
            extra_args: Additional key-value pairs appended to the action dict.

        Returns:
            Response dict from Unity (same format as send_to_unity).

        Raises:
            ValueError: If mcp_tool_name is not in the registry.
        """
        route = self.resolve(mcp_tool_name)
        if route is None:
            raise ValueError(
                f"MCP tool {mcp_tool_name!r} not found in registry. "
                f"Add it to tool_action_registry.json first."
            )

        args = route.build_args(extra_args)
        logger.debug(f"Router: {route} args={args}")
        return await _send_to_unity(route.unity_tool, args)

    async def send_tool_safe(
        self,
        mcp_tool_name: str,
        extra_args: dict | None = None,
        fallback: str = "error",
    ) -> dict[str, Any]:
        """Like send_tool but never raises — returns a fallback dict on error.

        Args:
            fallback: "error" → return error dict; "empty" → return {}.
        """
        try:
            return await self.send_tool(mcp_tool_name, extra_args)
        except Exception as ex:
            logger.warning(f"ToolRouter.safe_send({mcp_tool_name!r}) failed: {ex}")
            if fallback == "error":
                return {
                    "status": "error",
                    "tool": mcp_tool_name,
                    "error": str(ex),
                }
            return {}

    # ── Introspection ──────────────────────────────────────────────

    def list_all_mcp_tools(self) -> list[str]:
        """Return all known MCP tool names."""
        return sorted(self._routes.keys())

    def list_all_unity_handlers(self) -> list[str]:
        """Return all unique Unity handler names."""
        return sorted(set(r.unity_tool for r in self._routes.values()))

    def get_summary(self) -> dict:
        """Return a summary suitable for logging or diagnostics."""
        return {
            "registry_version": "1.0.0",
            "total_mcp_tools": len(self._routes),
            "total_unity_handlers": len(self.list_all_unity_handlers()),
            "route_examples": [
                repr(r) for r in list(self._routes.values())[:5]
            ],
        }


# ── Singleton factory ─────────────────────────────────────────────────

def get_router(registry_path: str = _REGISTRY_PATH) -> ToolRouter:
    """Get (or create) the singleton ToolRouter instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = ToolRouter(registry_path)
    return _router_instance


def reset_router() -> None:
    """Reset the singleton (for testing)."""
    global _router_instance
    _router_instance = None
