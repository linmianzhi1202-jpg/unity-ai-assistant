---
name: create-epics
description: 创建史诗 — 将游戏概念分解为主要系统，创建史诗列表
version: 0.3.0
category: game-development
whenToUse: >
  当需要创建史诗技能时使用。
  处理将游戏概念分解为主要系统、创建史诗列表相关任务时。
  支持参数：all（所有层）、layer: foundation/core/feature/presentation、[system-name]（指定系统）。
input:
  - 项目根目录路径（默认当前工作区）
  - 模式参数：all / layer: [name] / [system-name]
output:
  - 结构化结果报告（Markdown 格式）
  - production/epics/[epic-slug]/EPIC.md 文件生成
  - production/epics/index.md 文件更新
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 创建史诗技能

## 技能概述

将游戏概念分解为主要系统，创建史诗列表。

史诗是一个命名的、有边界的工作体，它映射到一个架构模块。它定义 **什么** 需要构建以及 **谁在架构上拥有它**。它不规定实施步骤 —— 那是故事的工作。

**每个层运行此技能一次**，随着开发接近该层。在 Core 几乎完成之前，不要创建 Feature 层史诗 —— 设计会改变。

**输出：** `production/epics/[epic-slug]/EPIC.md` + `production/epics/index.md`

**每个史诗后的下一步：** `/create-stories [epic-slug]`

**何时运行：** 在 `/create-control-manifest` 和 `/architecture-review` 通过后。

## 使用方式

- 通过 Agent 触发：当用户说「创建史诗」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill create-epics [参数]`

---

## 阶段 1：解析参数

解析审查模式（一次，为此运行的所有门控生成存储）：
1. 如果传递了 `--review [full|lean|solo]` → 使用那个值
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认 `lean`

参阅 `.claude/docs/director-gates.md` 了解完整检查模式。

**模式：**
- `/create-epics all` — 按层顺序处理所有系统
- `/create-epics layer: foundation` — 仅 Foundation 层
- `/create-epics layer: core` — 仅 Core 层
- `/create-epics layer: feature` — 仅 Feature 层
- `/create-epics layer: presentation` — 仅 Presentation 层
- `/create-epics [system-name]` — 一个特定系统
- 无参数 — 询问："您想为哪个层或系统创建史诗？"

---

## 阶段 2：加载输入

### 步骤 2a — 摘要扫描（快速）

在所有 GDD 中搜索 `## Summary` 部分，然后再完整读取任何内容：

```
search_content pattern="## Summary" path="design/gdd/*.md" output_mode="content" contextAfter=5
```

对于 `layer:` 或 `[system-name]` 模式：根据摘要快速参考过滤到仅范围内 GDD。跳过完整读取任何超出范围的内容。

### 步骤 2b — 完整文档加载（仅范围内系统）

使用步骤 2a 的搜索结果，识别范围内的系统。仅读取 **范围内系统** 的完整文档 —— 不要读取超出范围或层的 GDD 或 ADR。

读取范围内系统：

- `design/gdd/systems-index.md` — 权威系统列表、层、优先级
- 仅范围内 GDD（Approved 或 Designed 状态，由步骤 2a 结果过滤）
- `docs/architecture/architecture.md` — 模块所有权和 API 边界
- 其域覆盖范围内系统的已接受 ADR **仅** —— 读取"GDD 需求覆盖"、"决策"和"引擎兼容性"部分；跳过不相关域的 ADR
- `docs/architecture/control-manifest.md` — 清单版本日期（来自标头）
- `docs/architecture/tr-registry.yaml` — 用于追踪需求到 ADR 覆盖
- `docs/engine-reference/[engine]/VERSION.md` — 引擎名称、版本、风险级别

报告："已加载 [N] 个 GDD，[M] 个 ADR，引擎：[名称 + 版本]。"

---

## 阶段 3：处理顺序

按依赖安全的层顺序处理：
1. **Foundation**（无依赖）
2. **Core**（依赖于 Foundation）
3. **Feature**（依赖于 Core）
4. **Presentation**（依赖于 Feature + Core）

在每层内，使用 `systems-index.md` 中的顺序。

---

## 阶段 4：定义每个史诗

对于每个系统，将其映射到 `architecture.md` 中的架构模块。

根据 TR 注册表检查 ADR 覆盖：
- **已追踪的需求**：有已接受 ADR 覆盖它们的 TR-ID
- **未追踪的需求**：没有 ADR 的 TR-ID —— 在继续之前警告

在写入任何内容之前向用户展示：

```
## 史诗：[系统名称]

**层**：[Foundation / Core / Feature / Presentation]
**GDD**：design/gdd/[filename].md
**架构模块**：[来自 architecture.md 的模块名称]
**管辖 ADR**：[ADR-NNNN, ADR-MMMM]
**引擎风险**：[LOW / MEDIUM / HIGH — 管辖 ADR 中的最高风险]
**ADR 覆盖的 GDD 需求**：[N / 总数]
**未追踪的需求**：[列出没有 ADR 的 TR-ID，或"无"]
```

