"""Tool registry for the Unified MCP for Unity system.

All tool modules use the register_*_tools(mcp) pattern for FastMCP registration.
Import and call these functions during server startup.
"""

import logging

# ── Implemented tool modules ────────────────────────────────────
from services.tools.ai_generation import register_ai_generation_tools
from services.tools.mcp_bridge import register_mcp_bridge_tools
from services.tools.computer_tools import register_computer_tools

# ── Unity operations ─────────────────────────────────────────────
from services.tools.package_tools import register_package_tools
from services.tools.scene_tools import register_scene_tools
from services.tools.material_prefab_tools import register_material_prefab_tools
from services.tools.agent_tools import register_agent_tools
from services.tools.ui_tools import register_ui_tools
from services.tools.animation_tools import register_animation_tools
from services.tools.asset_tools import register_asset_tools
from services.tools.screenshot_tools import register_screenshot_tools
from services.tools.project_tools import register_project_tools
from services.tools.graphics_tools import register_graphics_tools
from services.tools.scripting_tools import register_scripting_tools
from services.tools.testing_tools import register_testing_tools

# ── Phase D: Extended Unity Editor tools ────────────────────────────
from services.tools.extended_unity_tools import register_extended_unity_tools

# ── Phase E: Reference repair ───────────────────────────────────────
from services.tools.reference_repair_tools import register_reference_repair_tools

# ── RAG Knowledge Base tools ────────────────────────────────────────
from services.tools.rag_tools import register_rag_tools
from services.tools.game_code_tools import register_game_code_tools
from services.tools.asset_library_tools import register_asset_library_tools

from services.tools.tool_group_map import get_full_map, get_all_groups

# ── Architecture: Shared Registry & Validator ───────────────────────
from services.tools.tool_router import get_router, ToolRouter
from services.tools.startup_validator import validate_registry, validate_or_warn

logger = logging.getLogger(__name__)

__all__ = [
    # Original
    "register_ai_generation_tools",
    "register_mcp_bridge_tools",
    "register_computer_tools",
    # New
    "register_scene_tools",
    "register_material_prefab_tools",
    "register_agent_tools",
    "register_ui_tools",
    "register_animation_tools",
    "register_asset_tools",
    "register_screenshot_tools",
    "register_project_tools",
    "register_graphics_tools",
    "register_scripting_tools",
    "register_testing_tools",
    # Phase D: Extended Unity Editor
    "register_extended_unity_tools",
    # Phase E: Reference repair
    "register_reference_repair_tools",
    # RAG
    "register_rag_tools",
    "register_game_code_tools",
    "register_asset_library_tools",
    # Aggregator
    "register_all_tools",
]


def register_all_tools(mcp) -> None:
    """Register implemented tools; configure_tools applies selected groups."""
    # ── Original modules ─────────────────────────────────────────────
    register_ai_generation_tools(mcp)
    register_mcp_bridge_tools(mcp)         # 1 tool
    register_computer_tools(mcp)

    # ── New modules ──────────────────────────────────────────────────
    register_package_tools(mcp)
    register_scene_tools(mcp)
    register_material_prefab_tools(mcp)
    register_agent_tools(mcp)
    register_ui_tools(mcp)
    register_animation_tools(mcp)
    register_asset_tools(mcp)
    register_screenshot_tools(mcp)
    register_project_tools(mcp)
    register_graphics_tools(mcp)
    register_scripting_tools(mcp)
    register_testing_tools(mcp)

    # ── Phase D: Extended Unity Editor ──────────────────────────────
    register_extended_unity_tools(mcp)

    # ── Phase E: Reference Repair ───────────────────────────────────
    register_reference_repair_tools(mcp)   # 1 tool (repair_scene_references)

    # ── RAG Knowledge Base ──────────────────────────────────────────
    register_rag_tools(mcp)                # Unity API knowledge tools
    register_game_code_tools(mcp)          # Game source code RAG tools
    register_asset_library_tools(mcp)      # External reusable Unity asset library



async def validate_registry_on_startup() -> dict:
    """Async validation hook — call from server lifespan after TCP bridge is ready.

    Cross-checks tool_action_registry.json against Unity's live handler list.
    Returns a dict with 'status', 'errors', 'warnings'.

    Usage in main.py lifespan:
        asyncio.create_task(validate_registry_on_startup())
    """
    try:
        from services.tools.startup_validator import validate_registry
        report = await validate_registry()
        result = report.to_dict()

        if report.status == "error":
            logger.error(report.summary())
        else:
            logger.info(report.summary())

        return result
    except Exception as ex:
        logger.warning(f"Startup validation skipped: {ex}")
        return {"status": "skipped", "reason": str(ex)}


async def configure_tools(mcp) -> None:
    """Apply group selection before the server accepts tool calls."""
    from core.config import config
    from services.tools.tool_group_map import build_group_map_from_mcp

    tools = await mcp.list_tools()
    groups = {tag[6:] for tool in tools for tag in tool.tags if tag.startswith("group:")}
    unknown = set(config.enabled_tool_groups) - groups - {"all"}
    if unknown:
        raise ValueError(f"Unknown tool groups: {sorted(unknown)}. Available: {sorted(groups)}")
    for tool in tools:
        selected = {tag[6:] for tag in tool.tags if tag.startswith("group:")}
        if len(selected) != 1:
            raise ValueError(f"Expected one group tag for {tool.name}: {selected}")
        if not any(config.is_tool_group_enabled(group) for group in selected):
            mcp.local_provider.remove_tool(tool.name)
    await build_group_map_from_mcp(mcp)
