---
name: code-review
description: "代码审查 — 六维代码审查框架：正确性、性能、安全、可维护性、可读性、测试覆盖"
version: 0.2.0
category: game-development
whenToUse: >
  需要通过代码审查技能审查代码、检查六维代码质量（正确性、性能、安全、可维护性、可读性、测试覆盖）、
  或生成结构化代码审查报告时，使用此技能。
  支持参数：[file-path]（指定审查文件）、无参数（审查当前打开的文件）。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标文件路径参数：[file-path] / 无
output:
  - 代码审查报告（Markdown 格式）
  - 按严重性排序的问题列表
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 代码审查技能#

## 技能概述#

六维代码审查框架：正确性、性能、安全、可维护性、可读性、测试覆盖。

## 使用方式#

- 通过 Agent 触发：当用户说「代码审查」或相关需求时，Agent 应自动加载此 Skill#
- 手动触发：`/skill code-review [参数]`

## 工作流程#

### 阶段 1：加载目标文件#

读取目标文件（们）的完整内容。读取 CLAUDE.md 以获取项目编码标准。

---

### 阶段 2：识别引擎专家#

读取 `.claude/docs/technical-references.md`，`## Engine Specialists` 部分。注意：

- **Primary** 专家（用于架构和广泛的引擎关注点）
- **Language/Code Specialist**（用于审查项目的主要语言文件时）
- **Shader Specialist**（用于审查着色器文件时）
- **UI Specialist**（用于审查 UI 代码时）

如果部分读取为 `[TO BE CONFIGURED]`，则没有引擎被固定 — 跳过引擎专家步骤。

---

### 阶段 3：ADR 合规性检查#

搜索故事文件、提交消息和头注释中的 ADR 引用。查找 `ADR-NNN` 或 `docs/architecture/ADR-` 等模式。

如果未找到 ADR 引用，注意："未找到 ADR 引用 — 跳过 ADR 合规性检查。"

对于每个引用的 ADR：读取文件，提取 **Decision** 和 **Consequences** 部分，然后分类任何偏差：

- **ARCHITECTURAL VIOLATION** (BLOCKING): 使用了 ADR 中明确拒绝的模式
- **ADR DRIFT** (WARNING): 有意义地偏离了选择的方法，但没有使用禁止的模式
- **MINOR DEVIATION** (INFO): 与 ADR 指导的小差异，不影响整体架构

---

### 阶段 4：标准合规性#

识别系统类别（引擎、游戏性、AI、网络、UI、工具）并评估：

- [ ] 公共方法和类有文档注释
- [ ] 每个方法的圈复杂度低于 10
- [ ] 没有方法超过 40 行（排除数据声明）
- [ ] 依赖项被注入（没有用于游戏状态的静态单例）
- [ ] 配置值从数据文件加载
- [ ] 系统暴露接口（不是具体类依赖）

---

### 阶段 5：架构和 SOLID#

**架构：**

- [ ] 正确的依赖方向（引擎 <- 游戏性，不是反向）
- [ ] 模块之间没有循环依赖
- [ ] 适当的层分离（UI 不拥有游戏状态）
- [ ] 用于跨系统通信的事件/信号
- [ ] 与代码库中已建立的模式一致

**SOLID：**

- [ ] 单一职责：每个类有一个变更理由
- [ ] 开闭原则：可扩展而无需修改
- [ ] 里氏替换：子类型可替代基础类型
- [ ] 接口隔离：没有胖接口
- [ ] 依赖倒置：依赖抽象，不是具体实现

---

### 阶段 6：游戏特定关注点#

- [ ] 帧率独立性（delta 时间使用）
- [ ] 热路径中没有分配（更新循环）
- [ ] 正确的 null/空状态处理
- [ ] 需要时的线程安全
- [ ] 资源清理（没有泄漏）

---

### 阶段 7：专家审查（并行）#

同时通过 Task 生成所有适用的专家 — 不要等待一个完成后再开始下一个。

#### 引擎专家#

如果配置了引擎，确定哪个专家适用于每个文件并并行生成：

- 主要语言文件 (`.gd`, `.cs`, `.cpp`) → Language/Code Specialist
- 着色器文件 (`.gdshader`, `.hlsl`, 着色器图形) → Shader Specialist
- UI 屏幕/小组件代码 → UI Specialist
- 交叉切割或不清楚 → Primary Specialist

同时为主要专家生成 **Primary Specialist**，用于任何触及引擎架构的文件（场景结构、节点层次、生命周期钩子）。

#### QA 可测试性审查#

对于 Logic 和 Integration 故事，同时与引擎专家一起通过 Task 生成 `qa-tester`：

- 正在审查的实现文件
- 故事的 `## QA Test Cases` 部分（来自 qa-lead 的预先编写测试规范）
- 故事的 `## Acceptance Criteria`

要求 qa-tester 评估：

- [ ] 所有测试钩子和接口是否暴露（不是隐藏在私有/内部访问后面）？
- [ ] 故事的 `## QA Test Cases` 部分中的 QA 测试用例是否映射到可测试的代码路径？
- [ ] 任何验收标准是否作为实现不可测试（例如，硬编码值，没有用于注入的接缝）？
- [ ] 实现是否引入了任何未由现有 QA 测试用例覆盖的新边缘情况？
- [ ] 是否有任何应该测试但没测试的可见副作用？

对于 Visual/Feel 和 UI 故事：qa-tester 审查 `## QA Test Cases` 中的手动验证步骤是否可通过实现实现 — 例如，"手动检查器需要达到的状态是否实际上可到达？"

在生成输出之前收集所有专家发现。

---

### 阶段 8：输出审查#

```markdown
## Code Review: [File/System Name]

### Engine Specialist Findings: [N/A — no engine configured / CLEAN / ISSUES FOUND]
[Findings from engine specialist(s), or "No engine configured." if skipped]

### Testability: [N/A — Visual/Feel or Config story / TESTABLE / GAPS / BLOCKING]
[qa-tester findings: test hooks, coverage gaps, untestable paths]

### ADR Compliance: [NO ADRS FOUND / COMPLIANT / DRIFT / VIOLATIONS FOUND]
[List each ADR checked, result; and any deviations with severity]

### Standards Compliance: [X/6 passing]
[List failures with line references]

### Architecture: [CLEAN / MINOR ISSUES / VIOLATIONS FOUND]
[List specific architectural concerns]

### SOLID: [COMPLIANT / ISSUES FOUND]
[List specific violations]

### Game-Specific Concerns#
[List game development specific issues]

### Positive Observations#
[What is done well -- always include this section]

### Required Changes#
[Must-fix items before approval — ARCHITECTURAL VIOLATIONS always appear here]

### Suggestions#
[Nice-to-have improvements]

### Verdict: [APPROVED / APPROVED WITH SUGGESTIONS / CHANGES REQUIRED]
```

此技能是只读的 — 不写入文件。

---

### 阶段 9：下一步#

- 如果 verdict 是 APPROVED：运行 `/story-done [story-path]` 以关闭故事。
- 如果 verdict 是 CHANGES REQUIRED：修复问题并重新运行 `/code-review`。
- 如果找到 ARCHITECTURAL VIOLATION：运行 `/architecture-decision` 以记录正确的方法。

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
