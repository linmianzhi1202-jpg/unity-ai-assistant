---
name: team-combat
description: 团队战斗 — 协调多代理开发战斗系统
version: 0.2.0
category: game-development
whenToUse: >
  需要协调多代理开发战斗系统时使用此技能。
  适用于：设计战斗机制、实现战斗代码、创建 VFX/音频、验证架构、编写测试用例。
  支持参数：[combat feature description]（战斗功能描述）。
input:
  - 项目根目录路径（默认当前工作区）
  - 战斗功能描述参数（例如：melee parry system, ranged weapon spread）
output:
  - 结构化战斗系统设计文档（Markdown 格式）
  - 实现代码和测试文件
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 团队战斗技能

## 技能概述

协调多代理开发战斗系统。此技能编排跨职能团队（游戏设计师、游戏性程序员、AI 程序员、技术美术、声音设计师、引擎专家、QA 测试员）来设计、实现和验证战斗功能。

## 使用方式

- 通过 Agent 触发：当用户说「团队战斗」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill team-combat [战斗功能描述]`

**参数检查**：如果未提供战斗功能描述，输出：
> "用法: `/team-combat [战斗功能描述]` — 提供要设计和实现的战斗功能描述（例如：`melee parry system`, `ranged weapon spread`）。"

然后立即停止，不要生成任何子代理或读取任何文件。

当使用有效参数调用此技能时，通过结构化管道编排战斗团队。

**决策点**：在每个阶段转换时，使用 `AskUserQuestion` 向用户展示子代理的方案作为可选选项。在对话中写入代理的完整分析，然后用简洁的标签捕获决策。用户必须在继续下一阶段之前批准。

---

## 团队组成

- **game-designer** — 设计机制，定义公式和边缘情况
- **gameplay-programmer** — 实现核心游戏性代码
- **ai-programmer** — 实现功能的 NPC/敌人 AI 行为
- **technical-artist** — 创建 VFX、着色器效果和视觉反馈
- **sound-designer** — 定义音频事件、冲击音效和环境战斗音频
- **engine-specialist** (primary) — 验证架构和实现模式是否符合引擎习惯（从 `.claude/docs/technical-preferences.md` 引擎专家部分读取）
- **qa-tester** — 编写测试用例并验证实现

---

## 如何委托

使用 Task 工具生成每个团队成员作为子代理：
- `subagent_type: game-designer` — 设计机制，定义公式和边缘情况
- `subagent_type: gameplay-programmer` — 实现核心游戏性代码
- `subagent_type: ai-programmer` — 实现 NPC/敌人 AI 行为
- `subagent_type: technical-artist` — 创建 VFX、着色器效果、视觉反馈
- `subagent_type: sound-designer` — 定义音频事件、冲击音效、环境音频
- `subagent_type: [primary engine specialist]` — 架构和实现的引擎习惯验证
- `subagent_type: qa-tester` — 编写测试用例并验证实现

始终在每个代理的提示中提供完整上下文（设计文档路径、相关代码文件、约束）。在管道允许的情况下并行启动独立代理（例如，阶段 3 代理可以同时运行）。

---

## 管道

### 阶段 1：设计

委托给 **game-designer**：
- 在 `design/gdd/` 中创建或更新设计文档，涵盖：机制概述、玩家幻想、详细规则、带变量定义的公式、边缘情况、依赖项、带安全范围的调优旋钮、验收标准
- 输出：完成的设计文档

### 阶段 2：架构

委托给 **gameplay-programmer**（如果涉及 AI，加上 **ai-programmer**）：
- 审查设计文档
- 设计代码架构：类结构、接口、数据流
- 识别与现有系统的集成点
- 输出：带文件列表和接口定义的架构草图

然后生成**主引擎专家**以验证提议的架构：
- 类/节点/组件结构是否符合固定引擎的习惯？（例如，Godot 节点层次结构、Unity MonoBehaviour vs DOTS、Unreal Actor/Component 设计）
- 是否有应该使用的引擎原生系统而不是自定义实现？
- 固定引擎版本中是否有已弃用或更改的提议 API？
- 输出：引擎架构注释 — 在阶段 3 开始之前合并到架构中

### 阶段 3：实现（尽可能并行）

并行委托：
- **gameplay-programmer**：实现核心战斗机制代码
- **ai-programmer**：实现 AI 行为（如果功能涉及 NPC 反应）
- **technical-artist**：创建 VFX 和着色器效果
- **sound-designer**：定义音频事件列表和混音注释

### 阶段 4：集成

- 连接游戏性代码、AI、VFX 和音频
- 确保所有调优旋钮都已暴露且数据驱动
- 验证功能与现有战斗系统一起工作

### 阶段 5：验证

委托给 **qa-tester**：
- 根据验收标准编写测试用例
- 测试设计中发现的所有边缘情况
- 验证性能影响在预算范围内
- 为发现的任何问题提交错误报告

### 阶段 6：签核

- 收集所有团队成员的结果
- 报告功能状态：COMPLETE / NEEDS_WORK / BLOCKED
- 列出任何未解决的问题及其分配的负责人

---

## 错误恢复协议

如果任何生成的代理（通过 Task）返回 BLOCKED、错误 or 无法完成：

1. **立即上报**：在继续依赖阶段之前向用户报告 "[AgentName]: BLOCKED — [reason]"
2. **评估依赖项**：检查被阻止代理的输出是否是后续阶段所必需的。如果是，在没有用户输入的情况下不要超过该依赖点
3. **通过 AskUserQuestion 提供选项**：
   - 跳过此代理并注意到最终报告中的差距
   - 使用更窄的范围重试
   - 停在这里并首先解决阻止程序
4. **始终生成部分报告** — 输出任何已完成的内容。永远不要因为一个代理被阻止而丢弃工作

常见阻止程序：
- 输入文件缺失（未找到故事，GDD 缺失）→ 重定向到创建它的技能
- ADR 状态是 Proposed → 不要实现；首先运行 `/architecture-decision`
- 范围太大 → 通过 `/create-stories` 拆分为两个故事
- ADR 和故事之间的指令冲突 → 上报冲突，不要猜测

---

## 文件写入协议

所有文件写入（设计文档、实现文件、测试用例）都委托给通过 Task 生成的子代理。每个子代理强制执行 "我可以写入 [path] 吗？" 协议。此编排器不直接写入文件。

---

## 输出

涵盖以下内容的总结报告：设计完成状态、每个团队成员的实现状态、测试结果和任何未解决的问题。

判定：**COMPLETE** — 战斗功能已设计、实现和验证。
判定：**BLOCKED** — 一个或多个阶段无法完成；生成带有未解决项目列表的部分报告。

---

## 后续步骤

- 在关闭故事之前对实现的战斗代码运行 `/code-review`
- 运行 `/balance-check` 以验证战斗公式和调优值
- 如果需要 VFX、音频或性能打磨，运行 `/team-polish`

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
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式，升级版本号 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
