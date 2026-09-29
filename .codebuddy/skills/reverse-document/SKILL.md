---
name: reverse-document
description: 逆向文档 — 从现有代码生成文档，创建反向文档
version: 0.2.0
category: game-development
whenToUse: >
  需要从现有代码生成文档或创建反向文档时使用此技能。
  适用于：未先编写设计文档就构建了功能、继承了没有文档的代码库、
  原型化机制并需要形式化它、需要记录现有代码背后的"为什么"。
  支持参数：<type> <path>（type: design / architecture / concept）。
input:
  - 项目根目录路径（默认当前工作区）
  - 类型和路径参数（必需）
output:
  - 反向设计/架构/概念文档（Markdown 格式）
  - 相应的文档文件生成（design/gdd/[system].md / docs/architecture/ADR-[N]-[slug].md / prototypes/[name]/CONCEPT.md）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 逆向文档技能#

## 技能概述#

从现有代码生成文档，创建反向文档。此技能分析现有实现（代码、原型、系统）并生成适当的设计或架构文档。用于在未先编写设计文档的情况下构建了功能、继承了没有文档的代码库、原型化机制并需要形式化它、或需要记录现有代码背后的"为什么"。

## 使用方式#

- 通过 Agent 触发：当用户说「逆向文档」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill reverse-document <type> <path>`

**示例**：
```bash
/reverse-document design src/gameplay/magic-system
/reverse-document architecture src/core/entity-component
/reverse-document concept prototypes/vehicle-combat
```

---

## Phase 1: 解析参数#

**格式**：`/reverse-document <type> <path>`

**类型选项**：
- `design` → 生成游戏设计文档（GDD 部分）
- `architecture` → 生成架构决策记录（ADR）
- `concept` → 从原型生成概念文档

**路径**：要分析的目录或文件：
- `src/gameplay/combat/` → 所有战斗相关代码
- `src/core/event-system.cpp` → 特定文件
- `prototypes/stealth-mech/` → 原型目录

---

## Phase 2: 分析实现#

**读取并理解代码/原型**：

**对于设计文档（GDD）**：
- 识别机制、规则、公式
- 提取游戏性值（伤害、冷却时间、范围）
- 找到状态机、能力系统、进度
- 检测代码中处理的边缘情况
- 映射依赖关系（什么系统交互？）

**对于架构文档（ADR）**：
- 识别模式（ECS、单例、观察者等）
- 理解技术决策（线程、序列化等）
- 映射依赖关系和耦合
- 评估性能特征
- 找到约束和权衡

**对于概念文档（原型分析）**：
- 识别核心机制
- 提取突现的游戏性模式
- 注意什么有效 vs. 什么无效
- 找到技术可行性见解
- 记录玩家幻想 / 感觉

---

## Phase 3: 询问澄清问题#

**不要**只是描述代码。**询问**意图：

**设计问题**：
- "我看到 [资源] 系统在 [活动] 时消耗。这是用于："
  - 节奏（防止垃圾邮件）？
  - 资源管理（策略深度）？
  - 还是其他？"

- "[机制] 似乎是核心。这是核心支柱，还是支持功能？"

- "[值] 按 [因子] 缩放。有意的还是需要调整平衡？"

**架构问题**：
- "您使用服务定位器模式。这是选择用于："
  - 可测试性（模拟依赖）？
  - 解耦（减少硬引用）？
  - 还是从现有代码继承？"

- "我看到手动内存管理而不是智能指针。性能要求，还是遗留？"

**概念问题**：
- "原型强调潜行胜过战斗。这是预期支柱吗？"

- "玩家似乎利用抓取钩进行加速。功能还是错误？"

---

## Phase 4: 展示发现#

在起草之前，向用户展示您发现了什么：

```
我分析了 [路径]/。这是我发现：

已实现的机制：
- [机制-a] 带有 [属性]（例如，时机窗口、冷却时间）
- [机制-b]（例如，[系统 a] 和 [系统 b] 之间的交互）
- [资源] 系统（在 [动作] 时消耗，在 [条件] 时重新生成）

已发现的公式：
- [输出] = [公式使用发现的变量]
- [次要输出] = [公式]

未清除的意图领域：
- [资源] 系统 — 节奏或资源管理？
- [机制] — 核心支柱还是支持？
- [值] 缩放 — 有意设计还是需要调整？
```

**等待用户澄清意图后再起草。**

---

## Phase 5: 起草文档使用模板#

基于类型，使用适当的模板：

| 类型 | 模板 | 输出路径 |
|------|----------|-------------|
| `design` | `templates/design-doc-from-implementation.md` | `design/gdd/[system-name].md` |
| `architecture` | `templates/architecture-doc-from-code.md` | `docs/architecture/[decision-name].md` |
| `concept` | `templates/concept-doc-from-prototype.md` | `prototypes/[name]/CONCEPT.md` 或 `design/concepts/[name].md` |

**起草结构**：
- 捕获**存在什么**（机制、模式、实现）
- 记录**为什么存在**（通过用户澄清的意图）
- 识别**缺失什么**（代码未处理的边缘情况、设计差距）
- 标记**后续工作**（平衡调整、缺失功能）

---

## Phase 6: 展示草案并请求批准#

**协作协议**：

```
我基于您的代码和澄清起草了 [system-name] 设计文档。

