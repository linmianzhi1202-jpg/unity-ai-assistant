---
name: start
description: 开始 — 引导式入门流程，检测项目阶段
version: 0.2.0
category: game-development
whenToUse: >
  当用户刚接触 Claude Code Game Studios、需要引导式入门流程、检测项目阶段、
  或选择审查模式（full/lean/solo）时，使用此技能。
  这是新用户的入口点，会根据用户的状态引导到正确的工作流。
input:
- 项目根目录路径（默认当前工作区）
- 用户当前状态（无想法/模糊想法/清晰概念/已有工作）
output:
- 引导式工作流路径推荐
- 审查模式配置（production/review-mode.txt）
- 项目状态检测报告
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
context: inline
---

# 开始技能

## 技能概述

引导式入门流程，检测项目阶段。此技能是引导式入门流程的起点。
它写入一个文件：`production/review-mode.txt`（在阶段 3b 中设置的审查模式配置）。

此技能是新用户的入口点。它不假设您有游戏想法、引擎偏好或任何先前经验。它首先询问，然后引导您到正确的工作流。

## 使用方式

- 通过 Agent 触发：当用户说「开始」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：```/skill start [参数]```

---

## 阶段 1: 检测项目状态

在询问任何内容之前，静默收集上下文，以便您可以根据情况调整指导。不要主动显示这些结果——它们为您的建议提供信息，而不是对话开场白。

检查：
- **引擎已配置？** 读取 `.claude/docs/technical-preferences.md`。如果 Engine 字段包含 `[TO BE CONFIGURED]`，则引擎未设置。
- **游戏概念存在？** 检查 `design/gdd/game-concept.md`。
- **源代码存在？** 在 `src/` 中 Glob 源文件（`*.gd`、`*.cs`、`*.cpp`、`*.h`、`*.rs`、`*.py`、`*.js`、`*.ts`）。
- **原型存在？** 检查 `prototypes/` 中的子目录。
- **设计文档存在？** 计算 `design/gdd/` 中的 Markdown 文件数。
- **生产工件？** 检查 `production/sprints/` 或 `production/milestones/` 中的文件。

在内部存储这些发现以验证用户的自我评估并调整建议。

---

## 阶段 2: 询问用户所在位置

这是用户看到的第一件事。使用带有这些确切选项的 `AskUserQuestion`，以便用户可以点击而不是输入：

- **提示**: "欢迎来到 Claude Code Game Studios！在我建议任何内容之前，我想了解您从哪里开始。您现在对游戏想法处于什么状态？"
- **选项**:
  - `A) 还没有想法` — 我完全没有游戏概念。我想探索并弄清楚要制作什么。
  - `B) 模糊想法` — 我有一个粗略的主题、感觉或类型（例如"与太空有关的东西"或"舒适的农场游戏"），但没有具体内容。
  - `C) 清晰概念` — 我知道核心想法——类型、基本机制，也许还有一个推销句——但还没有将其正式化为文档。
  - `D) 已有工作` — 我已经有设计文档、原型、代码或完成的重要规划。我想组织工作或继续工作。

等待用户的选择。在他们回应之前不要继续。

---

## 阶段 3: 根据答案路由

#### 如果 A：还没有想法

用户在其他任何事情之前需要创意探索：

1. 确认从零开始完全没问题
2. 简要解释 `/brainstorm` 的作用（使用专业框架的引导式构思——MDA、玩家心理学、动词优先设计）。提到它有两种模式：`/brainstorm open` 用于完全开放的探索，或者如果有模糊主题（例如"太空"、"舒适"、"恐怖"），则使用 `/brainstorm [hint]`。
3. 建议将 `/brainstorm open` 作为下一步，但邀请他们如果有任何想法就使用提示
4. 显示推荐路径：
   **概念阶段：**
   - `/brainstorm open` — 发现您的游戏概念
   - `/setup-engine` — 配置引擎（brainstorm 会推荐一个）
   - `/art-bible` — 定义视觉标识（使用视觉标识锚点头脑风暴产生）
   - `/map-systems` — 将概念分解为系统
   - `/design-system` — 为每个 MVP 系统编写 GDD
   - `/review-all-gdds` — 跨系统一致性检查
   - `/gate-check` — 在架构工作之前验证准备情况
   **架构阶段：**
   - `/create-architecture` — 生成主架构蓝图和必需 ADR 列表
   - `/architecture-decision (×N)` — 遵循必需 ADR 列表记录关键技术决策
   - `/create-control-manifest` — 将决策编译成可操作的规则表
   - `/architecture-review` — 验证架构覆盖
   **预生产阶段：**
   - `/ux-design` — 为关键屏幕编写 UX 规范（主菜单、HUD、核心交互）
   - `/prototype` — 构建一次性原型以验证核心机制
   - `/playtest-report (×1+)` — 记录每个垂直切片试玩会话
   - `/create-epics` — 将系统映射到史诗
   - `/create-stories` — 将史诗分解为可实现的用户故事
   - `/sprint-plan` — 计划第一个冲刺
   **生产阶段：** → 使用 `/dev-story` 拾取故事

