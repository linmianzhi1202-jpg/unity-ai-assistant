---
name: design-system
description: 设计系统 — 按章节引导 GDD 编写，设计游戏系统
version: 0.3.0
category: game-development
whenToUse: >
  当需要通过设计系统技能创建 GDD（游戏设计文档）时使用。
  处理按章节引导 GDD 编写、设计游戏系统相关任务时。
  支持参数：无参数（交互模式）、[system-name]（直接设计指定系统）、retrofit [path]（补充已有 GDD 的缺失章节）。
input:
  - 项目根目录路径（默认当前工作区）
  - 系统名称或 retrofit 路径
output:
  - 结构化 GDD 文档（Markdown 格式）
  - 自动保存到 design/gdd/[system-name].md
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 设计系统技能

## 技能概述

按章节引导 GDD（游戏设计文档）的编写，通过交互式问答逐步设计游戏系统。

**核心原则**：
- **交互式**：每个章节都通过询问用户获取决策
- **增量写入**：每个章节批准后立即写入文件（会话崩溃可恢复）
- **上下文感知**：从游戏概念、系统索引、依赖 GDD 中收集所有相关信息
- **专家路由**：复杂章节委托给专家代理（systems-designer、creative-director 等）

**与 `/create-architecture` 的区别**：
- `/create-architecture` 创建整个系统的主架构蓝图
- `/design-system` 为单个系统编写详细的 GDD

---

## 使用方式

