"""Tool groups derived from registered FastMCP tags."""
from __future__ import annotations

GROUP_TAG_PREFIX = "group:"
_TOOL_GROUP_MAP: dict[str, str] = {}

def get_tool_group(tool_name: str) -> str | None:
    return _TOOL_GROUP_MAP.get(tool_name)

def get_all_groups() -> set[str]:
    return set(_TOOL_GROUP_MAP.values())

def get_tools_in_group(group: str) -> list[str]:
    return [name for name, value in _TOOL_GROUP_MAP.items() if value == group]

def get_full_map() -> dict[str, str]:
    return _TOOL_GROUP_MAP.copy()

def clear() -> None:
    _TOOL_GROUP_MAP.clear()

async def build_group_map_from_mcp(mcp) -> dict[str, str]:
    tools = await mcp.list_tools()
    clear()
    for tool in tools:
        groups = sorted(tag[len(GROUP_TAG_PREFIX):] for tag in tool.tags if tag.startswith(GROUP_TAG_PREFIX))
        if len(groups) != 1:
            raise ValueError(f"Expected one group tag for {tool.name}: {groups}")
        _TOOL_GROUP_MAP[tool.name] = groups[0]
    return get_full_map()

def make_group_tag(group: str) -> str:
    return f"{GROUP_TAG_PREFIX}{group}"

def make_group_tags(group: str) -> set[str]:
    return {make_group_tag(group)}