#### 如果 B：模糊想法

1. 让他们分享模糊的想法——哪怕几个词就足够了
2. 将想法验证为起点（不要判断或重定向）
3. 建议运行 `/brainstorm [their hint]` 来开发它
4. 显示推荐路径：
   **概念阶段：**
   - `/brainstorm [hint]` — 将想法发展为完整概念
   - `/setup-engine` — 配置引擎
   - `/art-bible` — 定义视觉标识（使用视觉标识锚点头脑风暴产生）
   - `/map-systems` — 将概念分解为系统
   - `/design-system` — 为每个 MVP 系统编写 GDD
   - `/review-all-gdds` — 跨系统一致性检查
   - `/gate-check` — 在架构工作之前验证准备情况
   **架构阶段：**
   - `/create-architecture` — 生成主架构蓝图和必需 ADR 列表
   - `/architecture-decision (×N)` — 遵循必需 ADR 列表记录关键技术决策
   - `/create-control-manifest` — 将决策编译成可操作的规则表
   - `/architecture-review` — 验证架构覆盖
   **预生产阶段：**
   - `/ux-design` — 为关键屏幕编写 UX 规范（主菜单、HUD、核心交互）
   - `/prototype` — 构建一次性原型以验证核心机制
   - `/playtest-report (×1+)` — 记录每个垂直切片试玩会话
   - `/create-epics` — 将系统映射到史诗
   - `/create-stories` — 将史诗分解为可实现的用户故事
   - `/sprint-plan` — 计划第一个冲刺
   **生产阶段：** → 使用 `/dev-story` 拾取故事

#### 如果 C：清晰概念

1. 让他们用一句话描述他们的概念——类型和核心机制。使用纯文本，而不是 AskUserQuestion（这是一个开放式响应）。
2. 确认概念，然后使用 `AskUserQuestion` 提供两条路径：
   - **提示**: "您希望如何继续？"
   - **选项**:
     - `首先正式化` — 运行 `/brainstorm [concept]` 将其结构化为适当的游戏概念文档
     - `直接开始` — 现在转到 `/setup-engine` 并之后手动编写 GDD
3. 显示推荐路径：
   **概念阶段：**
   - `/brainstorm` 或 `/setup-engine` —（您在步骤 2 中的选择）
   - `/art-bible` — 定义视觉标识（如果在运行之后，或在概念文档存在之后）
   - `/design-review` — 验证概念文档
   - `/map-systems` — 将概念分解为单独的系统
   - `/design-system` — 为每个 MVP 系统编写 GDD
   - `/review-all-gdds` — 跨系统一致性检查
   - `/gate-check` — 在架构工作之前验证准备情况
   **架构阶段：**
   - `/create-architecture` — 生成主架构蓝图和必需 ADR 列表
   - `/architecture-decision (×N)` — 遵循必需 ADR 列表记录关键技术决策
   - `/create-control-manifest` — 将决策编译成可操作的规则表
   - `/architecture-review` — 验证架构覆盖
   **预生产阶段：**
   - `/ux-design` — 为关键屏幕编写 UX 规范（主菜单、HUD、核心交互）
   - `/prototype` — 构建一次性原型以验证核心机制
   - `/playtest-report (×1+)` — 记录每个垂直切片试玩会话
   - `/create-epics` — 将系统映射到史诗
   - `/create-stories` — 将史诗分解为可实现的用户故事
   - `/sprint-plan` — 计划第一个冲刺
   **生产阶段：** → 使用 `/dev-story` 拾取故事

#### 如果 D：已有工作