- 通过 Agent 触发：当用户说「设计系统 [系统名]」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill design-system [参数]`

**参数模式**：
- **无参数**：自动检测下一个应设计的系统（按设计顺序）
- **`[system-name]`**：直接设计指定系统（如 `/design-system combat`）
- **`retrofit design/gdd/[system].md`**：补充已有 GDD 中缺失的章节

**审查模式解析**（一次性解析，存储用于所有网关生成）：
1. 如果传递了 `--review [full|lean|solo]` → 使用那个值
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认 `lean`

参阅 `.claude/docs/director-gates.md` 了解完整检查模式。

---

## 阶段 0：解析参数并验证

**系统名称是必需的**。如果缺失：

1. 检查 `design/gdd/systems-index.md` 是否存在。
2. 如果存在：读取它，找到状态为"Not Started"的最高优先级系统，并使用询问用户问题：
   - 提示："您的设计顺序中的下一个系统是 **[system-name]** ([priority] | [layer])。开始设计它吗？"
   - 选项：`[A] 是 — 设计 [system-name]` / `[B] 选择不同的系统` / `[C] 停止`
   - 如果 [A]：继续使用该系统名称。如果 [B]：询问要设计哪个系统（纯文本）。如果 [C]：退出。
3. 如果没有系统索引，失败并显示：
   > "用法：`/design-system <system-name>` — 例如：`/design-system movement`"
   > "或对现有 GDD 中的空白进行填充：`/design-system retrofit design/gdd/[system-name].md`"
   > "未找到系统索引。首先运行 `/map-systems` 来映射您的系统并获取设计顺序。"

**检测 retrofit 模式**：
如果参数以 `retrofit` 开头或参数是 `design/gdd/` 中现有 `.md` 文件的文件路径，进入 **retrofit 模式**：

1. 读取现有 GDD 文件。
2. 识别 8 个必需章节中的哪些存在（扫描章节标题）。
   必需章节：Overview、Player Fantasy、Detailed Design/Rules、Formulas、Edge Cases、Dependencies、Tuning Knobs、Acceptance Criteria。
3. 识别哪些章节仅包含占位符文本（`[To be designed]` 或等效内容 — 空白、单行或明显不完整）。
4. 在继续之前向用户展示：
   ```
   ## Retrofit: [System Name]
   文件：design/gdd/[filename].md
   
   已编写的章节（不会被触碰）：
    ✓ [section name]
    ✓ [section name]
   
   缺失或不完整的章节（将被编写）：
    ✗ [section name] — 缺失
    ✗ [section name] — 仅占位符
   ```
5. 询问："我应该填写 [N] 个缺失的章节吗？我将不会修改任何现有内容。"
6. 如果"是"：像正常一样继续 **阶段 2（收集上下文）**，但在 **阶段 3** 中跳过创建骨架（文件已存在），在 **阶段 4** 中跳过已完整的章节。仅对缺失/不完整章节运行章节循环。
7. **永远不要覆盖现有章节内容。** 使用 Edit 工具仅替换 `[To be designed]` 占位符或空章节正文。

如果**不在** retrofit 模式中，将系统名称规范化为 kebab-case 作为文件名（例如，"combat system" 变为 `combat-system`）。

---

## 阶段 1：收集上下文（读取阶段）

**在询问用户任何内容之前**，按此顺序读取完整项目上下文：

### 1a：必需读取

- **游戏概念**：读取 `design/gdd/game-concept.md` — 如果缺失则失败：
  > "未找到游戏概念。首先运行 `/brainstorm`。"
- **系统索引**：读取 `design/gdd/systems-index.md` — 如果缺失则失败：
  > "未找到系统索引。首先运行 `/map-systems` 来映射您的系统。"
- **目标系统**：在索引中找到该系统。如果未列出，警告：
  > "[system-name] 不在系统索引中。您想要添加它，还是将其作为非索引系统设计？"
- **实体注册表**：读取 `design/registry/entities.yaml`（如果存在）。
  提取此系统引用或相关的所有条目（grep `referenced_by.*[system-name]` 和 `source.*[system-name]`）。将这些保留在上下文中作为 **已知事实** — 其他 GDD 已经建立且此 GDD 不得矛盾的值。
- **反射日志**：读取 `docs/consistency-failures.md`（如果存在）。
  提取其 Domain 匹配此系统类别的条目。这些是
  反复出现的冲突模式 — 在阶段 1d 上下文摘要中将其展示为"Past failure patterns"，以便用户知道此域中以前在哪里出现过错误。

### 1b：依赖项读取

从系统索引中，识别：

- **上游依赖项**：此系统依赖的系统。读取它们的 GDD（如果存在）（这些包含此系统必须尊重的决策）。
- **下游依赖项**：依赖此系统的系统。读取它们的 GDD（如果存在）（这些包含此系统必须满足的期望）。

对于每个存在的依赖项 GDD，提取并保留在上下文中：
- 关键接口（哪些数据在系统之间流动）
- 引用此系统输出的公式
- 假定此系统行为的边缘情况
- 馈入此系统的调优旋钮

### 1c：可选读取

- **游戏支柱**：读取 `design/gdd/game-pillars.md`（如果存在）
- **现有 GDD**：读取 `design/gdd/[system-name].md`（如果存在）（恢复，不要从头开始）
- **相关 GDD**：搜索 `design/gdd/*.md` 并读取主题相关的任何内容
   （例如，如果设计的系统与另一个在范围上重叠，请读取相关 GDD，即使它不是正式依赖项）

### 1d：展示上下文摘要

在开始设计工作之前，向用户展示简要摘要：

> **正在设计：[System Name]**
> - 优先级：[来自索引] | 层：[来自索引]
> - 依赖于：[列表，注意哪些有 GDD vs. 未设计]
> - 被依赖：[列表，注意哪些有 GDD vs. 未设计]
> - 要尊重的现有决策：[来自依赖项 GDD 的关键约束]
> - 支柱对齐：[此系统主要服务的哪个（些）支柱]
> - **已知跨系统事实（来自注册表）**：
>   - [entity_name]：[attribute]=[value], [attribute]=[value]（由 [source GDD] 拥有）
>   - [item_name]：[attribute]=[value], [attribute]=[value]（由 [source GDD] 拥有）
>   - [formula_name]：variables=[list], output=[min–max]（由 [source GDD] 拥有）
>   - [constant_name]：[value] [unit]（由 [source GDD] 拥有）
> *（这些值是锁定的 — 如果此 GDD 需要不同的值，请在写入之前暴露冲突。不要静默使用不同数字。）*
>
> 如果没有相关注册表条目：省略"已知跨系统事实"部分。

如果任何上游依赖项未设计，警告：

> "[dependency] 还没有 GDD。我们需要对它的接口做出假设。考虑首先设计它，或者我们可以在定义预期契约后将其标记为临时。"

### 1e：技术可行性预检查

在开始设计之前，加载引擎上下文并暴露任何将塑造设计的约束或知识差距。

**步骤 1 — 确定此系统的引擎域：**

将系统的类别（来自 systems-index.md）映射到引擎域：

| 系统类别 | 引擎域 |
|--------------|--------------|
| 战斗、物理、碰撞 | Physics |
| 渲染、视觉特效、着色器 | Rendering |
| UI、HUD、菜单 | UI |
| 音频、声音、音乐 | Audio |
| AI、路径查找、行为树 | Navigation / Scripting |
| 动画、IK、绑定 | Animation |
| 网络、多人游戏、同步 | Networking |
| 输入、控制、键绑定 | Input |
| 保存/加载、持久化、数据 | Core |
| 对话、任务、叙事 | Scripting |

**步骤 2 — 读取引擎上下文（如果可用）：**
- 读取 `.claude/docs/technical-preferences.md`：
  - `Engine:` 值 — 确定要使用的程序员代理
  - 命名约定（类名、文件名、信号/事件名）
  - 性能预算（帧预算、内存上限）
  - 禁止模式

**步骤 3 — 展示可行性简要说明：**

如果引擎参考文档存在，在开始设计之前展示：

```
## 技术可行性简要说明：[System Name]
引擎：[名称 + 版本]
域：[域]

### 已知引擎功能（为 [版本] 验证）
- [与此系统相关的功能]
- [功能 2]

### 将塑造此设计的引擎约束
- [来自引擎参考或现有 ADR 的约束]

### 知识差距（在提交这些之前验证）
- [此设计可能依赖的截止后功能 — 标记 HIGH/MEDIUM 风险]

### 约束此系统的现有 ADR
- ADR-XXXX：[决策摘要] — 意味着 [对此 GDD 的影响]
 （或"还不存在"）
```

如果引擎参考文档**不**存在（引擎尚未配置），显示简短注释：

> "引擎尚未配置 — 跳过技术可行性检查。如果您还没有，请在移动到架构之前运行 `/setup-engine`。"

**步骤 4 — 在继续之前询问：**

使用询问用户问题：
- "在继续之前，是否有要添加的约束，还是我们应该使用这些注释的继续？"
  - 选项："继续使用这些注释"，"首先添加约束"，"我需要检查引擎文档 — 在此暂停"

---

## 阶段 2：创建文件骨架

用户确认后，**立即**使用空章节标题创建 GDD 文件。这确保增量写入有目标。

使用 `.claude/docs/templates/game-design-document.md` 的模板结构：

```markdown
# [System Name]

> **Status**: In Design
> **Author**: [user + agents]
> **Last Updated**: [today's date]
> **Implements Pillar**: [from context]

## Overview

[To be designed]

## Player Fantasy

[To be designed]

## Detailed Design

### Core Rules

[To be designed]

### States and Transitions

[To be designed]

### Interactions with Other Systems

[To be designed]

## Formulas

[To be designed]

## Edge Cases

[To be designed]

## Dependencies

[To be designed]

## Tuning Knobs

[To be designed]

## Visual/Audio Requirements

[To be designed]

## UI Requirements

[To be designed]

## Acceptance Criteria

[To be designed]

## Open Questions

[To be designed]
```

询问："我可以将骨架文件创建到 `design/gdd/[system-name].md` 吗？"

写入后，更新 `production/session-state/active.md`：

- 使用 搜索文件 检查文件是否存在。
- 如果**不**存在：使用 write_to_file 工具创建它。永远不要尝试在可能不存在的文件上进行 replace_in_file。
- 如果它**已经**存在：使用 replace_in_file 工具更新相关字段。

文件内容：
- 任务：设计 [system-name] GDD
- 当前章节：已启动（骨架已创建）
- 文件：design/gdd/[system-name].md
- 章节：全部 8 个已创建（占位符）
- 下一步：（在骨架写入后立即启动阶段 4）

---

## 阶段 3：逐章节设计

按顺序遍历每个章节。对于每个章节，遵循此循环：

### 章节循环

```
上下文  ->  问题  ->  选项  ->  决策  ->  草稿  ->  批准  ->  写入
```

1. **上下文**：陈述此章节需要包含的内容，并暴露约束此章节的任何依赖项 GDD 的决策。
2. **问题**：询问此章节特定的澄清问题。对受约束的问题使用询问用户，对开放式探索使用对话文本。
3. **选项**：如果章节涉及设计选择（不仅仅是文档），展示 2-4 个方法，附带利弊。在对话文本中解释推理，然后使用询问用户捕获决策。
4. **决策**：用户选择一个方法或提供自定义方向。
5. **草稿**：在对话文本中为审查编写章节内容。标记对未设计依赖项的任何临时假设。
6. **批准**：在草稿之后 — 在同一**响应中 — 使用询问用户。**永远不要使用纯文本。**永远不要跳过此步骤。**
   - 提示："批准 [Chapter Name] 章节吗？"
   - 选项：`[A] 批准 — 写入文件` / `[B] 进行更改 — 描述要修复的内容` / `[C] 重新开始`
   **草稿和小部件必须在一个响应中一起出现。如果草稿在没有小部件的情况下出现，用户会留在空白提示符处，没有前进路径 — 这是协议违反。**
7. **写入**：使用 replace_in_file 工具将批准的内容替换占位符。
   **关键**：始终在 `old_string` 中包含章节标题以确保唯一性 — 永远不要仅匹配 `[To be designed]`，因为多个章节使用相同的占位符，并且 replace_in_file 工具需要唯一匹配。使用此模式：
   ```
   old_str: "## [Section Name]\n\n[To be designed]"
   new_str: "## [Section Name]\n\n[approved content]"
   ```
   确认写入。

8. **注册表冲突检查**（仅章节 C 和 D — Detailed Design 和 Formulas）：
   写入后，扫描章节内容中以实体名称、项目名称、公式名称和数字常量出现在注册表中的内容。对于每个匹配：
   - 将刚写入的值与注册表条目进行比较。
   - 如果它们不同：**立即**暴露冲突，在启动下一个
     章节之前。不要静默继续。
      > "注册表冲突：[name] 在 [source GDD] 中注册为 [registry_value]。
      > 此章节刚刚写入了 [new_value]。哪个是正确的？"
   - 如果是新的（不在注册表中）：将其标记为注册表注册的候选者
     （将在阶段 5 中处理）。

写入每个章节后，更新 `production/session-state/active.md` 和已完成的章节名称。使用 搜索文件 检查文件是否存在 — 如果缺失则使用 write_to_file 创建，如果存在则使用 replace_in_file 更新。

### 章节特定指导：

每个章节都有独特的设计考虑，可能受益于专家代理：

---

### 章节 A：概述

**目标**：陌生人可以阅读和理解的一段。

**在构建小部件之前推导推荐选项**：读取系统的类别和层（来自阶段 2 的上下文），然后确定每个小部件的推荐选项：
- **框架选项卡**：Foundation/Infrastructure 层 → `[A]` 推荐。面向玩家的类别（Combat、UI、Dialogue、Character、Animation、Visual Effects、Audio） → `[C] Both` 推荐。
- **ADR 引用选项卡**：搜索文件 `docs/architecture/adr-*.md` 并 grep 任何 ADR 中的系统名称。如果找到匹配的 ADR → `[A] 是 — 引用 ADR` 推荐。如果未找到 → `[B] 否` 推荐。
- **幻想选项卡**：Foundation/Infrastructure 层 → `[B] 否` 推荐。所有其他类别 → `[A] 是` 推荐。

将 `(Recommended)` 附加到小部件中的适当选项文本。

**框架问题（在起草**之前询问）**：使用带有多选项卡小部件的询问用户：
- 选项卡"框架" — "概述应该如何框定此系统？" 选项：`[A] 作为数据/基础设施层（技术框架）` / `[B] 通过其面向玩家的影响（设计框架）` / `[C] 两者 — 描述数据层和它的玩家影响`
- 选项卡"ADR 引用" — "概述应该引用此系统的现有 ADR 吗？" 选项：`[A] 是 — 引用 ADR 以获取实现详细信息` / `[B] 否 — 将 GDD 保持在纯设计级别`
- 选项卡"幻想" — "此系统是否有值得陈述的玩家幻想？" 选项：`[A] 是 — 玩家直接感受到它` / `[B] 否 — 纯基础设施，玩家感受到它启用`

使用用户的答案适当地塑造草稿。不要自己回答这些问题并自动起草。

**要询问的问题**：
- 这个系统用一句话来说是什么？
- 玩家如何与它交互？（主动/被动/自动）
- 为什么此系统存在 — 如果没有它，游戏会失去什么？

**交叉引用**：检查描述是否与系统索引号它的方式一致。标记差异。

**设计与实现边界**：概述问题必须保持在行为级别 — 系统 *做什么*，而不是 *如何构建*。如果在概述期间出现实现问题（例如，"应该使用 Autoload 单例还是信号总线？"），将它们标记为"→ 成为 ADR"并继续。实现模式属于 `/architecture-decision`，而不是 GDD。GDD 描述行为；ADR 描述用于实现它的技术方法。

---

### 章节 B：玩家幻想

**目标**：情感目标 — 玩家应该 *感受到*什么。

**在构建小部件之前推导推荐选项**：读取阶段 2 上下文中的系统类别和层：
- 面向玩家的类别（Combat、UI、Dialogue、Character、Animation、Audio、Level/World） → `[A] Direct` 推荐
- Foundation/Infrastructure 层 → `[B] Indirect` 推荐
- 混合类别（Camera/input、Economy、带可见玩家影响的 AI） → `[C] Both` 推荐

将 `(Recommended)` 附加到适当的选项文本。

**框架问题（在起草**之前询问）**：使用询问用户：
- 提示："此系统是玩家直接参与的，还是他们间接体验的基础设施？"
  - 选项：`[A] 直接 — 玩家主动使用或感受到此系统` / `[B] 间接 — 玩家体验效果，而不是系统` / `[C] 两者 — 具有直接交互层和其下方的基础设施`

使用答案适当地框定玩家幻想章节。不要假设答案。

**要询问的问题**：
- 它服务于什么情感或力量幻想？
- 哪些参考游戏实现了这种感觉？具体是什么创造了它？
- 这是"您喜欢参与的系统"还是"您不注意的基础设施"？

**交叉引用**：必须与游戏支柱一致。如果系统服务于一个支柱，引用相关的支柱文本。

**代理委托（必需）**：在给出框架答案之后但在起草之前，生成 `creative-director`  via Task：
- 提供：系统名称、框架答案（直接/间接/两者）、游戏支柱、用户提到的任何参考游戏、游戏概念摘要
- 询问："塑造此系统的玩家幻想。它应该服务于什么情感或力量幻想？我们应该锚定什么玩家时刻？我们应该使用什么语气和语言来适应游戏已建立的感觉？要具体 — 给我 2-3 个候选框架。"

收集 creative-director 的框架，并将它们与草稿一起展示给用户。

**在咨询 `creative-director` 之前，不要起草章节 B。** 框架答案告诉我们它是*什么*类型的幻想；creative-director 塑造 *它如何被描述* — 语气、语言、要锚定的特定玩家时刻。

---

### 章节 C：详细设计（核心规则、状态、交互）

**目标**：程序员可以在没有问题的情况下实现的明确规范。

这通常是最长的章节。将其分解为子章节：

1. **核心规则**：基本机制。对顺序过程使用编号规则，对属性使用项目符号。
2. **状态和转换**：如果系统有状态，映射每个状态和每个有效转换。使用表格。
3. **与其他系统的交互**：对于每个依赖项（上游和下游），指定什么数据流入、什么流出，以及谁拥有接口。

**要询问的问题**：
- 带我逐步了解此系统的典型用法
- 玩家面临什么决策点？
- 玩家不能做什么？（约束与能力一样重要）

**代理委托（必需）**：在起草章节 C 之前，并行生成专家代理 via Task：
- 在路由表（此技能的阶段 6）中查找系统类别
- 生成此类别列出的主要代理 **和**支持代理
- 向每个代理提供：系统名称、游戏概念摘要、支柱集、依赖项 GDD 摘录、正在处理的特定章节
- 在起草之前收集他们的发现
- 通过询问用户暴露代理之间的任何分歧
- 仅在收到专家输入后起草

**在首先咨询适当的专家之前，不要起草章节 C。** 审查规则和机制的 `systems-designer` 将捕获主会话无法发现的 design gaps。**

**交叉引用**：对于列出的每个交互，验证它与依赖项 GDD 指定的内容一致。如果一个依赖项定义了此系统期望不同的值或公式，标记冲突。

---

### 章节 D：公式

**目标**：每个数学公式，都定义了变量、指定了范围并注释了边缘情况。

**完成引导 — 始终使用此确切结构开始每个公式：**

```
[formula_name] 公式定义为：

`[formula_name] = [expression]`

**变量：**

| 变量 | 符号 | 类型 | 范围 | 描述 |
|----------|--------|------|-------|-------------|
| [name] | [sym] | float/int | [min–max] | [它代表什么] |

**输出范围：**[min] 到 [max]（正常游戏期间）；[极端情况下的行为]

**示例：**[带实际数字的工作示例]
```

**不要**写 `[Formula TBD]` 或用散文描述公式而不使用变量表。没有定义变量的公式在没有猜测工作的情况下无法实现。

**要询问的问题**：
- 此系统执行的核心计算是什么？
- 缩放应该是线性、对数还是阶梯式的？
- 在游戏早期/中期/后期，输出范围应该是什么？

**代理委托（必需）**：在提出任何公式或平衡值之前，并行生成专家代理 via Task：
- **始终生成 `systems-designer`**：提供章节 C 中的核心规则、来自用户的调优目标、来自依赖项 GDD 的平衡上下文。要求他们提出带有变量表和输出范围的公式。
- **对于经济/成本系统，还要生成 `economy-designer`**：提供放置成本、升级成本意图和进度目标。要求他们验证成本曲线和比率。
- 通过询问用户将专家的建议呈现给用户进行审查：
- 用户决定；主会话写入文件
- **在没有专家输入的情况下，不要发明公式值或平衡数字。** 没有平衡设计专业知识的用户无法评估原始数字 — 他们需要专家的推理。**

**交叉引用**：如果一个依赖项 GDD 定义了输出馈入此系统的公式，请显式引用它。不要重新发明 — 连接。

---

### 章节 E：边缘情况

**目标**：显式处理异常情况，以便它们不会成为 bug。

**完成引导 — 将每个边缘情况格式化为：**

- **如果 [condition]**：[exact outcome]. [如果非明显，则提供基本原理]

示例（使术语适应游戏的域）：
- **如果 [resource] 在 [protective condition] 处于活动状态时达到 0**：在条件结束之前保持最小值，然后应用后果。
- **如果两个 [triggers/events] 同时触发**：以 [defined priority order] 解决；平局使用 [defined tiebreak rule]。

**不要**写模糊条目如"handle appropriately" — 每个必须命名确切条件和确切解决方案。没有解决方案的边缘情况是一个开放的设计问题，而不是规范。

**要询问的问题**：
- 在零时会发生什么？在最大值时？在超出范围的值时？
- 当两个规则同时应用时会发生什么？
- 如果玩家发现意外的交互会发生什么？（识别退化策略）

**代理委托（必需）**：在最终确定边缘情况之前，生成 `systems-designer` via Task。提供：已完成的章节 C 和 D，并要求他们识别主会话可能遗漏的来自公式和规则空间的边缘情况。对于叙事系统，还要生成 `narrative-director`。将他们的发现呈现给用户，并询问要包括哪些。

**交叉引用**：对照依赖项 GDD 检查边缘情况。如果一个依赖项定义了此系统可能违反的下限、上限或解决方案规则，标记它。

---

### 章节 F：依赖项

**目标**：映射每个系统连接以及方向和性质。

此章节部分由上下文收集阶段预填充。向用户展示已知的依赖项并询问：
- 我是否遗漏了什么依赖项？
- 对于每个依赖项，具体的接口是什么？
- 哪些依赖项是硬性的（系统在没有它的情况下无法运行）vs. 软性的（通过它增强但单独工作）？

**交叉引用**：此章节必须是双向一致的。如果此系统列出"依赖于战斗"，那么战斗 GDD 应该列出"被 [此系统] 依赖"。标记任何单向依赖项以进行更正。

---

### 章节 G：调优旋钮

**目标**：每个设计者可以在不进行代码更改的情况下调整的值，具有安全范围和极端行为。

**要询问的问题**：
- 设计者应该能够调整哪些值而无需更改代码？
- 对于每个旋钮，如果设置得太高会破坏什么？太低？
- 哪些旋钮相互影响？（更改 A 使 B 无关）

**代理委托**：如果公式复杂，委托给 `systems-designer` 从公式变量中推导调优旋钮。

**交叉引用**：如果依赖项 GDD 列出影响此系统的调优旋钮，请在此处引用它们。不要创建重复的旋钮 — 指向真相来源。

---

### 章节 H：验收标准

**目标**：可测试的条件，证明系统按设计工作。

**完成引导 — 将每个标准格式化为 Given-When-Then：**

- **GIVEN** [initial state], **WHEN** [action or trigger], **THEN** [measurable outcome]

示例（使术语适应游戏的域）：
- **GIVEN** [initial state], **WHEN** [player action or system trigger], **THEN** [specific measurable outcome].
- **GIVEN** [a constraint is active], **WHEN** [player attempts an action], **THEN** [feedback shown and action result].

至少包括：来自章节 C 的每个核心规则的一个标准，以及来自章节 D 的每个公式的一个标准。**不要**写"系统按设计工作" — 每个标准必须可由 QA 测试人员在无需读取 GDD 的情况下独立验证。

**代理委托（必需）**：在最终确定验收标准之前，生成 `qa-lead` via Task。提供：已完成的 GDD 章节 C、D、E，并要求他们验证这些标准是否可独立测试并涵盖所有核心规则和公式。将任何差距或不可测试的标准暴露给用户。

**要询问的问题**：
- 证明此工作所需的最小测试集是什么？
- 此系统获得什么性能预算？（帧时间、内存）
- QA 测试人员首先会检查什么？

**交叉引用**：包括验证跨系统交互工作的标准，而不仅仅是此系统的隔离。

---

### 可选章节：Visual/Audio、UI Requirements、Open Questions

这些章节包含在模板中。Visual/Audio 对于 visual system categories 是 **REQUIRED**（不可选）。在跳到这些之前确定要求级别：

**如果系统类别需要 Visual/Audio**，则 Visual/Audio 是必需的（不可选）：
- Combat、damage、health
- UI systems (HUD、menus)
- Animation、character movement
- Visual effects、particles、shaders
- Character systems
- Dialogue、quests、lore
- Level/world systems

对于必需的系统：**在起草此章节之前，生成 `art-director` via Task**。提供：系统名称、游戏概念、游戏支柱、如果它们存在，则提供 art bible 章节 1–4。要求他们指定：(1) 此系统事件的 VFX 和视觉反馈要求，(2) 任何动画或视觉风格约束，(3) 哪些 art bible 原则最直接适用于此系统。呈现他们的输出；**不要**将此外章节保留为 `[To be designed]` 对于 visual systems。

对于 **所有其他系统类别**（Foundation/Infrastructure、Economy、AI/pathfinding、Camera/input)，在必需章节之后提供可选章节：
- 使用询问用户：
  - "8 个必需章节已完成。您是否还想定义 Visual/Audio 要求、UI 要求或捕获开放问题？"
  - 选项："是，全部三个"，"仅开放问题"，"跳过 — 我稍后会添加这些"

对于 **Visual/Audio**（非必需系统）：如果需要，与 `art-director` 和 `audio-director` 协调。通常在 GDD 阶段，简短注释就足够了。

> **Asset Spec 标志**：写入 Visual/Audio 章节并具有真实内容后，输出此通知：
> "📌 **Asset Spec** — 已定义 Visual/Audio 要求。art bible 批准后，运行 `/asset-spec system:[system-name]` 以从此章节生成每个资产的视觉描述、尺寸和生成提示。"

对于 **UI Requirements**：对于复杂的 UI 系统，与 `ux-designer` 协调。
写入此章节后，检查它是否包含真实内容（不仅仅是 [To be designed] 或注释，即此系统没有 UI）。如果它确实有真实的 UI 要求，请立即输出此标志：
> "📌 UX 标志 — [System Name]**：此系统具有 UI 要求。在阶段 4（Pre-Production）中，在编写 epic 之前，运行 `/ux-design` 为此系统贡献的每个屏幕或 HUD 元素创建 UX 规范。"

> 在系统索引中为此系统记下这一点，如果您更新它。

对于 **Open Questions**：捕获在设计期间出现的、未完全解决的任何事情。每个问题应该有一个所有者与目标解决日期。

---

## 阶段 4：后设计验证

所有章节写入后：

### 4a：自检

读取完整的 GDD（从文件，不是来自对话记忆 — 文件是真相来源）。验证：
- 所有 8 个必需章节都有真实内容（不是占位符）
- 公式引用定义的变量
- 边缘情况有解决方案
- 依赖项被列为具有接口
- 验收标准是可测试的

### 4a-bis：Creative Director 支柱审查

**审查模式检查** — 在生成 CD-GDD-ALIGN 之前应用：
- `solo` → 跳过。注意："CD-GDD-ALIGN 跳过 — 单独模式。" 继续阶段 4b。
- `lean` → 跳过（不是 PHASE-GATE）。注意："CD-GDD-ALIGN 跳过 — Lean 模式。" 继续阶段 4b。
- `full` → 正常生成。

在最终确定 GDD 之前，使用网关 **CD-GDD-ALIGN**（`.claude/docs/director-gates.md`）生成 `creative-director` via Task。

传递：完整的 GDD 文件路径、游戏支柱（来自 `design/gdd/game-concept.md` 或 `design/gdd/game-pillars.md`）、MDA aesthetics 目标。

按照 `director-gates.md` 中的标准规则处理裁定。解决后，在 GDD 状态标头中记录裁定：
`> **Creative Director Review (CD-GDD-ALIGN)**: APPROVED [date] / CONCERNS (accepted) [date] / REVISED [date]`

---

### 4b：更新实体注册表

扫描已完成的 GDD，查找应注册的跨系统事实：
- 具有统计或掉落的名命实体（enemies、NPCs、bosses）
- 具有值、权重或类别的命名项目
- 定义了变量和输出范围的命名公式
- 在多个地方通过值引用的命名常量

对于每个候选者，检查它是否已经存在于 `design/registry/entities.yaml` 中：

```
search_content pattern="  - name: [candidate_name]" path="design/registry/entities.yaml"
```

呈现摘要：

```
来自此 GDD 的注册表候选者：

新的（尚未注册）：
  - [entity_name] [entity]：[attribute]=[value], [attribute]=[value]
  - [item_name] [item]：[attribute]=[value], [attribute]=[value]
  - [formula_name] [formula]：variables=[list], output=[min–max]
  已注册（将更新 `referenced_by`）：
  - [constant_name] [constant]：value=[N] ← 匹配注册表 ✅
```

询问："我可以用这些 [N] 个新条目更新 `design/registry/entities.yaml` 并为现有条目更新 `referenced_by` 吗？"

如果是，附加新条目并更新 `referenced_by` 数组。在首先将其暴露为冲突之前，永远不要修改现有的 `value` / attribute 字段。

---

### 4c：提供设计审查

呈现完成摘要：

> **GDD 完成：[System Name]**
> - 已编写的章节：[列表]
> - 临时假设：[列表任何关于未设计依赖项的假设]
> - 发现的跨系统冲突：[列表或 "none"]

> **要验证此 GDD，请打开一个新的 Claude Code 会话并运行：**
> `/design-review design/gdd/[system-name].md`

> **永远不要**在同一会话中运行 `/design-review` 作为 `/design-system`。审查代理必须独立于作者上下文。在此处运行它将继承完整设计历史，使独立评论变得不可能。

**永远不要**内联提供运行 `/design-review`。始终将用户引导到新的窗口。

---

### 4d：更新系统索引

GDD 完成后（以及可选审查后）：

- 读取系统索引
- 更新目标系统的行：
  - 如果设计审查已运行且裁定为 APPROVED：Status → "Approved"
  - 如果设计审查已运行且裁定为 NEEDS REVISION：Status → "In Review"
  - 如果设计审查已跳过：Status → "Designed"（pending review）
  - 如果用户选择了"I'll review it myself first"：Status → "Designed"
  - Design Doc：链接到 `design/gdd/[system-name].md`
- 更新进度跟踪器计数

询问："我可以在 `design/gdd/systems-index.md` 更新系统索引吗？"

---

### 4d：更新会话状态

更新 `production/session-state/active.md` 与：

- 任务：[system-name] GDD
- 状态：Complete（或如果设计审查已运行，则为 In Review）
- 文件：design/gdd/[system-name].md
- 章节：全部 8 个已编写
- 下一步：[从设计顺序建议下一个系统]

---

### 4e：建议后续步骤

使用询问用户：

- "下一步是什么？"
  - 选项：
    - "运行 `/consistency-check` — 验证此 GDD 的值不与现有 GDD 冲突（在移动到下一个系统之前推荐）"
    - "设计下一个系统 ([next-in-order])" — 如果未设计的系统仍然存在"
    - "修复审查发现" — 如果设计审查标记了问题"
    - "在此会话停在此处"
    - "运行 `/gate-check`" — 如果足够多的 MVP 系统已设计"

---

## 阶段 5：恢复和继续

如果会话被中断（压缩、崩溃、新会话）：

1. 读取 `production/session-state/active.md` — 它记录了当前系统和哪些章节已完成
2. 读取 `design/gdd/[system-name].md` — 具有真实内容的章节已完成；带有 `[To be designed]` 的章节仍需要工作
3. 从下一个不完整章节继续 — 无需重新讨论已完成的章节

这就是为什么增量写入很重要：每个批准的章节都可以幸免于任何中断。

---

## 协作协议

此技能在每一步都遵循协作设计原则：

1. **问题 -> 选项 -> 决策 -> 草稿 -> 批准** 对于每个章节
2. **在每个决策点使用 `AskUserQuestion`**（Explain -> Capture 模式）：
   - 阶段 2："准备好开始，还是需要更多上下文？"
   - 阶段 3："我可以创建骨架吗？"
   - 阶段 4（每个章节）：设计问题、方法选项、草稿批准
   - 阶段 5："运行设计审查？更新系统索引？下一步是什么？"
3. **在每个草稿之前询问*"May I write to [file-path]?"***
4. **增量写入**：每个章节在批准后立即写入文件
5. **会话状态更新**：在每个章节写入之后
6. **交叉引用**：每个章节检查现有 GDD 是否冲突
7. **专家路由**：复杂章节获得专家代理输入，呈现给用于决策的**用户** — 永远不要静默写入

**永远不要**阻止用户前进 — 裁定是建议性的。记录风险并让用户决定尽管有顾虑仍继续。

---

## 上下文窗口感知

这是一个长时间运行的技能。在写入每个章节后，检查状态行是否显示上下文处于或超过 70%。如果是这样，在响应的末尾附加此通知：

> **上下文正在接近限制（≥70%）。** 您的进度已保存到 `design/gdd/[system-name].md`。当您准备继续时，打开一个新的 Claude Code 会话并运行 `/design-system [system-name]` — 它将检测哪些章节已完成并从下一个恢复。

---

## 推荐后续步骤

- 在**新的会话**中运行 `/design-review design/gdd/[system-name].md` 以独立验证已完成的 GDD
- 运行 `/consistency-check` 以验证此 GDD 的值不与任何其他 GDD 冲突
- 运行 `/map-systems next` 以移动到下一个最高优先级的未设计系统
- 当所有 MVP GDD 都已编写和审查时，运行 `/gate-check pre-production`

---

## 系统类别到专家代理的路由表

| 系统类别 | 主要代理 | 支持代理 |
|--------------|----------|----------|
| 战斗、物理 | systems-designer | creative-director |
| UI、HUD、菜单 | ux-designer + systems-designer | creative-director、art-director |
| 动画、角色 | systems-designer | art-director、creative-director |
| 对话、任务 | systems-designer | narrative-director、creative-director |
| 经济、进度 | economy-designer + systems-designer | creative-director |
| AI、行为 | systems-designer | creative-director |
| 输入、控制 | systems-designer | ux-designer |
| 渲染、VFX | systems-designer | art-director、audio-director |
| 保存/加载 | systems-designer | technical-director |
| 网络、多人游戏 | systems-designer | technical-director |

---

## Unity 设计模式代码参考索引

在为 Unity 游戏设计系统时，可以参考以下 Template 项目中的设计模式实现：

### 设计模式参考（Unity-Design-Pattern）

| 模式类别 | 模式名称 | 路径 | 含反例 |
|----------|---------|------|--------|
| 行为型 | 策略模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Behavioral Patterns/Strategy Pattern/` | ✅ BadCodeExample.cs |
| 行为型 | 状态模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Behavioral Patterns/State Pattern/` | ✅ 多版本演进 |
| 行为型 | 观察者模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Behavioral Patterns/Observer Pattern/` | — |
| 行为型 | 命令模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Behavioral Patterns/Command Pattern/` | — |
| 创建型 | 单例模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Creational Patterns/Singleton Pattern/` | ✅ 线程安全 vs 非安全 |
| 游戏编程 | 组件模式 | `referrence/Template/Unity-Design-Pattern-master/Assets/Game Programming Patterns/Component Pattern/` | — |
| 游戏编程 | 事件队列 | `referrence/Template/Unity-Design-Pattern-master/Assets/Game Programming Patterns/Event Queue Pattern/` | ✅ 同步 vs 异步 |
| 游戏编程 | 对象池 | `referrence/Template/Unity-Design-Pattern-master/Assets/Game Programming Patterns/Object Pool Pattern/` | — |

### 系统级参考项目

| 系统领域 | 参考项目 | 路径 | .cs 数 | 关键模块 |
|----------|---------|------|--------|----------|
| 游戏框架 | UnityGameFramework | `referrence/Template/UnityGameFramework-master/` | 288 | 事件系统、UI框架、数据组件 |
| 网络框架 | Mirror | `referrence/Template/Mirror-master/` | 924 | NetworkManager、SyncVar、RPC |
| 背包系统 | Inventory-Pro | `referrence/Template/Inventory-Pro-master/` | 298 | 装备系统、物品数据库 |
| 任务系统 | Quest-System-Pro | `referrence/Template/Quest-System-Pro-master/` | 309 | 任务树、条件判断 |
| GAS 能力系统 | unity-gameplay-ability-system | `referrence/Template/unity-gameplay-ability-system-main/` | 42 | Ability、Effect、Tag |
| 层次状态机 | UnityHFSM | `referrence/Template/UnityHFSM-master/` | 64 | HierarchicalStateMachine |

**使用方式**：在阶段 1e 技术可行性预检查和阶段 3 详细设计时，读取对应参考项目的核心 .cs 文件验证设计可行性。

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文
- 使用 `unity-csharp-patterns` Rule 检查 C# 编码正反例
- 使用 `unity-performance` Rule 检查性能正反例

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| **0.3.0** | 2026-04-27 | 修复 whenToUse 格式，清理标题多余：符号，升级版本号 |
| 0.2.0 | 2026-04-27 | 完整翻译为正体中文，删除"原始英文提示词"部分，修复 YAML frontmatter |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
