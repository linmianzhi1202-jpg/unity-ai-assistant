---
name: unity-editor-control
version: 0.1.0
category: unity
description: "Unity 编辑器操控技能 — 通过 MCP 工具编排场景管理、对象操作、组件配置和构建运行的完整工作流"
triggers:
  - "操控 Unity 编辑器"
  - "Unity 编辑器操作"
  - "管理 Unity 场景"
  - "创建 Unity 游戏对象"
  - "Unity 编辑器工作流"
---

# Unity 编辑器操控技能

## 概述

本技能封装 MCP Server 的 57 个 Unity 操作工具为 CodeBuddy 可编排的工作流，覆盖场景管理、对象操作、组件配置和构建运行四大类操作。

**核心原则**：MCP 工具通过 `unified-mcp-unity` 服务器调用，CodeBuddy Agent 不直接调用，而是通过 Skill 定义编排模式。

## 工作流编排

### 工作流 1：场景管理

**触发**：用户要求查看场景、保存场景、切换场景

**步骤**：
1. `list_game_objects_in_hierarchy` — 获取场景层级
2. `get_game_object_info` — 查询特定对象详情
3. `save_scene` — 保存当前场景
4. `open_scene` — 打开指定场景

**示例编排**：
```
用户: "查看当前场景的层级结构"
→ list_game_objects_in_hierarchy(name_filter="", max_depth=3)
→ 返回格式化的层级树
→ 如有特定对象: get_game_object_info(gameobject_path="Player")
```

### 工作流 2：对象操作

**触发**：用户要求创建/删除/查找/变换游戏对象

**步骤**：
1. `create_game_object` — 创建对象（指定 primitive_type 或 prefab_path）
2. `set_transform` — 设置位置/旋转/缩放
3. `parent_game_object` — 设置父子关系
4. `duplicate_game_object` / `delete_game_object` — 复制/删除

**示例编排**：
```
用户: "在原点创建一个红色立方体"
→ create_game_object(name="RedCube", primitive_type="Cube", position="0,1,0")
→ add_component(gameobject_path="RedCube", component_type="Renderer") // 如需自定义
→ set_property(gameobject_path="RedCube", component_type="MeshRenderer",
    property_name="material.color", value="1,0,0,1")
```

### 工作流 3：组件配置

**触发**：用户要求添加/移除/设置组件属性

**步骤**：
1. `add_component` — 添加组件
2. `set_property` — 设置组件属性
3. `remove_component` — 移除组件
4. `get_game_object_info(include_components=true)` — 查看组件详情

**示例编排**：
```
用户: "给 Player 添加刚体组件并设置质量为 5"
→ add_component(gameobject_path="Player", component_type="Rigidbody")
→ set_property(gameobject_path="Player", component_type="Rigidbody",
    property_name="mass", value="5")
```

### 工作流 4：构建运行

**触发**：用户要求运行/暂停/停止游戏

**步骤**：
1. `save_scene` — 保存当前修改
2. `play_game` — 进入播放模式
3. `stop_game` — 停止播放模式
4. `check_compile_errors` — 检查编译错误

**示例编排**：
```
用户: "运行游戏测试一下"
→ save_scene()
→ play_game()
→ (等待用户指示或自动观察)
→ stop_game()
```

## MCP 工具速查表

### 场景类
| MCP 工具 | 功能 | 关键参数 |
|----------|------|----------|
| `list_game_objects_in_hierarchy` | 列出场景层级 | name_filter, max_depth, component_filter |
| `get_game_object_info` | 获取对象详情 | gameobject_path, include_components |
| `save_scene` | 保存场景 | scene_name |
| `open_scene` | 打开场景 | scene_path, open_mode |
| `create_scene` | 创建场景 | scene_path |

### 对象类
| MCP 工具 | 功能 | 关键参数 |
|----------|------|----------|
| `create_game_object` | 创建对象 | name, position, primitive_type, prefab_path |
| `delete_game_object` | 删除对象 | gameobject_path |
| `duplicate_game_object` | 复制对象 | gameobject_path, new_name |
| `set_transform` | 设置变换 | gameobject_path, position, rotation, scale |
| `parent_game_object` | 设置父级 | child_path, parent_path |
| `rename_game_object` | 重命名 | gameobject_path, new_name |

### 组件类
| MCP 工具 | 功能 | 关键参数 |
|----------|------|----------|
| `add_component` | 添加组件 | gameobject_path, component_type |
| `remove_component` | 移除组件 | gameobject_path, component_type |
| `set_property` | 设置属性 | gameobject_path, component_type, property_name, value |

### 编辑器类
| MCP 工具 | 功能 | 关键参数 |
|----------|------|----------|
| `play_game` | 播放 | — |
| `stop_game` | 停止 | — |
| `check_compile_errors` | 编译检查 | — |
| `manage_script` | 管理脚本 | action, script_path, content |
| `refresh_unity` | 刷新资产 | force |

### 视觉类
| MCP 工具 | 功能 | 关键参数 |
|----------|------|----------|
| `capture_scene_object` | 截图场景 | gameobject_path, width, height |
| `capture_ui_canvas` | 截图 UI | canvas_path, width, height |
| `create_material` | 创建材质 | material_name, color, texture_path |
| `assign_material` | 分配材质 | gameobject_path, material_path |

## 使用约束

1. **路径格式**：所有 gameobject_path 使用 `/` 分隔层级，如 `Player/Body/Head`
2. **坐标格式**：position/rotation/scale 使用逗号分隔字符串，如 `"1,2,3"`
3. **颜色格式**：RGBA 使用 0-1 范围逗号分隔，如 `"1,0,0,1"`（红色）
4. **组件类型**：使用 Unity 内置名称，如 `Rigidbody`, `BoxCollider`, `AudioSource`
5. **安全操作**：删除对象和停止播放前应确认

## 与其他 Skill 的协作

- **unity-debug**：编辑器操作出错时，转交诊断流程
- **unity-live-dev**：在实时开发循环中，本 Skill 提供编辑器操控能力
- **unity-project-bootstrap**：项目初始化后，使用本 Skill 创建初始场景结构
