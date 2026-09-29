---
name: test-setup
description: 测试设置 — 搭建测试框架，配置测试工具
version: 0.2.0
category: game-development
whenToUse: >
  当需要搭建自动化测试基础设施、配置测试运行器、
  创建标准目录布局并设置 CI/CD 以便每次推送时运行测试时，使用此技能。
  在项目的技术设置阶段运行一次，在任何实施开始之前。
input:
  - 项目根目录路径（默认当前工作区）
  - force 参数（可选，强制重新生成）
output:
  - tests/ 目录结构
  - .github/workflows/tests.yml (CI/CD 工作流)
  - 引擎特定的测试配置文件
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 测试设置技能

## 技能概述

为项目搭建自动化测试基础设施。检测已配置的引擎，生成适当的测试运行器配置，创建标准目录布局，并连接 CI/CD 以便每次推送时运行测试。

**适用场景**：
- 在项目的技术设置阶段运行一次，在任何实施开始之前
- 测试框架在早期（冲刺开始时）安装成本约为 30 分钟
- 在冲刺四次时安装测试框架成本约为 3 个冲刺

**输出**：`tests/` 目录结构 + `.github/workflows/tests.yml`

## 使用方式

- 通过 Agent 触发：当用户说「测试设置」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill test-setup [force]`
  - `force` 参数：即使文件已存在也重新生成（但不会覆盖现有测试文件）

---

## 阶段 0: 检测引擎和现有状态

### 1. 读取引擎配置

- 读取 `.claude/docs/technical-preferences.md` 并提取 `Engine:` 值。
- 如果引擎未配置（`[TO BE CONFIGURED]`），停止：
  > "引擎未配置。首先运行 `/setup-engine`，然后重新运行 `/test-setup`。"

### 2. 检查现有测试基础设施

- 全局搜索 `tests/` — 目录是否存在？
- 全局搜索 `tests/unit/` 和 `tests/integration/` — 子目录是否存在？
- 全局搜索 `.github/workflows/` — CI 工作流文件是否存在？
- 全局搜索引擎特定的工件：
  - Godot: `tests/gdunit4_runner.gd`
  - Unity: `tests/EditMode/`、`tests/PlayMode/`
  - Unreal: `Source/Tests/`

### 3. 报告发现

- "引擎：[引擎]。测试目录：[找到 / 未找到]。CI 工作流：[找到 / 未找到]。"
- 如果一切已存在且未传递 `force` 参数：
  > "测试基础设施似乎已就绪。使用 `/test-setup force` 重新运行以重新生成。继续不会覆盖现有测试文件。"

如果传递了 `force` 参数，跳过"已存在"提前退出并继续 — 但仍不会覆盖给定路径上已存在的文件。仅创建缺失的文件。

---

## 阶段 1: 展示计划

根据检测到的引擎和现有状态，展示计划：

```markdown
## 测试设置计划 — [引擎]

我将创建以下内容（跳过任何已存在的内容）：

tests/
  unit/           — 公式、状态和逻辑的隔离单元测试
  integration/    — 跨系统测试和保存/加载往返
  smoke/          — 关键路径测试列表（15 分钟手动门控）
  evidence/       — 屏幕截图和手动测试签署记录
  README.md       — 测试框架文档

[引擎特定的文件 — 见下方的每引擎详细信息]

.github/workflows/tests.yml  — CI：每次推送到 main 时运行测试

预计时间：约 5 分钟创建所有文件。
```

询问："我可以创建这些文件吗？我将不会覆盖这些路径上任何已存在的测试文件。"

未经批准不得继续。

---

## 阶段 2: 创建目录结构

批准后，创建以下文件：

### `tests/README.md`

```markdown
# 测试基础设施

**引擎**: [引擎名称 + 版本]
**测试框架**: [GdUnit4 | Unity Test Framework | UE Automation]
**CI**: `.github/workflows/tests.yml`
**设置日期**: [日期]

## 目录布局

```
tests/
  unit/           # 隔离单元测试（公式、状态机、逻辑）
  integration/    # 跨系统和保存/加载测试
  smoke/          # /smoke-check 门控的关键路径测试列表
  evidence/       # 屏幕截图日志和手动测试签署记录
```

## 运行测试

[引擎特定的命令 — 见下方]

## 测试命名

