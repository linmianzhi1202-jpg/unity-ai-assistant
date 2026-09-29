---
name: setup-engine
description: 设置引擎 — 配置游戏引擎，填充版本感知参考文档
version: 0.2.0
category: game-development
whenToUse: >
  需要配置游戏引擎、填充版本感知参考文档、选择适合项目的游戏引擎、
  或更新引擎参考文档时，使用此技能。
  当用户提到「设置引擎」「配置引擎」「选择引擎」「引擎迁移」等关键词时，应使用此技能。
  支持四种模式：完整规格、仅引擎、引导模式、刷新/升级子命令。
input:
- 项目根目录路径（默认当前工作区）
- 引擎名称、版本号、或子命令（refresh/upgrade）
output:
- 结构化结果报告（Markdown 格式）
- CLAUDE.md 技术栈更新
- docs/engine-reference/[engine]/ 参考文档
- .codebuddy/docs/technical-preferences.md 技术偏好配置
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
- web_search
- web_fetch
context: inline
---

# 设置引擎技能

## 技能概述

配置游戏引擎，填充版本感知参考文档。此技能帮助选择适合项目的游戏引擎（Godot、Unity、Unreal Engine），配置技术栈，并创建版本感知的参考文档以支持准确的技术决策。

**四种模式**：
- **完整规格**：`/setup-engine godot 4.6` — 提供引擎和版本
- **仅引擎**：`/setup-engine unity` — 提供引擎，将查找版本
- **无参数**：`/setup-engine` — 完全引导模式（引擎推荐 + 版本）
- **刷新**：`/setup-engine refresh` — 更新参考文档（见第 10 节）
- **升级**：`/setup-engine upgrade [旧版本] [新版本]` — 迁移到新引擎版本（见第 11 节）

---

## 使用方式

- **通过 Agent 触发**：当用户说「设置引擎」或相关需求时，Agent 应自动加载此 Skill
- **手动触发**：`/skill setup-engine [参数]`

---

## 1. 解析参数

四种模式：

- **完整规格**：`/setup-engine godot 4.6` — 提供引擎和版本
- **仅引擎**：`/setup-engine unity` — 提供引擎，将查找版本
- **无参数**：`/setup-engine` — 完全引导模式（引擎推荐 + 版本）
- **刷新**：`/setup-engine refresh` — 更新参考文档（见第 10 节）
- **升级**：`/setup-engine upgrade [旧版本] [新版本]` — 迁移到新引擎版本（见第 11 节）

---

## 2. 引导模式（无参数）

如果未指定引擎，运行交互式引擎选择流程：

### 检查现有游戏概念

- 如果存在，读取 `design/gdd/game-concept.md` — 提取类型、范围、平台、目标、美术风格、团队规模，以及来自 `/brainstorm` 的任何引擎推荐
- 如果不存在概念，通知用户：
  > "未找到游戏概念。考虑首先运行 `/brainstorm` 以发现您想构建什么 — 它也会推荐引擎。或者告诉我关于您的游戏，我可以帮您选择。"

### 如果用户想在没有概念的情况下选择，按此顺序询问：

**问题 1 —  prior 经验**（始终首先询问，通过 `AskUserQuestion`）：
- 提示："您之前使用过这些引擎中的任何一个吗？"
- 选项：`Godot` / `Unity` / `Unreal Engine 5` / `多个 — 我会解释` / `都不是`
- 如果他们选择特定引擎 → 推荐该引擎。Prior 经验胜过所有其他因素。与他们会合并跳过矩阵。
- 如果"都不是"或"多个" → 继续到下面的问题。

**问题 2-6 — 决策矩阵输入**（仅当无 prior 引擎经验时）：

**问题 2 — 目标平台**（始终 second 询问，通过 `AskUserQuestion` — 平台消除或严重权衡引擎 before 任何其他因素）：
- 提示："您为此游戏定位什么平台？"
- 选项：`PC (Steam / Epic)` / `Mobile (iOS / Android)` / `Console` / `Web / Browser` / `多平台`
- **平台规则直接输入推荐**：
  - 移动 → 强烈推荐 Unity；Unreal 是差的选择；Godot 对简单移动可行
  - 主机 → Unity 或 Unreal；Godot 主机支持需要第三方发行商或大量额外工作
  - Web → Godot 干净地导出到 web；Unity WebGL 功能正常；Unreal 的 web 支持差
  - 仅 PC → 所有引擎都可行；其他因素决定
  - 多个 → Unity 是跨 PC/移动/主机最便携的

