"""
Scene Inspector Reference Repair Tools — Phase E.

Automatically audits and repairs broken SerializeField object references on
MonoBehaviour components after scene loading or prefab instantiation.

This tool should be called after every manage_scene load, create_game_object,
or add_component operation to ensure Inspector references are intact.

Group: core
"""

from __future__ import annotations
from services.tools.tool_router import get_router

import logging
from typing import Any

from fastmcp import FastMCP

from services.tools.tool_group_map import make_group_tags

logger = logging.getLogger(__name__)


def register_reference_repair_tools(mcp: FastMCP) -> None:
    """Register scene reference repair tools with the MCP server.

    Tools registered:
    - repair_scene_references  — Audit & repair null SerializeField refs on a component.
    """
    group = "core"

    @mcp.tool(tags=make_group_tags("core"))
    async def repair_scene_references(
        gameobject_path: str,
        component_type: str,
    ) -> dict[str, Any]:
        """审计并修复一个组件上所有空的 SerializeField 对象引用。

        调用时机：每次 manage_scene load、create_game_object、add_component 之后。

        功能：
        1. 遍历组件的所有序列化字段
        2. 查找 ObjectReference 类型且值为 null 的字段
        3. 用字段名匹配场景层级路径自动修复（如 playButton → Canvas/Button）
        4. 返回完整审计报告

        Args:
            gameobject_path: GameObject 层级路径，例如 "GameManager"、"Canvas/TowerPanel/FireballTowerButton"
            component_type: 组件类型，例如 "GameManager"、"TowerManager"、"Tower"

        Returns:
            dict: {
                success: bool,
                component: str,
                path: str,
                total_null_refs: int,    # 空引用总数
                repaired_count: int,      # 成功修复数
                issues: [
                    {
                        field: str,                  # 字段名
                        displayName: str,            # Inspector 显示名
                        null_reference: bool,        # 是否空引用
                        resolved_path: str|null,     # 匹配到的 GameObject 名
                        repaired: bool,              # 是否修复成功
                        strategy: str,               # 匹配策略: exact/suffix_stripped/camelcase_split/gameobject_find/none
                        auto_created_component: bool, # 是否自动创建了缺失的组件
                        failure_reason: str|null     # 失败原因: null(成功)/no_gameobject_found/component_type_missing
                    },
                    ...
                ]
            }

        Example:
            repair_scene_references(
                gameobject_path="GameManager",
                component_type="GameManager"
            )
        """
        args: dict[str, Any] = {'path': gameobject_path, 'component_type': component_type}

        try:
            result = await get_router().send_tool('repair_scene_references', args)
            unity_result = result.get("result", {})
            warnings = unity_result.get("warnings", [])
            configuration_warnings_count = unity_result.get("configuration_warnings_count", len(warnings))

            return {
                "success": result.get("status") == "success",
                "tool": "repair_scene_references",
                "params": {
                    "gameobject_path": gameobject_path,
                    "component_type": component_type,
                },
                "component": unity_result.get("component", component_type),
                "path": unity_result.get("path", gameobject_path),
                "total_null_refs": unity_result.get("total_null_refs", 0),
                "repaired_count": unity_result.get("repaired_count", 0),
                "issues": unity_result.get("issues", []),
                "warnings": warnings,
                "configuration_warnings_count": configuration_warnings_count,
                "message": (
                    f"[{component_type} @ {gameobject_path}] "
                    f"{unity_result.get('total_null_refs', 0)} null refs, "
                    f"{unity_result.get('repaired_count', 0)} repaired, "
                    f"{configuration_warnings_count} warnings"
                    if result.get("status") == "success"
                    else result.get("error", "Unknown error")
                ),
            }
        except Exception as ex:
            logger.error(f"repair_scene_references failed: {ex}")
            return {
                "success": False,
                "tool": "repair_scene_references",
                "error": str(ex),
                "message": f"Failed to audit references: {ex}",
            }
