---
name: create-control-manifest
description: 创建控制清单 — 生成游戏控制映射文档
version: 0.3.0
category: game-development
whenToUse: >
  当需要创建控制清单技能时使用。
  处理生成游戏控制映射文档相关任务时。
  支持参数：无参数（完整引导）、update（更新现有清单）
input:
  - 项目根目录路径（默认当前工作区）
  - 模式参数：无 / update
output:
  - 结构化结果报告（Markdown 格式）
  - docs/architecture/control-manifest.md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 创建控制清单技能

## 技能概述

生成游戏控制映射文档。

控制清单是一个扁平、可操作的规则表，供程序员使用。它回答"我该做什么？"和"我绝不能做什么？"——按架构层组织，从所有已接受的 ADR、技术偏好和引擎参考文档中提取。ADR 解释 *为什么*，而清单告诉你 *做什么*。

**输出：** `docs/architecture/control-manifest.md`

**何时运行：** 在 `/architecture-review` 通过且 ADR 处于已接受状态后。每当新的 ADR 被接受或现有 ADR 被修订时重新运行。

## 使用方式

- 通过 Agent 触发：当用户说「创建控制清单」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill create-control-manifest [参数]`

---

## 阶段 1：加载所有输入

### ADR

- 搜索 `docs/architecture/adr-*.md` 并读取每个文件
- 仅过滤到已接受的 ADR（Status: Accepted）—— 跳过 Proposed、Deprecated、Superseded
- 注意每个规则来源的 ADR 编号和标题

### 技术偏好

- 读取 `.claude/docs/technical-preferences.md`
- 提取：命名约定、性能预算、批准的库/插件、禁止模式

### 引擎参考

- 读取 `docs/engine-reference/[engine]/VERSION.md` 以获取引擎 + 版本
- 读取 `docs/engine-reference/[engine]/deprecated-apis.md` —— 这些成为禁止 API 条目
- 如果存在，读取 `docs/engine-reference/[engine]/current-best-practices.md`

报告："已加载 [N] 个已接受 ADR，引擎：[名称 + 版本]。"

---

## 阶段 2：从每个 ADR 提取规则

对于每个已接受的 ADR，提取：

### 必需模式（来自"实施指南"部分）

- 每个"必须"、"应该"、"需要"、"总是"的陈述
- 每个强制的模式或方法

### 禁止方法（来自"考虑的替代方案"部分）

- 每个被明确拒绝的替代方案 —— *为什么* 被拒绝成为规则（"永远不要使用 X，因为 Y"）
- 任何被明确指出的反模式

### 性能防护栏（来自"性能影响"部分）

- 预算约束："此系统每帧最多 N ms"
- 内存限制："此系统不得超过 N MB"

### 引擎 API 约束（来自"引擎兼容性"部分）

- 需要验证的截止后 API
- 与默认 LLM 假设不同的已验证行为
- 在固定引擎版本中行为不同的 API 字段或方法

### 层分类

按系统所管辖的架构层对每个规则进行分类：
- **Foundation**：场景管理、事件架构、保存/加载、引擎初始化
- **Core**：核心游戏循环、主要玩家系统、物理/碰撞
- **Feature**：次要系统、次要机制、AI
- **Presentation**：渲染、音频、UI、VFX、着色器

如果一个 ADR 跨越多个层，将规则复制到每个相关层。

---

## 阶段 3：添加全局规则

组合适用于所有层的规则：

### 来自 technical-preferences.md：

- 命名约定（类、变量、信号/事件、文件、常量）
- 性能预算（目标帧率、帧预算、绘制调用限制、内存上限）

### 来自 deprecated-apis.md：

- 所有已弃用的 API → 禁止 API 条目

### 来自 current-best-practices.md（如果可用）：

- 引擎推荐的模式 → 必需条目

### 来自 technical-preferences.md 禁止模式：

- 直接复制任何"禁止模式"条目

---

## 阶段 4：在写入前展示规则摘要

在写入清单之前，向用户展示摘要：

```
## 控制清单预览
引擎：[名称 + 版本]
覆盖的 ADR：[列出 ADR 编号]
提取的规则总数：
  - Foundation 层：[N] 必需，[M] 禁止，[P] 防护栏
  - Core 层：[N] 必需，[M] 禁止，[P] 防护栏
  - Feature 层：...
  - Presentation 层：...
  - 全局：[N] 命名约定，[M] 禁止 API，[P] 批准的库
