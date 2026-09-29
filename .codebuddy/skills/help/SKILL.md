---
name: help
description: 帮助 — 显示工作流程目录，提供导航帮助
version: 0.2.0
category: game-development
whenToUse: >
  需要使用帮助技能时，或需要处理"显示工作流程目录，提供导航帮助"相关任务时。
  此技能是只读的 — 它报告发现但不会写入任何文件。
  此技能精确地找出您在游戏开发流程中所处的位置，并告诉您接下来要做什么。
  它是**轻量级**的 — 不是完整的审计。对于完整的差距分析，请使用 `/project-stage-detect`。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标参数（根据技能不同）
output:
  - 结构化结果报告（Markdown 格式）
  - 相关文件生成（根据技能不同）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 帮助技能

## 技能概述

显示工作流程目录，提供导航帮助。此技能是只读的，不会写入任何文件。它会精确找出您在游戏开发流程中所处的位置，并告诉您接下来要做什么。

## 使用方式

- 通过 Agent 触发：当用户说「帮助」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill help [参数]`

---

## Step 1：读取目录

读取 `.claude/docs/workflow-catalog.yaml`。这是所有阶段的权威列表，包含它们的步骤（按顺序排列）、每个步骤是必需的还是可选的，以及指示完成状态的产品文件 glob 模式。

---

## Step 1b：查找不在目录中的技能

读取目录后，使用 Glob 扫描 `.claude/skills/*/SKILL.md` 获取已安装技能的完整列表。对于每个文件，从其 frontmatter 中提取 `name:` 字段。

与目录中的 `command:` 值进行比较。任何名称未作为目录命令出现的技能都是**未编目技能** — 仍然可用，但不属于阶段门控工作流程的一部分。

为 Step 7 中的输出收集这些信息 — 将它们显示为页脚块：

```
### 也已安装（不在工作流程中）
- `/skill-name` — [SKILL.md frontmatter 中的描述]
- `/skill-name` — [描述]
```

仅当至少存在一个未编目技能时才显示此块。根据用户的当前阶段限制为最相关的 10 个（生产阶段的 QA 技能，生产/打磨阶段的团队技能等）。

---

## Step 2：确定当前阶段

按此顺序检查：

1. **读取 `production/stage.txt`** — 如果它存在且有内容，这是权威的阶段名称。将其映射到目录阶段键：
   - "Concept" → `concept`
   - "Systems Design" → `systems-design`
   - "Technical Setup" → `technical-setup`
   - "Pre-Production" → `pre-production`
   - "Production" → `production`
   - "Polish" → `polish`
   - "Release" → `release`

2. **如果 stage.txt 缺失**，从产品文件推断阶段（最先进的匹配获胜）：
   - `src/` 有 10+ 源文件 → `production`
   - `production/stories/*.md` 存在 → `pre-production`
   - `docs/architecture/adr-*.md` 存在 → `technical-setup`
   - `design/gdd/systems-index.md` 存在 → `systems-design`
   - `design/gdd/game-concept.md` 存在 → `concept`
   - 无 → `concept`（新项目）

---

## Step 3：读取会话上下文

读取 `production/session-state/active.md`（如果存在）。提取：
- 最近处理的内容
- 任何进行中的任务或开放问题
- 当前 epic/feature/task 从 STATUS 块（如果存在）

这告诉您用户刚刚完成什么或卡在哪里 — 使用它来个性化输出。

---

## Step 4：检查当前阶段的步骤完成情况

对于当前阶段中的每个步骤（从目录中）：

### 基于产品文件的检查

如果步骤有 `artifact.glob`：
- 使用 Glob 检查是否有匹配模式的文件存在
- 如果指定了 `min_count`，验证至少有那么多文件匹配
- 如果指定了 `artifact.pattern`，使用 Grep 验证模式在匹配的文件中的存在
- **完成** = 产品文件条件满足
- **未完成** = 产品文件缺失或模式未找到

如果步骤有 `artifact.note`（无 glob）：
- 标记为 **MANUAL** — 无法自动检测，将询问用户

如果步骤没有 `artifact` 字段：
- 标记为 **UNKNOWN** — 完成状态不可追踪（例如可重复的实现工作）

### 特殊情况：生产阶段 — 读取 `sprint-status.yaml`

当当前阶段是 `production` 时，在进行任何基于 glob 的故事检查之前，检查 `production/sprint-status.yaml` 是否存在。如果存在，直接读取它：

- 状态为 `in-progress` 的故事 → 显示为"当前活动"
- 状态为 `ready-for-dev` 的故事 → 显示为"下一步"
- 状态为 `done` 的故事 → 计为完成
- 状态为 `blocked` 的故事 → 显示为阻塞，附带 `blocker` 字段

这提供了精确的每个故事状态，无需扫描 markdown。跳过 `implement` 和 `story-done` 步骤的 glob 产品文件检查 — YAML 是权威的。

### 特殊情况：`repeatable: true`（非生产）

对于生产之外的可重复步骤（例如"System GDDs"），产品文件检查告诉您是否已完成*任何*工作，而不是是否已完成。不同地标记这些 — 显示检测到的内容，然后注意它可能正在进行中。

---

## Step 5：查找位置并识别下一步

从完成数据中确定：

1. **最后确认完成的步骤** — 最远的已完成的必需步骤
2. **当前阻塞** — 第一个未完成的*必需*步骤（这是用户接下来必须做的）
3. **可选机会** — 可以在阻塞之前或同时完成的未完成*可选*步骤
4. **即将到来的必需步骤** — 当前阻塞之后的必需步骤（显示为"即将到来"，以便用户提前计划）

如果用户提供了参数（例如"just finished design-review"），即使用产品文件检查不明确，也使用它来推进超过他们命名的步骤。

---

## Step 6：检查进行中的工作

如果 `active.md` 显示活动任务或 epic：
- 在顶部突出显示它："看起来您正在处理 [X]"
- 建议继续它或确认它是否已完成

---

## Step 7：呈现输出

保持**简短直接**。这是一个快速定位，不是报告。

```
## 您的位置：[阶段标签]

**进行中：**[来自 active.md，如果有]

### ✓ 已完成
- [已完成的步骤名称]
- [已完成的步骤名称]

### → 下一步（必需）
**[步骤名称]** — [描述]
命令：`[命令]`

### ~ 也可用（可选）
- **[步骤名称]** — [描述] → `/命令`
- **[步骤名称]** — [描述] → `/命令`

### 之后即将到来
- [下一个必需步骤名称] (`/命令`)
- [下一个必需步骤名称] (`/命令`)

---
接近 **[下一阶段]** 门 → 准备就绪时运行 `/gate-check`。
```

**格式规则：**
- `✓` 表示确认完成
- `→` 表示当前必需的下一步（只有一个 — 第一个阻塞）
- `~` 表示现在可用的可选步骤
- 内联显示命令作为反引号代码
- 如果步骤没有命令（例如"Implement Stories"），解释要做什么而不是显示斜杠命令
- 对于 MANUAL 步骤，询问用户："我无法确定 [步骤] 是否完成 — 它已经完成了吗？"

结论：**完成** — 已识别下一步。

---

## Step 8：门控警告（如果接近）

在当前阶段的步骤之后，检查用户是否可能接近门控：
- 如果当前阶段中的所有必需步骤都已完成（或接近完成），添加："您接近 **[当前] → [下一]** 门控。准备就绪时运行 `/gate-check`。"
- 如果仍有多个必需步骤剩余，跳过门控警告 — 它还不相关。

---

## Step 9：升级路径

在建议之后，如果用户似乎卡住或困惑，添加：

```
---
需要更多细节？
- `/project-stage-detect` — 完整的差距分析，列出所有缺失的产品文件
- `/gate-check` — 下一阶段的正式准备情况检查
- `/start` — 从头开始重新定位
```

仅当用户的输入暗示困惑时才显示此内容（例如"I don't know"、"stuck"、"lost"、"not sure"）。不要为简单的"what's next?"查询显示它。

---

## 协作协议

- **永远不要自动运行下一个技能。** 推荐它，让用户调用它。
- **询问 MANUAL 步骤**而不是假设完成或未完成。
- **匹配用户的语气** — 如果它们听起来有压力（"I'm totally lost"），要 reassuring 并给出一个行动，而不是六个列表。
- **一个主要建议** — 用户应该离开时确切知道接下来要做的一件事。可选步骤和"即将到来"是次要上下文。

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
