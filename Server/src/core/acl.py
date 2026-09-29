"""
Access Control List (ACL) Engine for the Unified MCP for Unity system.
Provides role-based access control for tool groups and individual tools.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from services.tools.tool_group_map import get_tool_group

logger = logging.getLogger(__name__)


# ─── Data Models ───


class RoleDefinition(BaseModel):
    """Definition of a single role."""
    description: str = ""
    allow_groups: list[str] = []
    deny_groups: list[str] = []
    read_only: bool = False
    rate_limits: dict[str, int] = {}  # tool_group → max_calls_per_minute


class ToolOverride(BaseModel):
    """Per-tool override for role restrictions and rate limits."""
    roles: list[str] = []             # allowed roles (empty = all)
    rate_limit: int | None = None     # max calls per minute


class AclConfig(BaseModel):
    """Complete ACL configuration."""
    version: str = "1.0"
    default_policy: str = "allow"     # "allow" | "deny"
    roles: dict[str, RoleDefinition] = {}
    tool_overrides: dict[str, ToolOverride] = {}
    user_assignments: dict[str, str] = {}  # user_id → role_name


# ─── Rate Limiter ───


class RateLimiter:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self) -> None:
        self._windows: dict[str, list[float]] = {}  # key → [timestamps]

    def check(self, key: str, limit: int, window_sec: int = 60) -> bool:
        """Check if a request is within rate limits.

        Returns:
            True if the request is allowed, False if rate limited.
        """
        now = time.time()
        cutoff = now - window_sec

        if key not in self._windows:
            self._windows[key] = []

        # Remove expired entries
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

        if len(self._windows[key]) >= limit:
            return False

        self._windows[key].append(now)
        return True


# ─── ACL Engine ───


class AclEngine:
    """Core ACL evaluation engine.

    Evaluates access permissions based on:
    1. Default policy (allow/deny)
    2. Role-based group permissions
    3. Per-tool overrides
    4. Rate limiting
    """

    def __init__(self, config: AclConfig | None = None) -> None:
        self._config = config or AclConfig()
        self._rate_limiter = RateLimiter()

    @classmethod
    def from_file(cls, path: str | Path) -> AclEngine:
        """Load ACL configuration from a JSON file."""
        path = Path(path)
        if not path.exists():
            logger.warning(f"ACL config file not found: {path}, using defaults")
            return cls()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            config = AclConfig(**data)
            return cls(config)
        except Exception as e:
            logger.error(f"Failed to parse ACL config: {e}")
            return cls()

    @property
    def config(self) -> AclConfig:
        return self._config

    def get_role_for_user(self, user_id: str | None) -> str | None:
        """Resolve the role for a given user ID."""
        if not user_id:
            return None
        return self._config.user_assignments.get(user_id)

    def check_access(
        self,
        tool_name: str,
        tool_group: str,
        user_id: str | None = None,
        role: str | None = None,
    ) -> tuple[bool, str]:
        """Check if a tool invocation is permitted.

        Args:
            tool_name: Name of the MCP tool.
            tool_group: Group the tool belongs to.
            user_id: Optional user ID for role lookup.
            role: Explicit role override (takes precedence over user_id lookup).

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        # Step 1: Resolve role
        resolved_role = role or self.get_role_for_user(user_id)

        # Step 2: If no role and default policy is allow, permit
        if not resolved_role:
            if self._config.default_policy == "allow":
                return True, "default_allow"
            return False, "no_role_default_deny"

        # Step 3: Check tool-level override
        override = self._config.tool_overrides.get(tool_name)
        if override:
            if override.roles and resolved_role not in override.roles:
                return False, f"tool_override_denied:role={resolved_role}"
            if override.rate_limit is not None:
                rate_key = f"{user_id or 'anon'}:{tool_name}"
                if not self._rate_limiter.check(rate_key, override.rate_limit):
                    return False, "rate_limited"

        # Step 4: Check role definition
        role_def = self._config.roles.get(resolved_role)
        if not role_def:
            # Role not defined; fall back to default policy
            if self._config.default_policy == "allow":
                return True, "undefined_role_default_allow"
            return False, f"undefined_role:{resolved_role}"

        # Step 5: Check deny list first (takes precedence)
        if "all" in role_def.deny_groups or tool_group in role_def.deny_groups:
            return False, f"denied_by_group:{tool_group}"

        # Step 6: Check allow list
        if "all" in role_def.allow_groups or tool_group in role_def.allow_groups:
            # Step 7: Check rate limit at group level
            group_limit = role_def.rate_limits.get(tool_group)
            if group_limit:
                rate_key = f"{user_id or 'anon'}:{tool_group}"
                if not self._rate_limiter.check(rate_key, group_limit):
                    return False, f"rate_limited:{tool_group}"
            return True, "allowed_by_role"

        # Step 8: No matching rule; fall back to default
        if self._config.default_policy == "allow":
            return True, "default_allow"
        return False, f"no_matching_rule:{tool_group}"

    def check_tool_access(
        self,
        tool_name: str,
        user_id: str | None = None,
        role: str | None = None,
    ) -> tuple[bool, str]:
        """Check tool access by automatically resolving its group from the map.

        Convenience method that looks up the tool's group via
        ``tool_group_map.get_tool_group`` and delegates to ``check_access``.
        Falls back to group="unknown" if the tool is not in the map.

        Args:
            tool_name: Name of the MCP tool.
            user_id: Optional user ID for role lookup.
            role: Explicit role override.

        Returns:
            Tuple of (allowed: bool, reason: str).
        """
        tool_group = get_tool_group(tool_name) or "unknown"
        return self.check_access(tool_name, tool_group, user_id=user_id, role=role)

    def list_roles(self) -> dict[str, RoleDefinition]:
        """List all defined roles."""
        return self._config.roles.copy()

    def assign_role(self, user_id: str, role_name: str) -> None:
        """Assign a role to a user."""
        self._config.user_assignments[user_id] = role_name

    def save(self, path: str | Path) -> None:
        """Save current ACL configuration to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self._config.model_dump_json(indent=2),
            encoding="utf-8",
        )


# ─── Default ACL Config ───

DEFAULT_ACL_CONFIG = AclConfig(
    version="1.0",
    default_policy="allow",
    roles={
        "admin": RoleDefinition(
            description="Full access to all tools",
            allow_groups=["all"],
            deny_groups=[],
            rate_limits={},
        ),
        "developer": RoleDefinition(
            description="Standard development tools",
            allow_groups=[
                "core", "animation", "graphics", "scene", "script",
                "asset", "ui", "package", "input",
            ],
            deny_groups=["profiler"],
            rate_limits={"ai_generation": 20},
        ),
        "viewer": RoleDefinition(
            description="Read-only access",
            allow_groups=["core"],
            deny_groups=[],
            read_only=True,
            rate_limits={},
        ),
    },
    tool_overrides={
        "execute_custom_tool": ToolOverride(roles=["admin"]),
        "invoke_mcp_tool": ToolOverride(roles=["admin"]),
        "generate_image": ToolOverride(roles=["admin", "developer"], rate_limit=10),
        "generate_3d_model": ToolOverride(roles=["admin", "developer"], rate_limit=5),
    },
    user_assignments={},
)