1. **什么类型的游戏？**（2D、3D 或两者？）
2. **主要输入方法？**（键盘/鼠标、手柄、触摸或混合？）
3. **团队规模和经验？**（独立初学者、独立有经验、小团队？）
4. **引擎许可的任何预算？**（仅免费，或商业许可 OK？）

### 生成推荐

**不要**使用简单的评分矩阵来消除引擎。相反，根据下面的诚实权衡，通过用户的配置文件进行推理，然后提供 1-2 个推荐及完整上下文。始终以用户选择结束 — 永远不要强制判定。

**引擎诚实权衡：**

**Godot 4**
- 真正优势：2D（同类最佳）、风格化/独立 3D、快速迭代、永远免费（MIT）、开源、最温和的学习曲线，最适合想要完全控制的独立开发者
- 实际限制：与 Unity/Unreal 相比，3D 生态系统薄弱（3D 特定问题的教程、资产、社区答案较少）；大型开放世界 3D 在 Godot 中非常困难且基本未测试；主机导出需要第三方发行商或大量额外工作；较小的专业就业市场
- 许可现实：真正的免费，永远没有收入阈值。MIT 许可证意味着您拥有所有内容。
- **最佳适合**：任何范围的 2D 游戏；风格化/氛围 3D；包含 3D 世界（非开放世界）；学习曲线很重要的首次游戏项目；在任何规模下预算都是硬约束的项目

**Unity**
- 真正优势：中范围 3D 和移动的行业标椎； massive 资产商店和教程生态系统；C# 是专业语言；独立最佳的主机认证支持；几乎每种类型的强大社区
- 实际限制：2023 年许可争议损害了信任（运行时费用被提出然后撤回 — 政策变化的风险仍然真实）；C# 比 GDScript 有更陡的初始曲线；对于简单项目，比 Godot 更重的编辑器
- 许可现实：收入 $200K 且安装量 200K 以下免费（Unity Personal/Plus）。仅当游戏真正成功时才变得昂贵 — 大多数独立游戏永远不会达到此阈值。2023 年争议值得了解，但实际当前条款对大多数独立开发者来说合理。
- **最佳适合**：移动游戏；中范围 3D；定位主机的游戏；有 C# 背景的开发者；需要大型资产商店的项目；2-5 人的团队

**Unreal Engine 5**
- 真正优势：同类最佳 3D 视觉效果（Lumen、Nanite、Chaos 物理）；AAA 和照片级真实感 3D 的行业标椎；大型开放世界支持成熟且经过生产测试；Blueprint 可视化脚本降低 C++ 障碍；针对高端 PC 或主机的游戏强大
- 实际限制：最陡的学习曲线；最重的编辑器（慢编译时间、大型项目大小）；对于风格化/2D/小范围游戏过度杀伤；C++ 真正困难；不适合移动或 web；超过 $1M 总收入后 5% 版税
- 许可现实：每个标题超过 $1M 总收入后才适用 5% 版税。对于首次游戏或任何未达到 $1M 的游戏，它不花费任何东西。此阈值足够高，大多数独立开发者永远不会支付。
- **最佳适合**：AAA 质量 3D；大型开放世界游戏；照片级真实感视觉效果；有 C++ 经验或愿意使用 Blueprint 的开发者；视觉保真度是核心卖点的针对高端 PC/主机的游戏

**类型特定指导**（将此因素输入推荐）：
- 任何风格 2D → 强烈推荐 Godot
- 风格化/氛围/包含世界 3D → Godot 可行，Unity 可靠替代
- 开放世界 3D（大型、无缝）→ Unity 或 Unreal；Godot 对此未经生产验证
- 照片级真实感 3D/AAA 质量 → Unreal
- 移动优先 → 强烈推荐 Unity
- 主机优先 → Unity 或 Unreal；Godot 主机支持需要额外工作
- 恐怖/叙事/步行模拟 → 任何引擎；匹配美术风格和团队经验
- 动作 RPG/Soulslike → Unity 或 Unreal 用于 3D；社区支持和资产在这里很重要
- 平台 2D → Godot
- 策略/顶视/RTS → Godot 或 Unity 取决于 2D vs 3D

**推荐格式：**
1. 显示以用户特定因素作为行的比较表
2. 给出主要推荐和诚实的推理
3. 命名最佳替代方案以及何时改为选择它
4. 明确说明："这是起点，不是判定 — 您可以在项目之间随时迁移引擎，许多开发者在不同项目之间切换。"
5. 使用 `AskUserQuestion` 确认："这个推荐感觉正确吗，或者您想探索不同的引擎？"
   - 选项：`[主要引擎]（推荐）` / `[替代引擎]` / `[第三引擎]` / `进一步探索` / `输入其他内容`