- **文件**: `[system]_[feature]_test.[ext]`
- **函数**: `test_[scenario]_[expected]`
- **示例**: `combat_damage_test.gd` → `test_base_attack_returns_expected_damage()`

## 故事类型 → 测试证据

| 故事类型 | 必需证据 | 位置 |
|-----------|--------------|----------|
| 逻辑 | 自动化单元测试 — 必须通过 | `tests/unit/[system]/` |
| 集成 | 集成测试或试玩文档 | `tests/integration/[system]/` |
| 视觉/感觉 | 屏幕截图 + 负责人签署 | `tests/evidence/` |
| UI | 手动遍历或交互测试 | `tests/evidence/` |
| 配置/数据 | 冒烟检查通过 | `production/qa/smoke-*.md` |

## CI

测试在每次推送到 `main` 和每个拉取请求时自动运行。
测试套件失败会阻止合并。
```

### 引擎特定的文件

#### Godot 4（`Engine: Godot`）

创建 `tests/gdunit4_runner.gd`：

```gdscript
# GdUnit4 测试运行器 — 由 CI 和 /smoke-check 调用
# 用法：godot --headless --script tests/gdunit4_runner.gd
extends SceneTree

func _init() -> void:
    var runner := load("res://addons/gdunit4/GdUnitRunner.gd")
    if runner == null:
        push_error("未找到 GdUnit4。通过 AssetLib 或 addons/ 安装。")
        quit(1)
        return
    var instance = runner.new()
    instance.run_tests()
    quit(0)
```

创建 `tests/unit/.gdignore_placeholder`，内容为：
`# 单元测试放在此处 — 每个系统一个子目录（例如 tests/unit/combat/）`

创建 `tests/integration/.gdignore_placeholder`，内容为：
`# 集成测试放在此处 — 每个系统一个子目录`

在 README 中注明：**安装 GdUnit4**
```
1. 打开 Godot → AssetLib → 搜索 "GdUnit4" → 下载并安装
2. 启用插件：项目 → 项目设置 → 插件 → GdUnit4 ✓
3. 重新启动编辑器
4. 验证：res://addons/gdunit4/ 存在
```

#### Unity（`Engine: Unity`）

创建 `tests/EditMode/README.md`：

```markdown
# 编辑模式测试

在不进入播放模式的情况下运行的单元测试。
用于纯逻辑：公式、状态机、数据验证。
需要程序集定义：`tests/EditMode/EditModeTests.asmdef`
```

创建 `tests/PlayMode/README.md`：

```markdown
# 播放模式测试

在真实游戏场景中运行的集成测试。
用于跨系统交互、物理和协程。
需要程序集定义：`tests/PlayMode/PlayModeTests.asmdef`
```

在 README 中注明：**启用 Unity 测试框架**
```
窗口 → 常规 → 测试运行器
（Unity 2019+ 默认包含 Unity 测试框架）
```

#### Unreal Engine（`Engine: Unreal` 或 `Engine: UE5`）

创建 `Source/Tests/README.md`：

```markdown
# Unreal 自动化测试

测试使用 UE 自动化测试框架。
运行 via：会话前端 → 自动化 → 选择 "MyGame." 测试
或无头运行：UnrealEditor -nullrhi -ExecCmds="Automation RunTests MyGame.; Quit"

测试类命名：F[SystemName]Test
测试类别命名："MyGame.[System].[Feature]"
```

---

## 阶段 3: 创建 CI/CD 工作流

### Godot 4

创建 `.github/workflows/tests.yml`：

```yaml
name: 自动化测试

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: 运行 GdUnit4 测试
    runs-on: ubuntu-latest

    steps:
      - name: 检出
        uses: actions/checkout@v4
        with:
          lfs: true

      - name: 运行 GdUnit4 测试
        uses: MikeSchulze/gdunit4-action@v1
        with:
          godot-version: '[从 docs/engine-reference/godot/VERSION.md 的版本]'
          paths: |
            tests/unit
            tests/integration
          report-name: test-results

      - name: 上传测试结果
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: reports/
```

### Unity

创建 `.github/workflows/tests.yml`：