如果有未追踪的需求：
> "⚠️ [系统] 中的 [N] 个需求没有 ADR。可以创建史诗，但在 ADR 存在之前，这些需求的故事将被标记为 Blocked。"
> 首先运行 `/architecture-decision`，或继续并使用占位符。"

询问："我应该创建史诗：[名称] 吗？"
选项："是，创建它"、"跳过"、"暂停 —— 我需要先编写 ADR"

---

## 阶段 4b：制作人史诗结构门控

**审查模式检查** —— 在生成 PR-EPIC 之前应用：
- `solo` → 跳过。注意："PR-EPIC 跳过 —— 单独模式。" 继续阶段 5（写入史诗文件）。
- `lean` → 跳过（不是 PHASE-GATE）。注意："PR-EPIC 跳过 —— Lean 模式。" 继续阶段 5（写入史诗文件）。
- `full` → 正常生成。

在所有当前层的史诗定义后（所有范围内系统的阶段 4 完成），在写入任何文件之前，通过 Task 使用门控 **PR-EPIC**（`.claude/docs/director-gates.md`）生成 `producer`：

传递：完整史诗结构摘要（所有史诗、其范围摘要、管辖 ADR 计数）、正在处理的层、里程碑时间表和团队能力。

展示制作人的评估。如果 UNREALISTIC，在写入之前提供修订史诗边界（拆分过大或合并过小）。如果 CONCERNS，展示它们并让用户决定。在制作人门控解决之前，不要写入史诗文件。

---

## 阶段 5：写入史诗文件

批准后，询问："我可以将史诗文件写入 `production/epics/[epic-slug]/EPIC.md` 吗？"

用户确认后，写入：

### `production/epics/[epic-slug]/EPIC.md`

```markdown
# 史诗：[系统名称]

> **层**：[Foundation / Core / Feature / Presentation]
> **GDD**：design/gdd/[filename].md
> **架构模块**：[模块名称]
> **状态**：Ready
> **故事**：尚未创建 —— 运行 `/create-stories [epic-slug]`

## 概述

[1 段描述此史诗实现什么，派生自 GDD 概述和架构模块的职责说明]

## 管辖 ADR

| ADR | 决策摘要 | 引擎风险 |
|-----|-----------------|-------------|
| ADR-NNNN: [标题] | [1 行摘要] | LOW/MEDIUM/HIGH |

## GDD 需求

| TR-ID | 需求 | ADR 覆盖 |
|-------|-------------|--------------|
| TR-[system]-001 | [来自注册表的需求文本] | ADR-NNNN ✅ |
| TR-[system]-002 | [需求文本] | ❌ 无 ADR |

## 完成定义

当以下情况时，此史诗完成：
- 所有故事都已实现、审查并通过 `/story-done` 关闭
- `design/gdd/[filename].md` 的所有验收标准都已验证
- 所有 Logic 和 Integration 故事在 `tests/` 中都有通过的测试文件
- 所有 Visual/Feel 和 UI 故事在 `production/qa/evidence/` 中都有证据文档和签署

## 下一步

运行 `/create-stories [epic-slug]` 将此史诗分解为可实现的故
```

### 更新 `production/epics/index.md`

创建或更新主索引：

```markdown
# 史诗索引

最后更新：[日期]
引擎：[名称 + 版本]

| 史诗 | 层 | 系统 | GDD | 故事 | 状态 |
|------|-------|--------|-----|---------|--------|
| [名称] | Foundation | [系统] | [文件] | 尚未创建 | Ready |
```

---

## 阶段 6：门控检查提醒

写入所有请求范围的史诗后：

- **Foundation + Core 完成**：这些是 Pre-Production → Production 门控所必需的。运行 `/gate-check production` 检查就绪性。
- **提醒**：史诗定义范围。故事定义实施步骤。在开发人员可以领取工作之前，为每个史诗运行 `/create-stories [epic-slug]`。

---

## 协作协议

1. **一次一个史诗** —— 在请求创建之前展示每个史诗定义
2. **在差距上警告** —— 在继续之前标记未追踪的需求
3. **在写入之前询问** —— 在写入任何文件之前获得每个史诗的批准
4. **无发明** —— 所有内容来自 GDD、ADR 和架构文档
5. **永远不要创建故事** —— 此技能在史诗级别停止

所有请求的史诗处理后：

- **裁决：COMPLETE** —— [N] 个史诗已写入。为每个史诗运行 `/create-stories [epic-slug]`。
- **裁决：BLOCKED** —— 用户拒绝所有史诗，或未找到符合条件的系统。

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
| **0.3.0** | 2026-04-27 | 修复 whenToUse 格式，清理标题多余#符号，升级版本号 |
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
