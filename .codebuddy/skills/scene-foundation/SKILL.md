---
name: scene-foundation
version: 1.0.0
category: unity
description: "场景基础建设技能 — 在任何功能开发前先建立灯光/摄影机/Canvas/地面等场景基础设施"
triggers:
  - "创建场景基础"
  - "场景初始化"
  - "Unity 场景搭建"
  - "场景灯光摄影机"
  - "BattlePrototype 场景"
---

# 场景基础建设技能

## 概述

本技能确保在开发任何游戏功能前，Unity 场景中必须先建立可见的基础元素（灯光、摄影机、Canvas、地面），使得后续所有操作都可以通过截图直观验证。

**核心原则**：没有灯光和摄影机的场景无法截图验证，因此场景基础是一切开发的前提条件。

## 前置条件

在执行场景基础建设前，必须先确认：

1. `get_unity_info()` — Unity 项目已连接
2. `set_unity_project_root()` — 项目路径已设定
3. `check_compile_errors()` — 当前无编译错误

## 场景基础建设流程

### Step 1: 创建场景

```
create_scene(scene_path="Assets/_PoemWar/Scenes/BattlePrototype.unity", add_to_build_settings=true)
save_scene(scene_name="BattlePrototype")
```

**验证**：`capture_scene_object()` 确认空白场景已创建

### Step 2: 添加灯光

```
create_game_object(name="Directional Light", primitive_type="", position="0,3,0")
```

配置灯光属性：
```
set_property(gameobject_path="Directional Light", component_type="Light",
    property_name="m_Type", value="1")  // 1 = Directional
set_property(gameobject_path="Directional Light", component_type="Light",
    property_name="m_Color", value="1,0.95,0.85,1")  // 暖色调，模拟宣纸质感
set_property(gameobject_path="Directional Light", component_type="Light",
    property_name="m_Intensity", value="1.2")
set_transform(gameobject_path="Directional Light", rotation="50,-30,0")
```

**验证**：`check_compile_errors()` + `get_unity_logs(show_errors=true)`

### Step 3: 添加摄影机

```
create_game_object(name="Main Camera", position="0,10,-5")
add_component(gameobject_path="Main Camera", component_type="Camera")
```

配置正交投影（适合 2.5D 棋盘视角）：
```
set_property(gameobject_path="Main Camera", component_type="Camera",
    property_name="orthographic", value="true")
set_property(gameobject_path="Main Camera", component_type="Camera",
    property_name="orthographicSize", value="8")
set_property(gameobject_path="Main Camera", component_type="Camera",
    property_name="clearFlags", value="1")  // SolidColor
set_property(gameobject_path="Main Camera", component_type="Camera",
    property_name="backgroundColor", value="0.96,0.9,0.83,1")  // #F5E6D3 宣纸底色
set_transform(gameobject_path="Main Camera", rotation="45,0,0")
```

**验证**：`capture_scene_object()` 确认摄影机视角正确

### Step 4: 添加 Canvas + EventSystem

```
create_ui_element(element_type="panel", element_name="GameCanvas", parent_path="")
```

Canvas 配置：
```
set_property(gameobject_path="GameCanvas", component_type="Canvas",
    property_name="renderMode", value="1")  // ScreenSpace-Overlay
set_property(gameobject_path="GameCanvas", component_type="CanvasScaler",
    property_name="uiScaleMode", value="1")  // ScaleWithScreenSize
set_property(gameobject_path="GameCanvas", component_type="CanvasScaler",
    property_name="referenceResolution", value="1920,1080")
```

**验证**：`capture_ui_canvas()` 确认 Canvas 已创建

### Step 5: 添加地面（棋盘底板）

```
create_game_object(name="BoardGround", primitive_type="Plane", position="0,0,0")
set_transform(gameobject_path="BoardGround", scale="2,1,2")
```

创建地面材质：
```
create_material(material_name="BoardGround_Mat", color="0.96,0.9,0.83,1",
    material_path="Assets/_PoemWar/Art/Materials")
assign_material(gameobject_path="BoardGround",
    material_path="Assets/_PoemWar/Art/Materials/BoardGround_Mat.mat")
```

**验证**：`capture_scene_object()` 确认地面可见

### Step 6: 保存场景并最终验证

```
save_scene(scene_name="BattlePrototype")
```

**最终三重门控**：
1. `check_compile_errors()` — 零编译错误
2. `get_unity_logs(show_errors=true)` — 零运行时错误
3. `capture_scene_object(width=1280, height=720)` — 场景完整可见

## 场景基础元素清单

| 元素 | 名称 | 用途 | 关键属性 |
|------|------|------|----------|
| 灯光 | Directional Light | 场景照明 | 暖色调, Intensity=1.2 |
| 摄影机 | Main Camera | 2.5D 俯视 | 正交, Size=8, 45°俯角 |
| 画布 | GameCanvas | UI 容器 | 1920x1080 参考分辨率 |
| 事件系统 | EventSystem | UI 交互 | 默认配置 |
| 地面 | BoardGround | 棋盘底板 | 宣纸色(#F5E6D3) |

## 常见问题与修复

| 问题 | 原因 | 修复 |
|------|------|------|
| 场景全黑 | 缺少灯光 | 添加 Directional Light |
| 看不到对象 | 摄影机位置/角度错误 | 调整 Camera position 和 rotation |
| UI 不显示 | 缺少 Canvas 或 EventSystem | 添加 Canvas + EventSystem |
| 对象粉色 | 材质缺失 | 创建材质并分配 |
| 地面不显示 | Plane 太小或被裁剪 | 调整 scale 和 Camera far clip |

## 与其他 Skill 的协作

| 协作 Skill | 触发条件 | 交接内容 |
|------------|----------|----------|
| `unity-live-dev` | 场景基础创建后 | 进入实时开发循环 |
| `unity-debug` | 任何步骤出错 | 错误码和场景状态 |
| `unity-editor-control` | 需要更复杂的场景操作 | 对象路径和操作类型 |
| `unity-project-bootstrap` | 项目初始化阶段 | 策略游戏模板参数 |

## 使用约束

1. 场景基础建设必须在任何游戏逻辑脚本之前完成
2. 每个步骤必须走完三重门控才能继续下一步
3. 摄影机使用正交投影（orthographic），不适合 FPS/TPS 视角
4. Canvas 使用 ScreenSpace-Overlay，适合 2D UI
5. 地面颜色使用宣纸底色(#F5E6D3)，后续可替换为正式美术
