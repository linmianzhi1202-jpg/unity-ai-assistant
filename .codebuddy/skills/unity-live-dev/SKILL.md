---
name: unity-live-dev
version: 0.1.0
category: unity
description: "Unity 实时开发循环技能 — 定义'写代码→编译→测试→截图→修正'闭环流程，通过 MCP 工具链实现即时反馈"
triggers:
  - "实时开发 Unity"
  - "Unity 热重载"
  - "Unity 即时反馈"
  - "Unity 代码测试循环"
---

# Unity 实时开发循环技能

## 概述

本技能定义 CodeBuddy 与 Unity 编辑器之间的实时反馈闭环，通过 MCP 工具链实现"写代码→编译→测试→截图→修正"的迭代循环，消除传统开发中"手动复制→手动测试→手动反馈"的断链。

## 核心循环

```
┌─────────────────────────────────────────────────┐
│                  实时开发循环                      │
│                                                   │
│  Step 1: 写代码 ───→ manage_script(action=update) │
│      ↓                                            │
│  Step 2: 编译检查 ─→ check_compile_errors()       │
│      ↓                                            │
│  Step 3: 运行测试 ─→ play_game() → stop_game()    │
│      ↓                                            │
│  Step 4: 截图验证 ─→ capture_scene_object()       │
│      ↓                                            │
│  Step 5: 分析结果 ─→ 如需修正，回到 Step 1         │
│                                                   │
└─────────────────────────────────────────────────┘
```

## 各步骤详细说明

### Step 1: 写代码

**目标**：通过 MCP 工具直接写入 Unity 项目

**MCP 工具**：`manage_script`

**操作**：
```python
# 创建新脚本
manage_script(action="create", script_path="Assets/Scripts/PlayerController.cs", content="...")

# 更新现有脚本
manage_script(action="update", script_path="Assets/Scripts/PlayerController.cs", content="...")
```

**约束**：
- 脚本路径必须以 `Assets/` 开头
- 内容必须包含正确的 `using` 声明和命名空间
- 遵循 `unity-project-structure` Rule 的目录规范

### Step 2: 编译检查

**目标**：验证代码无编译错误

**MCP 工具**：`check_compile_errors`, `refresh_unity`

**操作**：
```python
# 刷新资产数据库
refresh_unity(force=False)

# 检查编译错误
errors = check_compile_errors()
if errors:
    # 解析错误 → 转交 unity-debug Skill
    # 修正代码 → 回到 Step 1
```

**常见编译错误处理**：

| 错误 | 修复动作 |
|------|----------|
| CS0103 | 添加 `using` 声明 |
| CS0246 | 添加 `.asmdef` 引用或安装包 |
| CS1061 | 查询废弃 API 替代（`unity-csharp-patterns` §7） |

### Step 3: 运行测试

**目标**：在 Play Mode 下验证功能

**MCP 工具**：`save_scene`, `play_game`, `stop_game`, `get_unity_logs`

**操作**：
```python
# 保存当前场景
save_scene()

# 进入播放模式
play_game()

# 等待几秒观察（或通过日志监控）
logs = get_unity_logs(limit=20, show_errors=True)

# 停止播放
stop_game()
```

**约束**：
- 播放前必须保存场景
- 监控运行时错误（NullReference 等）
- 停止播放后才能修改代码

### Step 4: 截图验证

**目标**：通过截图直观验证 UI 布局和场景状态

**MCP 工具**：`capture_scene_object`, `capture_ui_canvas`

**操作**：
```python
# 场景截图（验证 3D 布局）
capture_scene_object(width=1280, height=720)

# UI 截图（验证界面布局）
capture_ui_canvas(width=1920, height=1080)

# 聚焦特定对象
capture_scene_object(gameobject_path="Player", width=512, height=512)
```

**截图检查点**：
- [ ] UI 元素是否正确显示
- [ ] 对象位置是否正确
- [ ] 材质/颜色是否正确
- [ ] 布局是否对齐

### Step 5: 分析与修正

**目标**：基于编译结果、运行日志和截图决定是否需要修正

**决策树**：
```
编译错误？
├── 是 → Step 1（修正代码）
└── 否
    运行时错误？
    ├── 是 → unity-debug Skill 诊断 → Step 1（修正代码）
    └── 否
        截图验证通过？
        ├── 是 → ✅ 完成
        └── 否 → Step 1（调整参数/位置）
```

## 快速迭代模式

### 模式 1：代码热修

适用：修改现有脚本逻辑

```
manage_script(update) → refresh_unity → check_compile_errors → ✅/修正
```

### 模式 2：UI 布局调整

适用：调整 UI 元素位置/大小

```
set_rect_transform → capture_ui_canvas → 分析 → 调整
```

### 模式 3：场景搭建

适用：创建/调整场景对象

```
create_game_object → set_transform → capture_scene_object → 调整
```

### 模式 4：参数调优

适用：调整 Inspector 参数

```
set_property → play_game → get_unity_logs → stop_game → 调整
```

## 与其他 Skill 的协作

| 协作 Skill | 触发条件 | 交接内容 |
|------------|----------|----------|
| `unity-debug` | 编译/运行时错误 | 错误码和调用栈 |
| `unity-editor-control` | 需要编辑器操作 | 对象路径和操作类型 |
| `unity-project-bootstrap` | 项目初始化 | 初始脚本内容 |

## 安全约束

1. 修改代码前建议先 `save_scene`
2. 不要在 Play Mode 中修改脚本（Unity 限制）
3. 截图分辨率不超过 1920×1080（避免过大）
4. 迭代循环最多 5 次，超出需用户确认
5. 涉及删除操作需显式确认
