"""Unity instance selection and project information."""
from typing import Any
from fastmcp import FastMCP
from core.error_codes import UnifiedErrorCode, make_error
from services.tools.tool_group_map import make_group_tags
from services.tools.unity_bridge import get_bridge, discover_unity_instances

def register_project_tools(mcp: FastMCP) -> None:
    @mcp.tool(tags=make_group_tags("core"))
    async def set_unity_project_root(unity_project_root: str) -> dict[str, Any]:
        """Select the target Unity project explicitly. The next connection verifies its identity."""
        if not unity_project_root.strip():
            return make_error(UnifiedErrorCode.PARAM_INVALID, message="Unity project root cannot be empty")
        await get_bridge().select_project(unity_project_root)
        return {"success": True, "tool": "set_unity_project_root",
                "params": {"unity_project_root": unity_project_root},
                "message": f"Unity project selected: {unity_project_root}"}

    @mcp.tool(tags=make_group_tags("core"))
    async def list_unity_project_roots() -> dict[str, Any]:
        """List editor instances with fresh per-instance heartbeats."""
        projects = discover_unity_instances()
        return {"success": bool(projects), "tool": "list_unity_project_roots",
                "projects": projects, "count": len(projects),
                "message": f"Found {len(projects)} Unity instance(s)"}

    @mcp.tool(tags=make_group_tags("core"))
    async def get_unity_info() -> dict[str, Any]:
        """Get current Unity project info (path, name, version) via TCP.

        MUST be called before any Unity development task to confirm the target project.
        Returns project_path, project_name, assets_path, unity_version, and port.

        This tool communicates directly with Unity's PluginHub via the built-in
        'get_info' TCP command, bypassing the ToolDispatcher queue for instant response.
        """
        try:
            bridge = get_bridge()
            info = await bridge.get_unity_info()
            return {
                "success": True,
                "tool": "get_unity_info",
                "result": info,
            }
        except ConnectionError as ex:
            return make_error(
                UnifiedErrorCode.CONNECTION_LOST,
                message=f"Cannot connect to Unity: {ex}. Is Unity running with MCP enabled?",
            )
        except Exception as ex:
            return make_error(
                UnifiedErrorCode.TOOL_EXECUTION_ERROR,
                message=f"Failed to get Unity info: {ex}",
            )