**如果用户选择"进一步探索"：**
使用 `AskUserQuestion` 提供概念特定的深度潜水主题。始终从用户的 actual 概念生成这些选项 — 不要使用通用选项。始终至少包括：
- 主要引擎对此概念的特定限制（例如，"Godot 3D 对于 [类型] 实际上可以走多远？"）
- 替代引擎对此概念的特定权衡
- 语言选择对此概念技术挑战的影响
- 任何概念特定的技术问题（例如，自适应音频、开放世界流、多人 netcode）

用户可以选择多个主题。在返回引擎确认问题之前，深入回答每个选择的问题。

---

## 3. 查找当前版本

选择引擎后：

- 如果提供了版本，使用它
- 如果未提供版本，使用 WebSearch 查找最新的稳定版本：
  - 搜索：`"[engine] latest stable version [current year]"`
  - 与用户确认："最新的稳定 [engine] 是 [version]。使用这个吗？"

---

## 4. 更新 CLAUDE.md 技术栈

### 语言选择（仅 Godot）

如果选择了 Godot，在显示提议的技术栈 **之前** 询问用户使用哪种语言：

> "Godot 支持两种主要语言：
>
>    **A) GDScript** — 类 Python，Godot 原生，最快迭代。最适合初学者、独立开发者，以及来自 Python 或 Lua 的团队。
>    **B) C#** — .NET 8+，对 Unity 开发者熟悉，更强的 IDE 工具（Rider / Visual Studio），对重度逻辑有轻微性能优势。
>    **C) 两者** — 游戏玩法/UI 脚本使用 GDScript，性能关键系统使用 C#。高级设置 — 需要 Godot 旁边的 .NET SDK。
>
>    这个项目主要使用哪一个？"

记录选择。它决定了 CLAUDE.md 模板、命名约定、专家路由，以及整个项目中生成代码文件时生成哪个代理。

---

读取 `CLAUDE.md` 并向用户显示提议的技术栈更改。

询问："我可以将这些引擎设置写入 `CLAUDE.md` 吗？"

在進行任何编辑之前等待确认。

使用 actual 值更新技术栈部分，替换 `[CHOOSE]` 占位符：

**对于 Godot** — 使用与上述选择的语言匹配的模板。有关所有三种变体（GDScript、C#、两者），请参见本技能末尾的 **附录 A**。

**对于 Unity：**
```markdown
- **引擎**：Unity [version]
- **语言**：C#
- **构建系统**：Unity Build Pipeline
- **资产管线**：Unity Asset Import Pipeline + Addressables
```

**对于 Unreal：**
```markdown
- **引擎**：Unreal Engine [version]
- **语言**：C++（主要）、Blueprint（游戏玩法原型）
- **构建系统**：Unreal Build Tool (UBT)
- **资产管线**：Unreal Content Pipeline
```

---

## 5. 填充技术偏好

更新 CLAUDE.md 后，使用引擎适当的默认值创建或更新 `.codebuddy/docs/technical-preferences.md`。首先读取现有模板，然后填写：

### 引擎和语言部分

- 从步骤 4 中的引擎选择填写

### 命名约定（引擎默认值）

**对于 Godot** — 有关 GDScript、C# 和两者变体，请参见 **附录 A**。