```yaml
name: 自动化测试

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: 运行 Unity 测试
    runs-on: ubuntu-latest

    steps:
      - name: 检出
        uses: actions/checkout@v4
        with:
          lfs: true

      - name: 运行编辑模式测试
        uses: game-ci/unity-test-runner@v4
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
        with:
          testMode: editmode
          artifactsPath: test-results/editmode

      - name: 运行播放模式测试
        uses: game-ci/unity-test-runner@v4
        env:
          UNITY_LICENSE: ${{ secrets.UNITY_LICENSE }}
        with:
          testMode: playmode
          artifactsPath: test-results/playmode

      - name: 上传测试结果
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: test-results/
```

注意：Unity CI 需要 `UNITY_LICENSE` 密钥。在首次 CI 运行之前添加到 GitHub 仓库密钥。

### Unreal Engine

创建 `.github/workflows/tests.yml`：

```yaml
name: 自动化测试

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: 运行 UE 自动化测试
    runs-on: self-hosted  # UE 需要安装了编辑器的本地运行器

    steps:
      - name: 检出
        uses: actions/checkout@v4
        with:
          lfs: true

      - name: 运行自动化测试
        run: |
          "$UE_EDITOR_PATH" "${{ github.workspace }}/[项目名称].uproject" \
            -nullrhi -nosound \
            -ExecCmds="Automation RunTests MyGame.; Quit" \
            -log -unattended
        shell: bash

      - name: 上传日志
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-logs
          path: Saved/Logs/
```

注意：UE CI 需要安装了 Unreal Editor 的自托管运行器。在运行器上设置 `UE_EDITOR_PATH` 环境变量。

---

## 阶段 4: 创建冒烟测试种子

创建 `tests/smoke/critical-paths.md`：

```markdown
# 冒烟测试：关键路径

**目的**：在 any QA 移交之前，在 15 分钟内运行这 10-15 个检查。
**通过**: `/smoke-check`（读取此文件）
**更新**：实施新核心系统时添加新条目。

## 核心稳定性（始终运行）

1. 游戏启动到主菜单无崩溃
2. 可以从主菜单开始新游戏 / 会话
3. 主菜单响应所有输入而无冻结

## 核心机制（按冲刺更新）

<!-- 在实施每个冲刺的第一个核心系统时在此处添加 -->
<!-- 示例："玩家可以移动、跳跃，并且摄像机正确跟随" -->
4. [主要机制 — 实施第一个核心系统时更新]

## 数据完整性

5. 保存游戏无错误完成（一旦实施保存系统）
6. 加载游戏恢复正确的状态（一旦实施加载系统）

## 性能

7. 在目标硬件上无可见帧率下降（60fps 目标）
8. 5 分钟游戏期间无内存增长（一旦实施核心循环）
```

---

## 阶段 5: 设置后摘要

写入所有文件后，报告：

```markdown
为 [引擎] 创建的测试基础设施。

已创建的文件：
- tests/README.md
- tests/unit/（目录）
- tests/integration/（目录）
- tests/smoke/critical-paths.md
- tests/evidence/（目录）
- [引擎特定的文件]
- .github/workflows/tests.yml

下一步：
1. [引擎特定的安装步骤，例如 "通过 AssetLib 安装 GdUnit4"]
2. 编写你的第一个测试：创建 tests/unit/[第一个系统]/[系统]_test.[ext]
3. 在第一个冲刺之前运行 `/qa-plan sprint` 以分类故事并设置测试证据需求
4. 每次 QA 移交之前 `/smoke-check`

门控说明：/gate-check 技术设置 → 预生产现在需要：
- tests/ 目录，包含 unit/ 和 integration/ 子目录
- .github/workflows/tests.yml
- 至少一个示例测试文件

在前进之前运行 /test-setup 并编写一个示例测试。
```

判定：**完成** — 测试框架已搭建并且 CI/CD 已连接。

---

## 协作协议

- **永远不要覆盖现有测试文件** — 仅创建缺失的文件。如果测试运行器文件存在，按原样保留它。
- **始终在创建文件之前询问** — 阶段 1 需要明确批准。
- **引擎检测是不可协商的** — 如果引擎未配置，停止并重新定向到 `/setup-engine`。不要猜测。
- **`force` 标志跳过"已存在"提前退出，但永远不会覆盖。**
  它的意思是"即使目录已存在，也创建任何缺失的文件。"
- 对于 Unity CI，注意必须手动配置 `UNITY_LICENSE` 密钥。不要尝试自动化许可证管理。

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