1. 分享您在阶段 1 中发现的内容：
   - "我可以看到您有 [X 个源文件 / Y 个设计文档 / Z 个原型]..."
   - "您的引擎 [配置为 X / 尚未配置]..."
2. **子情况 D1 — 早期阶段**（引擎未配置或仅存在游戏概念）：
   - 如果引擎未配置，建议首先 `/setup-engine`
   - 然后 `/project-stage-detect` 进行差距清单
   **子情况 D2 — GDD、ADR 或故事已存在：**
   - 解释："拥有文件不等同于模板的技能能够使用它们。GDD 可能缺少必需的章节。`/adopt` 专门检查这一点。"
   - 建议：
     1. `/project-stage-detect` — 了解什么阶段以及什么完全缺失
     2. `/adopt` — 审核现有工件是否采用正确的内部格式
3. 显示 D2 的推荐路径：
   - `/project-stage-detect` — 阶段检测和存在差距
   - `/adopt` — 格式合规性审计 + 迁移计划
   - `/setup-engine` — 如果引擎未配置
   - `/design-system retrofit [path]` — 填写缺失的 GDD 章节
   - `/architecture-decision retrofit [path]` — 添加缺失的 ADR 章节
   - `/architecture-review` — 引导 TR 需求注册表
   - `/gate-check` — 验证下一阶段的准备情况

---

## 阶段 3b: 设置审查模式

检查 `production/review-mode.txt` 是否已存在。

**如果存在**：读取它并显示当前模式——"审查模式设置为 `[current]`。"——然后继续到阶段 4。不要再询问。

**如果不存在**：使用 `AskUserQuestion`：

- **提示**: "一个设置选择：在您完成工作流时，您希望有多少设计审查？"
- **选项**:
  - `Full` — 主管专家在每个关键工作流步骤进行审查。最适合团队、学习工作流，或当您希望对每个决策进行彻底反馈时。
  - `Lean (推荐)` — 仅在阶段门转换时由主管审查（/gate-check）。跳过每技能审查。适合独立开发者和小型团队的平衡方法。
  - `Solo` — 完全没有主管审查。最大速度。最适合游戏果酱、原型，或当审查感觉像开销时。

在用户选择后立即将选择写入 `production/review-mode.txt`——不需要单独的"我可以写入吗？"，因为写入是选择的直接结果：
- `Full` → 写入 `full`
- `Lean (推荐)` → 写入 `lean`
- `Solo` → 写入 `solo`

如果 `production/` 目录不存在，创建它。

---

## 阶段 4: 在继续之前确认

在展示推荐路径后，使用 `AskUserQuestion` 询问用户他们希望首先采取哪个步骤。永远不要自动运行下一个技能。

- **提示**: "您想从 [推荐的第一步] 开始吗？"
- **选项**:
  - `是的，让我们从 [推荐的第一步] 开始`
  - `我想先做一些其他事情`

---

## 阶段 5: 交接

当用户确认他们的下一步时，用一行简短的话回应："输入 `[skill command]` 开始。"没别的。不要重新解释技能或添加鼓励。`/start` 技能的工作已完成。

判定：**完成**——用户已定位并交接给下一步。

---

## 边缘情况

- **用户选择 D 但项目为空**：温和重定向——"看起来项目是一个新鲜模板，还没有任何工件。路径 A 或 B 会更合适吗？"
- **用户选择 A 但有代码**：提到您发现的——"我注意到 `src/` 中已经有代码。您是打算选择 D（已有工作）吗？"
- **用户正在返回（引擎已配置，概念存在）**：完全跳过入门——"看起来您已经设置好了！您的引擎是 [X]，您在 `design/gdd/game-concept.md` 有游戏概念。审查模式：`[从 production/review-mode.txt 读取，如果缺失则为 'lean (默认)']`。想从您离开的地方继续吗？尝试 `/sprint-plan` 或直接告诉我您想做什么。"
- **用户不适合任何选项**：让他们用自己的话描述他们的情况并适应。

---

## 协作协议

1. **首先询问**——永远不要假设用户的状态或意图
2. **展示选项**——给出清晰的路径，而不是强制命令
3. **用户决定**——他们选择方向
4. **无自动执行**——推荐下一个技能，不要在没有询问的情况下运行它
5. **适应**——如果用户的情况不适合模板，倾听并调整

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
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