**对于 Unity (C#)：**
- 类：PascalCase（例如 `PlayerController`）
- 公共字段/属性：PascalCase（例如 `MoveSpeed`）
- 私有字段：_camelCase（例如 `_moveSpeed`）
- 方法：PascalCase（例如 `TakeDamage()`）
- 文件：PascalCase 匹配类（例如 `PlayerController.cs`）
- 常量：PascalCase 或 UPPER_SNAKE_CASE

**对于 Unreal (C++)：**
- 类：带前缀的 PascalCase（`A` 用于 Actor，`U` 用于 UObject，`F` 用于 struct）
- 变量：PascalCase（例如 `MoveSpeed`）
- 函数：PascalCase（例如 `TakeDamage()`）
- 布尔值：`b` 前缀（例如 `bIsAlive`）
- 文件：匹配类 without 前缀（例如 `PlayerController.h`）

### 输入和平台部分

使用在第 2 节收集的回答（或从游戏概念提取）填充 `## 输入和平台`。使用此外映射派生值：

| 平台目标 | 手柄支持 | 触摸支持 |
|--------------|------------|------------|
| 仅 PC | 部分（推荐） | 无 |
| 主机 | 完整 | 无 |
| 移动 | 无 | 完整 |
| PC + 主机 | 完整 | 无 |
| PC + 移动 | 部分 | 完整 |
| Web | 部分 | 部分 |

对于 **主要输入**，使用游戏类型的支配性输入：
- 动作/RPG/平台游戏定位主机 → 手柄
- 策略/点选/RTS → 键盘/鼠标
- 移动游戏 → 触摸
- 跨平台 → 询问用户

在写入之前，向用户显示派生的值并询问确认或调整。

填充部分示例：
```markdown
## 输入和平台
- **目标平台**：PC、主机
- **输入方法**：键盘/鼠标、手柄
- **主要输入**：手柄
- **手柄支持**：完整
- **触摸支持**：无
- **平台注释**：所有 UI 必须支持 d-pad 导航。无仅悬停交互。
```

### 剩余部分

- **性能预算**：使用 `AskUserQuestion`：
  - 提示："我应该现在设置默认性能预算，还是稍后留下它们？"
  - 选项：`[A] 现在设置默认值（60fps、16.6ms 帧预算、引擎适当的绘制调用限制）` / `[B] 保留为 [TO BE CONFIGURED] — 我将在了解目标硬件时设置这些`
  - 如果 [A]：用建议的默认值填充。如果 [B]：保留为占位符。
- **测试**：建议引擎适当的框架（Godot 用 GUT、Unity 用 NUnit 等）— 在添加之前询问。
- **禁止模式**：保留为占位符 — 不要预填充。
- **允许的库**：保留为占位符 — 不要预填充项目目前不需要的依赖关系。仅当库正在主动集成时才在此处添加，而不是推测性地。

> **护栏**：永远不要向允许库添加推测性依赖关系。例如，除非此会话中主动开始 Steam 集成，否则不要添加 GodotSteam。发布后集成应在该工作开始时添加到允许库，而不是在引擎设置期间。

### 引擎专家路由

还在 `technical-preferences.md` 中填充 `## 引擎专家` 部分，并为所选引擎提供正确路由：

**对于 Godot** — 请参阅 **附录 A** 以获取与所选语言匹配的路由表。

**对于 Unity：**
```markdown
## 引擎专家
- **主要**：unity-specialist
- **语言/代码专家**：unity-specialist（C# 审查 — 主要覆盖它）
- **着色器专家**：unity-shader-specialist（Shader Graph、HLSL、URP/HDRP 材质）
- **UI 专家**：unity-ui-specialist（UI Toolkit UXML/USS、UGUI Canvas、runtime UI）
- **附加专家**：unity-dots-specialist（ECS、Jobs system、Burstand compiler）、unity-addressables-specialist（资产加载、内存管理、content catalogs）
- **路由注释**：为主要架构和常规 C# 代码审查生成主要。为任何 ECS/Jobs/Burst 代码生成 DOTS 专家。为渲染和视觉效果生成着色器专家。为所有界面实现生成 UI 专家。为资产管理系统生成 Addressables 专家。
```

**文件扩展路由：**

| 文件扩展名/类型 | 要生成的专家 |
|--------------|------------|
| 游戏代码（.cs 文件） | unity-specialist |
| 着色器/材质文件（.shader、.shadergraph、.mat） | unity-shader-specialist |
| UI/屏幕文件（.uxml、.uss、Canvas prefabs） | unity-ui-specialist |
| 场景/预制体/关卡文件（.unity、.prefab） | unity-specialist |
| 原生扩展/插件文件（.dll、原生插件） | unity-specialist |
| 常规架构审查 | unity-specialist |

**对于 Unreal：**
```markdown
## 引擎专家
- **主要**：unreal-specialist
- **语言/代码专家**：ue-blueprint-specialist（Blueprint graphs）或 unreal-specialist（C++）
- **着色器专家**：unreal-specialist（无专用着色器专家 — 主要覆盖材质）
- **UI 专家**：ue-umg-specialist（UMG widgets、CommonUI、input routing、widget styling）
- **附加专家**：ue-gas-specialist（Gameplay Ability System、attributes、gameplay effects）、ue-replication-specialist（property replication、RPCs、client prediction、netcode）
- **路由注释**：为主要 C++ 架构和广泛的引擎决策生成主要。为 Blueprint graph 架构和 BP/C++ 边界设计生成 Blueprint 专家。为所有能力和属性代码生成 GAS 专家。为任何多人或网络系统生成 replication 专家。为所有 UI 实现生成 UMG 专家。
```

**文件扩展路由：**

| 文件扩展名/类型 | 要生成的专家 |
|--------------|------------|
| 游戏代码（.cpp、.h 文件） | unreal-specialist |
| 着色器/材质文件（.usf、.ush、Material assets） | unreal-specialist |
| UI/屏幕文件（.umg、UMG Widget Blueprints） | ue-umg-specialist |
| 场景/预制体/关卡文件（.umap、.uasset） | unreal-specialist |
| 原生扩展/插件文件（Plugin .uplugin、modules） | unreal-specialist |
| Blueprint graphs（.uasset BP classes） | ue-blueprint-specialist |
| 常规架构审查 | unreal-specialist |

### 协作步骤

向用户显示填写的偏好。对于 Godot，包括所选语言并注意完整命名约定和路由表的位置：

> "这是 [engine]（[language if Godot]）的默认技术偏好。命名约定和专家路由在 此技能的附录 A 中 — 我将应用 [GDScript/C#/Both] 变体。想要自定义其中任何一项，还是我应该保存默认值？"

对于所有其他引擎，直接显示默认设置而不引用附录。

在写入文件之前等待批准。

---

## 6. 确定知识差距

检查引擎版本是否可能超出 LLM 的训练数据。

**已知近似覆盖**（随着模型变化更新）：
- LLM 知识截止：**2025 年 5 月**
- Godot：训练数据可能覆盖到 ~4.3
- Unity：训练数据可能覆盖到 ~2023.x / 早期 6000.x
- Unreal：训练数据可能覆盖到 ~5.3 / 早期 5.4

将用户选择的版本与这些基线进行比较：

- **在训练数据内** → `低风险` — 参考文档可选但推荐
- **接近边缘** → `中等风险` — 推荐参考文档
- **超出训练数据** → `高风险` — 需要参考文档

通知用户他们处于哪个类别以及为什么。

---

## 7. 填充引擎参考文档

### 如果在训练数据内（低风险）：

创建最小的 `docs/engine-reference/<engine>/VERSION.md`：

```markdown
# [Engine] — 版本参考

| 字段 | 值 |
|-------|-------|
| **引擎版本** | [version] |
| **项目固定** | [today's date] |
| **LLM 知识截止** | 2025 年 5 月 |
| **风险级别** | 低 — 版本在 LLM 训练数据内 |

## 注释

此引擎版本在 LLM 的训练数据内。引擎参考
文档是可选的，但如果代理建议不正确的 API，可以稍后添加。

随时运行 `/setup-engine refresh` 以填充完整参考文档。
```

**不要**创建 breaking-changes.md、deprecated-apis.md 等 — 它们会
增加上下文成本，价值最小。

### 如果超出训练数据（中等或高风险）：

通过搜索 web 创建完整参考文档集：

1. **搜索官方迁移/升级指南**：
   - `"[engine] [旧版本] to [新版本] migration guide"`
   - `"[engine] [version] breaking changes"`
   - `"[engine] [version] changelog"`
   - `"[engine] [version] deprecated API"`

2. **获取并提取** 来自官方文档：
   - 训练截止和当前之间的每个版本的 Breaking changes
   - 带有替换的 Deprecated APIs
   - 新功能和最佳实践

询问："我可以在 `docs/engine-reference/<engine>/` 下创建引擎参考文档吗？"

在写入任何文件之前等待确认。

3. **创建完整参考目录**：
   ```
   docs/engine-reference/<engine>/
   ├── VERSION.md              # 版本固定 + 知识差距分析
   ├── breaking-changes.md     # 版本间 breaking changes
   ├── deprecated-apis.md      # "不要使用 X → 使用 Y" 表
   ├── current-best-practices.md  # 训练截止后的新实践
   └── modules/                # 每个子系统的参考（根据需要创建）
   ```

4. **填充每个文件** 使用来自 web 搜索的真实数据，遵循
   现有参考文档中建立的格式。每个文件必须有一个
   "Last verified: [date]" 标头。

5. **对于模块文件**：仅当发生重大更改时
   为子系统创建模块。不要创建空或最小的模块文件。

---

## 8. 更新 CLAUDE.md 导入

询问："我可以更新 `CLAUDE.md` 中的 `@` 导入以指向新引擎参考吗？"

等待确认，然后更新"引擎版本参考"下的 `@` 导入以指向
正确的引擎：

```markdown
## 引擎版本参考

@docs/engine-reference/<engine>/VERSION.md
```

如果先前的导入指向不同的引擎（例如，从 Godot 切换到 Unity），更新它。

---

## 9. 更新代理指令

询问："我可以在引擎专家代理文件中添加版本感知部分吗？" 再进行任何编辑。

对于所选引擎的专家代理，验证它们有
"版本感知"部分。如果没有，按照
现有 Godot 专家代理中的模式添加一个。

该部分应指示代理：
1. 读取 `docs/engine-reference/<engine>/VERSION.md`
2. 在建议代码之前检查已弃用的 API
3. 检查相关版本转换的 breaking changes
4. 使用 WebSearch 验证不确定的 API

---

## 10. 刷新子命令

如果作为 `/setup-engine refresh` 调用：

1. 读取现有 `docs/engine-reference/<engine>/VERSION.md` 以获取
   当前引擎和版本
2. 使用 WebSearch 检查：
   - 自上次验证以来的新引擎版本
   - 更新的迁移指南
   - 新弃用的 API
3. 使用新发现更新所有参考文档
4. 更新所有修改文件上的 "Last verified" 日期
5. 报告更改内容

---

## 11. 升级子命令

如果作为 `/setup-engine upgrade [旧版本] [新版本]` 调用：

### 步骤 1 — 读取当前版本状态

读取 `docs/engine-reference/<engine>/VERSION.md` 以确认当前固定
版本、风险级别和任何已记录的迁移注释 URL。如果
未将 `旧版本` 作为参数提供，请使用此文件中的固定版本。

### 步骤 2 — 获取迁移指南

使用 WebSearch 和 WebFetch 定位
`旧版本` 和 `新版本` 之间的官方迁移指南：

- 搜索：`"[engine] [旧版本] to [新版本] migration guide"`
- 搜索：`"[engine] [新版本] breaking changes changelog"`
- 如果从 VERSION.md 已记录 URL，获取迁移指南 URL，
  或使用通过搜索找到的 URL。

提取：重命名的 API、删除的 API、更改的默认值、行为更改，以及
任何"必须迁移"项目。

### 步骤 3 — 升级前审计

扫描 `src/` 以查找使用已知已弃用或已在
目标版本中更改的 API 的代码：

- 使用 Grep 搜索从迁移指南提取的已弃用 API 名称（例如，旧函数名称、删除的节点类型、更改的属性名称）
- 列出每个匹配的文件，以及找到的特定 API 引用

将审计结果显示为表：

```
升级前审计：[engine] [旧版本] → [新版本]
=========================================================

需要更改的文件：
 文件                              | 已弃用的 API 找到       | 工作量
 --------------------------------- | -------------------------- | -----
  src/gameplay/player_movement.gd   | old_api_name               | 低
  src/ui/hud.gd                     | removed_node_type          | 中

需注意的 Breaking changes：
  - [来自迁移指南的更改描述]
  - [来自迁移指南的更改描述]

推荐的迁移顺序（依赖排序）：
  1. [依赖最少的系统/层首先]
  2. [下一个系统]
  ...
```

如果在 `src/` 中未找到已弃用的 API 使用，报告："在 src/ 中未找到已弃用的 API 使用 — 升级可能是低风险。"

### 步骤 4 — 在更新前确认

在进行任何更改之前询问用户：

> "升级前审计完成。在 [N] 个文件中找到已弃用的 API 使用。
> 继续将 VERSION.md 升级到 [新版本]？
> （这将更新固定版本并添加迁移注释 — 它不会
> 更改任何源文件。源迁移是手动完成的，或通过故事完成。）"

在继续之前等待明确确认。

### 步骤 5 — 更新 VERSION.md

确认后：

1. 更新 `docs/engine-reference/<engine>/VERSION.md`：
   - `引擎版本` → `[新版本]`
   - `项目固定` → 今天的日期
   - `上次文档验证` → 今天的日期
   - 重新评估并更新 `风险级别` 和 `截止后版本时间线`
     如果新版本超出 LLM 知识截止，则表
   - 添加 `## 迁移注释 — [旧版本] → [新版本]` 部分
     包含：迁移指南 URL、关键 breaking changes、中找到的已弃用 API
     在此项目中，以及来自审计的推荐迁移顺序

2. 如果引擎参考目录中存在 `breaking-changes.md` 或 `deprecated-apis.md`，
   将这些文件的新版本更改附加到。

### 步骤 6 — 升级后提醒

更新 VERSION.md 后，输出：

```
VERSION.md 已更新：[engine] [旧版本] → [新版本]

下一步：
1. 迁移上面列出的 [N] 个文件中的已弃用 API 使用
2. 升级实际引擎二进制文件后，运行 /setup-engine refresh 以
   验证没有遗漏新的弃用
3. 运行 /architecture-review — 引擎升级可能使引用特定 API 或引擎功能的 ADR 无效
4. 如果任何 ADR 被无效，运行 /propagate-design-change 以更新
   下游故事
```

---

## 12. 输出总结

设置完成后，输出：

```
引擎设置完成
=====================

引擎：          [name] [version]
语言：        [GDScript | C# | GDScript + C# | C# | C++ + Blueprint]
知识风险：  [低/中/高]
参考文档：  [已创建/已跳过]
CLAUDE.md:       [已更新]
技术偏好：      [已创建/已更新]
代理配置：    [已验证]

下一步：
1. 查看 docs/engine-reference/<engine>/VERSION.md
2. [如果从 /brainstorm] 运行 /map-systems 以将您的概念分解为单独的系统
3. [如果从 /brainstorm] 运行 /design-system 以编写每个系统 GDD（引导式，逐部分）
4. [如果从 /brainstorm] 运行 /prototype [core-mechanic] 以测试核心循环
5. [如果全新开始] 运行 /brainstorm 以发现您的游戏概念
6. 创建您的第一个里程碑：/sprint-plan new
```

---

## 判定

**完成** — 引擎已配置并且参考文档已填充。

## 护栏

- 永远不要猜测引擎版本 — 始终通过 WebSearch 或用户确认进行验证
- 永远不要在没有询问的情况下覆盖现有参考文档 — 附加或更新
- 如果参考文档已存在于不同的引擎，请在替换之前询问
- 在进行 CLAUDE.md 编辑之前，始终向用户显示您将要更改的内容
- 如果 WebSearch 返回模棱两可的结果，向用户显示并让他们决定
- 当用户选择 **GDScript** 时：完全从附录 A1 复制 GDScript CLAUDE.md 模板。永远不要将"C++ via GDExtension"添加到语言字段。GDScript 项目可以使用 GDExtension，但它不是主要项目语言。需要时，路由表中的 `godot-gdextension-specialist` 可用 — 它不会使 C++ 成为项目语言。

---

## 附录 A — Godot 语言配置

依赖于语言的配置的所有 Godot 特定变体。从第 4 和第 5 节引用 — 仅当 Godot 是所选引擎时才相关。使用与第 4 节中选择的语言匹配的子部分。

---

### A1. CLAUDE.md 技术栈模板

**GDScript：**
```markdown
- **引擎**：Godot [version]
- **语言**：GDScript
- **构建系统**：SCons（引擎）、Godot Export Templates
- **资产管线**：Godot Import System + custom resource pipeline
```

> **护栏**：使用此 GDScript 模板时，将语言字段完全写为 "`GDScript`" — 无附加。不要附加"C++ via GDExtension"或任何其他语言。下面的 C# 模板包括 GDExtension，因为 C# 项目通常包装原生代码；GDScript 项目不包装。

**C#：**
```markdown
- **引擎**：Godot [version]
- **语言**：C#（.NET 8+，主要）、C++ via GDExtension（仅原生插件）
- **构建系统**：.NET SDK + Godot Export Templates
- **资产管线**：Godot Import System + custom resource pipeline
```

**两者 — GDScript + C#：**
```markdown
- **引擎**：Godot [version]
- **语言**：GDScript（游戏玩法/UI 脚本）、C#（性能关键系统）、C++ via GDExtension（仅原生）
- **构建系统**：.NET SDK + Godot Export Templates
- **资产管线**：Godot Import System + custom resource pipeline
```

---

### A2. 命名约定

**GDScript：**
- 类：PascalCase（例如 `PlayerController`）
- 变量/函数：snake_case（例如 `move_speed`）
- 信号：snake_case 过去时（例如 `health_changed`）
- 文件：snake_case 匹配类（例如 `player_controller.gd`）
- 场景：PascalCase 匹配根节点（例如 `PlayerController.tscn`）
- 常量：UPPER_SNAKE_CASE（例如 `MAX_HEALTH`）

**C#：**
- 类：PascalCase（`PlayerController`）— 也必须为 `partial`
- 公共属性/字段：PascalCase（`MoveSpeed`、`JumpVelocity`）
- 私有字段：`_camelCase`（`_currentHealth`、`_isGrounded`）
- 方法：PascalCase（`TakeDamage()`、`GetCurrentHealth()`）
- 信号委托：PascalCase + `EventHandler` 后缀（`HealthChangedEventHandler`）
- 文件：PascalCase 匹配类（`PlayerController.cs`）
- 场景：PascalCase 匹配根节点（`PlayerController.tscn`）
- 常量：PascalCase（`MaxHealth`、`DefaultMoveSpeed`）

**两者 — GDScript + C#：**
对 `.gd` 文件使用 GDScript 约定，对 `.cs` 文件使用 C# 约定。混合语言文件不存在 — 边界是每文件。当不确定新系统应使用哪种语言时，询问用户并在 `technical-preferences.md` 中记录决策。

---

### A3. 引擎专家路由

**GDScript：**
```markdown
## 引擎专家
- **主要**：godot-specialist
- **语言/代码专家**：godot-gdscript-specialist（所有 .gd 文件）
- **着色器专家**：godot-shader-specialist（.gdshader 文件、VisualShader 资源）
- **UI 专家**：godot-specialist（无专用 UI 专家 — 主要覆盖所有 UI）
- **附加专家**：godot-gdextension-specialist（GDExtension / 原生 C++ 绑定，仅当涉及原生扩展时）
- **路由注释**：为主要架构决策、ADR 验证和跨领域代码审查生成主要。为代码质量、信号架构、静态类型强制和 GDScript 惯用语生成 GDScript 专家。为材质设计和着色器代码生成着色器专家。仅当涉及原生扩展时才生成 GDExtension 专家。
```

**文件扩展路由：**

| 文件扩展名/类型 | 要生成的专家 |
|--------------|------------|
| 游戏代码（.gd 文件） | godot-gdscript-specialist |
| 着色器/材质文件（.gdshader、VisualShader） | godot-shader-specialist |
| UI/屏幕文件（Control 节点、CanvasLayer） | godot-specialist |
| 场景/预制体/关卡文件（.tscn、.tres） | godot-specialist |
| 原生扩展/插件文件（.gdextension、C++） | godot-gdextension-specialist |
| 常规架构审查 | godot-specialist |

**C#：**
```markdown
## 引擎专家
- **主要**：godot-specialist
- **语言/代码专家**：godot-csharp-specialist（所有 .cs 文件）
- **着色器专家**：godot-shader-specialist（.gdshader 文件、VisualShader 资源）
- **UI 专家**：godot-specialist（无专用 UI 专家 — 主要覆盖所有 UI）
- **附加专家**：godot-gdextension-specialist（GDExtension / 原生 C++ 绑定，仅当涉及原生扩展时）
- **路由注释**：为主要架构决策、ADR 验证和跨领域代码审查生成主要。为代码质量、[Signal] 委托模式、[Export] 属性、.csproj 管理和 C# 特定的 Godot 惯用语生成 C# 专家。为材质设计和着色器代码生成着色器专家。仅当涉及原生 C++ 插件时才生成 GDExtension 专家。
```

**文件扩展路由：**

| 文件扩展名/类型 | 要生成的专家 |
|--------------|------------|
| 游戏代码（.cs 文件） | godot-csharp-specialist |
| 着色器/材质文件（.gdshader、VisualShader） | godot-shader-specialist |
| UI/屏幕文件（Control 节点、CanvasLayer） | godot-specialist |
| 场景/预制体/关卡文件（.tscn、.tres） | godot-specialist |
| 项目配置（.csproj、NuGet） | godot-csharp-specialist |
| 原生扩展/插件文件（.gdextension、C++） | godot-gdextension-specialist |
| 常规架构审查 | godot-specialist |

**两者 — GDScript + C#：**
```markdown
## 引擎专家
- **主要**：godot-specialist
- **GDScript 专家**：godot-gdscript-specialist（.gd 文件 — 游戏玩法/UI 脚本）
- **C# 专家**：godot-csharp-specialist（.cs 文件 — 性能关键系统）
- **着色器专家**：godot-shader-specialist（.gdshader 文件、VisualShader 资源）
- **UI 专家**：godot-specialist（无专用 UI 专家 — 主要覆盖所有 UI）
- **附加专家**：godot-gdextension-specialist（GDExtension / 原生 C++ 绑定，仅当涉及原生扩展时）
- **路由注释**：为主要跨语言架构决策以及哪些系统属于哪种语言生成主要。为 .gd 文件生成 GDScript 专家。为 .cs 文件和 .csproj 管理生成 C# 专家。在边界处首选信号而不是直接跨语言方法调用。
```

**文件扩展路由：**

| 文件扩展名/类型 | 要生成的专家 |
|--------------|------------|
| 游戏代码（.gd 文件） | godot-gdscript-specialist |
| 游戏代码（.cs 文件） | godot-csharp-specialist |
| 跨语言边界决策 | godot-specialist |
| 着色器/材质文件（.gdshader、VisualShader） | godot-shader-specialist |
| UI/屏幕文件（Control 节点、CanvasLayer） | godot-specialist |
| 场景/预制体/关卡文件（.tscn、.tres） | godot-specialist |
| 项目配置（.csproj、NuGet） | godot-csharp-specialist |
| 原生扩展/插件文件（.gdextension、C++） | godot-gdextension-specialist |
| 常规架构审查 | godot-specialist |

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：

- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 修复 whenToUse 格式；删除原始英文提示词；完全中文化；升级版本号；添加附录 A 完整翻译 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