[展示关键部分：概述、机制、公式、设计意图]

添加的条款：
- 将 [机制] 记录为"[意图]" 根据您的澄清
- 添加了代码中未处理的边缘情况（例如，[资源] 在 [动作] 期间达到 0 时？）
- 标记了平衡问题：[缩放类型] 在 [边界条件] 时的缩放

标记为未完成的部分：
- "[系统] 与 [其他系统] 的交互"（尚未完全实现）
- "[变体或功能]"（到目前为止仅实现了 [子集]）

我可以将此写入 design/gdd/[system-name].md 吗？
```

**等待批准。用户可能在写入前请求更改。**

---

## Phase 7: 写入带元数据的文档#

批准时，使用特殊标记写入文件：

```markdown
---
status: reverse-documented
source: [path/]
date: [today]
verified-by: [User name]
---

# [系统名称] 设计#

> **注意**：此文档是从现有实现逆向工程的。它捕获了当前行为和澄清的设计意图。某些部分可能不完整，其中实现是部分性的或意图不明确。

[文档的其余部分...]
```

---

## Phase 8: 标记后续工作#

写入后，建议后续步骤：

```
✅ 写入 design/gdd/combat-system.md

建议的后续行动：
1. 对战斗公式运行 /balance-check（指数缩放问题）
2. 为耐力系统架构决策创建 ADR
3. 实现缺失的边缘情况：
   - 连击期间耐力耗尽时的行为
   - 闪避期间的眩晕状态
4. 实现武器种类时扩展设计文档

您想让我现在处理这些吗？
```

---

## 模板选择逻辑#

| 如果分析... | 使用模板... | 因为... |
|---------------|----------------|------------|
| `src/gameplay/*` | design-doc-from-implementation.md | 游戏性机制 → GDD |
| `src/core/*`, `src/ai/*` | architecture-doc-from-code.md | 核心系统 → ADR |
| `prototypes/*` | concept-doc-from-prototype.md | 实验 → 概念文档 |
| `src/networking/*` | architecture-doc-from-code.md | 技术系统 → ADR |
| `src/ui/*` | design-doc-from-implementation.md | UI/UX → 设计规格 |

---

## 示例会话：逆向文档系统#

```
用户：/reverse-document design src/gameplay/[system]

Agent: 我将分析您的 [系统] 实现以创建设计文档。
       [读取代码，发现机制、公式]

Agent: 我分析了 src/gameplay/[system]/。这是我发现：
       [展示机制、公式、不清楚的领域]

       在起草之前，您能澄清：
       1. [资源] 系统意图？
       2. 是 [机制] 核心支柱吗？
       3. [值] 缩放 — 有意还是需要调整？

用户：1. [资源] 用于节奏，防止 [不需要的行为]
       2. [机制] 是核心 — 我想要 [设计意图]
       3. 是的，指数太高，应该是线性

Agent: 完美，这澄清了愿景。让我起草设计文档。
       [展示带澄清意图的草案]

       我可以将其写入 design/gdd/[system-name].md 吗？

用户：是的，写入它。

Agent: ✅ 写入 design/gdd/[system-name].md
       ✅ 标记为 [REVERSE-DOCUMENTED]
       ✅ 标记了 [值] 缩放以进行重新平衡

       下一步：
       - 更新 [公式] 为 [正确的缩放]
       - 运行 /balance-check 以验证 [曲线]
       - 实现时将 [机制] 记录为核心支柱在 game-pillars.md
```

---

## 协作协议#

此技能遵循协作设计原则：
1. **首先分析**：读取代码，理解实现
2. **询问意图**：询问"为什么"，不只是"什么"
3. **展示发现**：展示发现，突出不清楚的领域
4. **用户澄清**：分离意图与意外
5. **起草文档**：基于现实 + 意图创建文档
6. **展示草案**：显示关键部分，解释添加
7. **获取批准**："我可以写入 [文件路径] 吗？" 批准时：结论：**完成** — 文档已生成。拒绝时：结论：**已锁定** — 用户拒绝写入。
8. **标记后续**：建议相关工作，不要自动执行

**永远不要**假设意图。在记录"为什么"之前始终询问。**

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

---

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
