---
name: project-stage-detect
description: 项目阶段检测 — 分析现有项目，自动检测开发阶段
version: 0.2.0
category: game-development
whenToUse: >
  需要分析现有项目或自动检测开发阶段时使用此技能。
  适用于：扫描关键目录、分类项目阶段、协作式差距识别、生成阶段报告。
  支持参数：无参数（通用分析）、[role]（按角色过滤建议）。
input:
  - 项目根目录路径（默认当前工作区）
  - 角色参数：无 / programmer / designer / producer
output:
  - 项目阶段分析报告（Markdown 格式）
  - production/project-stage-report.md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 项目阶段检测技能

## 技能概述

分析现有项目，自动检测开发阶段，识别缺失工件和需要关注的问题。

## 使用方式

- 通过 Agent 触发：当用户说「项目阶段检测」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：```/skill project-stage-detect [参数]```

## 工作流

### 1. 扫描关键目录

分析项目结构和内容：

**设计文档** (`design/`)：
- 统计 `design/gdd/*.md` 中的 GDD 文件数
- 检查 game-concept.md、game-pillars.md、systems-index.md
- 如果 systems-index.md 存在，统计总系统数 vs. 已设计系统数
- 分析完整性（概述、详细设计、边缘情况等）
- 统计 `design/narrative/` 中的叙事文档数
- 统计 `design/levels/` 中的关卡设计数

**源代码** (`src/`)：
- 统计源文件数（语言无关）
- 识别主要系统（包含 5+ 文件的目录）
- 检查 core/、gameplay/、ai/、networking/、ui/ 目录
- 估算代码行数（粗略规模）

**生产工件** (`production/`)：
- 检查活跃冲刺计划
- 查找里程碑定义
- 查找路线图文档

**原型** (`prototypes/`)：
- 统计原型目录数
- 检查 README（有文档 vs 无文档）
- 评估原型是已归档还是活跃

**架构文档** (`docs/architecture/`)：
- 统计 ADR（架构决策记录）数
- 检查概览/索引文档

**测试** (`tests/`)：
- 统计测试文件数
- 估算测试覆盖率（粗略启发式）

---

### 2. 分类项目阶段

基于扫描的工件，确定阶段。首先检查 `production/stage.txt` — 如果存在，使用其值（来自 `/gate-check` 的显式覆盖）。否则，使用这些启发式自动检测（从最先进的向后检查）：

| 阶段 | 指标 |
|------|------|
| **概念** | 无游戏概念文档，头脑风暴阶段 |
| **系统设计** | 游戏概念存在，系统索引缺失或未完成 |
| **技术设置** | 系统索引存在，引擎未配置 |
| **预生产** | 引擎已配置，`src/` 有 <10 个源文件 |
| **生产** | `src/` 有 10+ 个源文件，活跃开发 |
| **打磨** | 仅显式（由 `/gate-check` Production → Polish 门控设置） |
| **发布** | 仅显式（由 `/gate-check` Polish → Release 门控设置） |

---

### 3. 协作式差距识别

**不要**只是列出缺失的文件。相反，**询问澄清问题**：

- "我看到战斗代码 (`src/gameplay/combat/`)，但没有 `design/gdd/combat-system.md`。这是先原型化了，还是我们应该反向文档化？"
- "你有 15 个 ADR，但没有架构概览。我应该创建一个以帮助新贡献者吗？"
- "`production/` 中没有冲刺计划。你在其他地方跟踪工作吗（Jira、Trello 等）？"
- "我找到了游戏概念，但没有系统索引。你已经将概念分解为单个系统了吗，还是我们应该运行 `/map-systems`？"
- "原型目录有 3 个项目，没有 README。这些是实验，还是需要文档？"

---

### 4. 生成阶段报告

使用模板：`.claude/docs/templates/project-stage-report.md`

**报告结构**：

```markdown
# 项目阶段分析

**日期**：[日期]
**阶段**：[概念/系统设计/技术设置/预生产/生产/打磨/发布]
**阶段置信度**：[PASS — 清晰检测 / CONCERNS — 模糊信号 / FAIL — 关键差距阻止进度]

## 完整性概览

- 设计：[X%] ([N] 个文档，[差距])
- 代码：[X%] ([N] 个文件，[系统])
- 架构：[X%] ([N] 个 ADR，[差距])
- 生产：[X%] ([状态])
- 测试：[X%] ([覆盖率估算])

## 识别的差距

1. [差距描述 + 澄清问题]
2. [差距描述 + 澄清问题]

## 推荐下一步

[基于阶段和角色的优先级排序列表]
```

---

### 5. 角色过滤建议（可选）

如果用户提供了 role 参数（例如，`/project-stage-detect programmer`）：

**程序员**：
- 关注架构文档、测试覆盖率、缺失的 ADR
- 代码到文档的差距

**设计师**：
- 关注 GDD 完整性、缺失的设计部分
- 原型文档

**制作人**：
- 关注冲刺计划、里程碑跟踪、路线图
- 跨团队协调文档

**通用**（无角色）：
- 所有差距的整体视图
- 跨域的最高优先级项目

---

### 6. 写入前请求批准

**协作协议**：

```
我分析了你的项目。这是我发现的：

[显示摘要]

识别的差距：
1. [差距 1 + 问题]
2. [差距 2 + 问题]

推荐下一步：
- [优先级 1]
- [优先级 2]
- [优先级 3]

我可以将完整阶段分析写入 production/project-stage-report.md 吗？
```

等待用户批准后再创建文件。

---

## 示例用法

```bash
# 通用项目分析
/project-stage-detect

# 程序员焦点分析
/project-stage-detect programmer

# 设计师焦点分析
/project-stage-detect designer
```

---

## 后续行动

生成报告后，建议相关的下一步：

- **概念存在但无系统索引？** → `/map-systems` 分解为系统
- **缺失设计文档？** → `/reverse-document design src/[system]`
- **缺失架构文档？** → `/architecture-decision` 或 `/reverse-document architecture`
- **原型需要文档？** → `/reverse-document concept prototypes/[name]`
- **无冲刺计划？** → `/sprint-plan`
- **接近里程碑？** → `/milestone-review`

---

## 协作协议

此技能遵循协作设计原则：

1. **首先提问**：询问差距，不要假设
2. **展示选项**："我应该创建 X，还是它在其他地方跟踪？"
3. **用户决定**：等待方向
4. **展示草稿**：显示报告摘要
5. **获得批准**："我可以将写入 production/project-stage-report.md 吗？"

**永远不要**静默写入文件。**始终**展示发现并在创建工件之前询问。

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