```

询问："这看起来完整吗？在写入清单之前，有什么规则要添加或删除吗？"

---

## 阶段 4b：总监门控 —— 技术审查

**审查模式检查** —— 在生成 TD-MANIFEST 之前应用：
- `solo` → 跳过。注意："TD-MANIFEST 跳过 —— 单独模式。" 继续阶段 5。
- `lean` → 跳过。注意："TD-MANIFEST 跳过 —— Lean 模式。" 继续阶段 5。
- `full` → 正常生成。

通过 Task 使用门控 **TD-MANIFEST**（`.claude/docs/director-gates.md`）生成 `technical-director`：

传递：阶段 4 的控制清单预览（每层规则计数、完整提取规则列表）、覆盖的 ADR 列表、引擎版本和任何来自 technical-preferences.md 或引擎参考文档的规则。

技术总监审查是否：
- 所有强制 ADR 模式都被捕获并准确陈述
- 禁止方法完整且正确归因
- 没有添加缺乏来源 ADR 或偏好文档的规则
- 性能防护栏与 ADR 约束一致

应用裁决：
- **APPROVE** → 继续阶段 5
- **CONCERNS** → 通过询问用户展示，选项：`修订标记的条目` / `接受并继续` / `进一步讨论`
- **REJECT** → 不要写入清单；修复标记的规则并重新展示摘要

---

## 阶段 5：写入控制清单

询问："我可以将此写入 `docs/architecture/control-manifest.md` 吗？"

格式：

```markdown
# 控制清单

> **引擎**：[名称 + 版本]
> **最后更新**：[日期]
> **清单版本**：[日期]
> **覆盖的 ADR**：[ADR-NNN, ADR-MMM, ...]
> **状态**：[活跃 —— 当 ADR 变更时通过 `/create-control-manifest update` 重新生成]

清单版本是此清单生成的日期。故事文件在创建时嵌入此日期。`/story-readiness` 将故事嵌入的版本与此字段进行比较，以检测针对过时规则编写的故事。始终与 `最后更新` 匹配 —— 它们是同一日期，服务于不同的消费者。

此清单是从所有已接受的 ADR、技术偏好和引擎参考文档中提取的程序员快速参考。有关每个规则背后的推理，请参阅引用的 ADR。

---

## Foundation 层规则

*适用于：场景管理、事件架构、保存/加载、引擎初始化*

### 必需模式

- **[规则]** — 来源：[ADR-NNN]
- **[规则]** — 来源：[ADR-NNN]

### 禁止方法

- **永远不要 [反模式]** — [简要原因] — 来源：[ADR-NNN]

### 性能防护栏

- **[系统]**：最多 [N] ms/帧 — 来源：[ADR-NNN]

---

## Core 层规则

*适用于：核心游戏循环、主要玩家系统、物理、碰撞*

### 必需模式

...

### 禁止方法

...

### 性能防护栏

...

---

## Feature 层规则

*适用于：次要机制、AI 系统、次要功能*

### 必需模式

...

### 禁止方法

...

---

## Presentation 层规则

*适用于：渲染、音频、UI、VFX、着色器、动画*

### 必需模式

...

### 禁止方法

...

---

## 全局规则（所有层）

### 命名约定

| 元素 | 约定 | 示例 |
|---------|-----------|---------|
| 类 | [来自 technical-preferences] | [示例] |
| 变量 | [来自 technical-preferences] | [示例] |
| 信号/事件 | [来自 technical-preferences] | [示例] |
| 文件 | [来自 technical-preferences] | [示例] |
| 常量 | [来自 technical-preferences] | [示例] |

### 性能预算

| 目标 | 值 |
|--------|-------|
| 帧率 | [来自 technical-preferences] |
| 帧预算 | [来自 technical-preferences] |
| 绘制调用 | [来自 technical-preferences] |
| 内存上限 | [来自 technical-preferences] |

### 批准的库 / 插件

- [库] — 批准用于 [目的]

### 禁止的 API（[引擎版本]）

这些 API 在 [引擎 + 版本] 中已弃用或未验证：
- `[api 名称]` — 自 [版本] 起已弃用 / 截止后未验证
- 来源：`docs/engine-reference/[engine]/deprecated-apis.md`

### 跨层约束

- [无论层如何都适用的约束]
```

---

## 阶段 6：建议后续步骤

写入清单后：

- 如果史诗/故事还不存在："运行 `/create-epics layer: foundation` 然后 `/create-stories [epic-slug]` —— 程序员现在可以在编写故事实施说明时使用此清单。"
- 如果这是重新生成（清单已存在）："已更新。建议通知团队规则变更 —— 特别是任何新的禁止条目。"

---

## 协作协议

1. **静默加载** —— 在展示任何内容之前读取所有输入
2. **首先展示摘要** —— 在写入之前让用户看到范围
3. **在写入之前询问** —— 在创建或覆盖清单之前始终确认。写入时：裁决：**COMPLETE** —— 控制清单已写入。拒绝时：裁决：**BLOCKED** —— 用户拒绝写入。
4. **溯源每个规则** —— 永远不要添加无法追溯到 ADR、技术偏好或引擎参考文档的规则
5. **无解释** —— 按 ADR 中所述提取规则；不要以改变含义的方式改述

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
| **0.3.0** | 2026-04-27 | 修复 whenToUse 格式，升级版本号，完善英文翻译 |
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
