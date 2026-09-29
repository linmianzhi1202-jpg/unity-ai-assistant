---
name: team-qa
description: 团队 QA — 协调多代理质量保证
version: 0.2.0
category: game-development
whenToUse: >
  当需要协调多代理质量保证时使用此技能。
  通过结构化测试周期协调 QA 团队，包括 QA 策略、测试计划生成、
  测试用例编写、手动执行、签署报告。
  适用于：冲刺结束 QA、功能验证、回归测试周期。
input:
  - 项目根目录路径（默认当前工作区）
  - 冲刺标识符或功能名称参数
output:
  - QA 策略文档（production/qa/qa-plan-[sprint].md）
  - 测试计划（production/qa/qa-plan-[sprint].md）
  - 测试用例文档（每个故事一个）
  - QA 签署报告（production/qa/qa-signoff-[sprint].md）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 团队 QA 技能#

## 技能概述#

协调多代理质量保证。当调用此技能时，通过结构化测试周期协调 QA 团队。

**适用场景**：
- 冲刺结束 QA
- 功能验证
- 回归测试周期
- 发布前质量门控

**团队组成**：
- **qa-lead**（QA 负责人）— QA 策略、测试计划生成、故事分类、签署报告
- **qa-tester**（QA 测试员）— 测试用例编写、Bug 报告编写、手动 QA 文档

## 使用方式#

- 通过 Agent 触发：当用户说「团队 QA」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill team-qa [参数]`

**参数模式**：
- `/team-qa [sprint-id]` — 为特定冲刺运行完整 QA 周期
- `/team-qa [feature-name]` — 为特定功能运行 QA
- 无参数 — 使用 `AskUserQuestion` 询问范围#

---

## 阶段 0: 解析参数#

**参数**: `$ARGUMENTS[0]` (空白 = 询问用户）

从参数确定模式：

| 参数 | 模式 | 操作 |
|----------|------|----------|
| `[sprint-id]` | 冲刺模式 | 读取 `production/sprints/[sprint-id]/` 中的所有故事文件 |
| `[feature-name]` | 功能模式 | 全局搜索 `production/epics/[feature-name]/story-*.md` |
| 无参数 | 询问 | 使用 `AskUserQuestion` |

---

## 阶段 1: 加载上下文#

在做任何其他事情之前，收集完整范围：

### 1a: 检测范围#

根据参数：

**单个冲刺**：读取 `production/sprints/` 中最近修改的文件。从冲刺计划中提取故事文件路径列表。读取每个故事文件。

**功能**：全局搜索 `production/epics/[system-name]/story-*.md`。读取每个文件。

**所有故事**：读取 `production/session-state/active.md` 以获取当前冲刺。读取该冲刺中的所有故事。

对于每个故事，收集：
- `Type:` 字段（Logic / Integration / Visual/Feel / UI / Config/Data）
- `## Test Evidence` 部分 — 陈述的预期测试文件路径或证据文档
- 故事标签（从文件名）
- 系统名称（从目录路径）
- 验收标准列表（所有复选框项目）

### 1b: 读取项目上下文#

- 读取 `CLAUDE.md` 以获取技术栈和团队结构
- 读取 `production/milestones/` 中的最新里程碑
- 读取 `tests/regression-suite.md`（如果存在）以获取已隔离测试列表
- 读取 `design/accessibility-requirements.md`（如果存在）以获取可访问性层级#

---

## 阶段 2: QA 策略（qa-lead）#

生成 **qa-lead** 以审查所有范围内故事并生成 QA 策略。

提示 qa-lead：
- 读取每个故事文件
- 按类型对每个故事进行分类：**Logic** / **Integration** / **Visual/Feel** / **UI** / **Config/Data**
- 识别哪些故事需要自动化测试证据 vs. 手动 QA
- 标记任何缺失验收标准或缺失测试证据的故事
- 估算手动 QA 工作量（需要的测试会话数量）
- 检查 `tests/smoke/` 中的冒烟测试场景；对于每个，评估给定当前构建是否可以验证#

**输出**：QA 策略摘要表#

```markdown
## QA 策略：[冲刺/功能名称]

**生成日期**: [今天]
**范围**: [冲刺 ID 或功能名称]
**故事数量**: [N]

### 故事分类#

| 故事 | 类型 | 自动化测试 | 手动 QA | 阻止项 |
|-------|------|--------------|-----------|----------|
| [标题] | Logic | 需要 | 不需要 | 无 |
| [标题] | Visual/Feel | 不需要 | 需要 | 签署缺失 |

### 冒烟检查结果#

[PASS / PASS WITH WARNINGS / FAIL] — [详细信息]

### 估算工作量#

- 自动化测试审查：[N] 个故事
- 手动 QA 会话：[N] 个会话（每个约 15 分钟）
- 总估算时间：[N] 小时
```

向用户展示 qa-lead 的策略。使用 `AskUserQuestion`：
```
question: "QA 策略已就绪。继续到测试计划？"
options:
  - "看起来不错 — 继续到测试计划"
  - "调整故事类型"
  - "跳过阻止的故事并继续"
  - "冒烟检查失败 — 先修复问题"
```

**如果冒烟检查 *FAIL***：不要继续到阶段 3。表面失败并停止。判定：**已阻止** — 冒烟检查失败。

---

## 阶段 3: 测试计划生成#

使用阶段 2 中的 QA 策略生成结构化测试计划文档。

**输出**：`production/qa/qa-plan-[sprint]-[date].md`

```markdown
## 测试计划：[冲刺/功能名称]

**生成日期**: [日期]
**QA 负责人**: [姓名]
**范围**: [冲刺/功能]

### 1. 范围#

[故事列表和类型]

### 2. 故事分类表#

| 故事 | 类型 | 自动化测试必需 | 手动 QA 必需 | 问题 |
|-------|------|--------------------|--------------------|--------|
| [标题] | Logic | 是 | 否 | 无 |
| [标题] | Visual/Feel | 否 | 是 | 签署缺失 |

### 3. 自动化测试需求#

[需要测试文件的系统列表，每个的预期路径]

### 4. 手动 QA 范围#

[需要手动遍历及其验证内容的故事列表]

### 5. 退出标准#

[在 QA 周期可以完成之前必须为真的内容]
```

询问："我可以将此测试计划写入 `production/qa/qa-plan-[sprint]-[date].md` 吗？"

仅在批准后写入。

---

## 阶段 4: 测试用例编写（qa-tester）#

对于每个需要手动 QA 的故事（Visual/Feel、UI、没有自动化测试的 Integration）：

生成 **qa-tester**（并行，如果可能）：

提示 qa-tester：
- 故事文件路径
- 该故事的 QA 计划部分
- GDD 验收标准（如果可用）
- 现有测试证据（如果有）#

**每个测试用例集应包括**：
- **前置条件**：测试开始前的游戏状态
- **步骤**：编号、明确的操作
- **预期结果**：应该发生什么
- **实际结果**：留给测试人员填写的字段
- **通过/失败**：留空的字段#

向用户展示每个故事的测试用例以进行审查。分批进行（一次 3-4 个故事）。

使用 `AskUserQuestion` 每个故事组：
```
question: "测试用例已准备好用于 [故事组]。在手动 QA 开始之前审查？"
options:
  - "已批准 — 开始此组的手动 QA"
  - "修订测试用例以 [故事名称]"
  - "跳过此故事的手动 QA — 尚未准备好"
```

**输出**：测试用例文档（每个故事一个，存储在 `production/qa/evidence/` 中）

---

## 阶段 5: 手动 QA 执行#

遍历批准的手手动 QA 列表中的每个故事。

分批进行（一次 3-4 个故事）并使用 `AskUserQuestion`：
```
question: "手动 QA — [故事标题]\n[要测试内容的简要描述]"
options:
  - "PASS — 所有验收标准已验证"
  - "PASS WITH NOTES — 发现小问题（之后描述）"
  - "FAIL — 标准未满足（之后描述）"
  - "BLOCKED — 尚无法测试（原因）"
```

收集所有结果后，汇总：
- 故事 PASS: [计数]
- 故事 PASS WITH NOTES: [计数]
- 故事 FAIL: [计数] — 已提交 Bug：[ID]
- 故事 BLOCKED: [计数]#

**对于每个 FAIL 结果**：使用 `AskUserQuestion` 收集失败描述，然后生成 **qa-tester** 通过 Task 编写正式 Bug 报告到 `production/qa/bugs/`。

Bug 报告命名：`BUG-[NNN]-[short-slug].md`（从目录中的现有 Bug 递增 NNN）。

---

## 阶段 6: QA 签署报告#

生成 **qa-lead** 以使用阶段 2-5 的所有结果生成签署报告。

提示 qa-lead 使用：
- 测试计划（来自阶段 3）
- 手动 QA 结果（来自阶段 5）
- 任何已提交的 Bug 报告#

**签署报告格式**：

```markdown
## QA 签署报告：[冲刺/功能]

**日期**: [日期]
**QA 负责人签署**: [待定]
**制作人签署**: [待定]

### 结果摘要#

| 故事 | 类型 | 自动化测试 | 手动 QA | 结果 |
|-------|------|--------------|-----------|--------|
| [标题] | Logic | PASS | — | PASS |
| [标题] | Visual/Feel | — | PASS | PASS |

### 已提交的 Bug#

| ID | 故事 | 严重性 | 状态 |
|----|-------|----------|--------|
| BUG-001 | [故事] | S2 | 打开 |

### 判定: APPROVED / APPROVED WITH CONDITIONS / NOT APPROVED#

[基于结果的判定和原理]

### 下一步#

[基于判定的指导]
```

**判定规则**：
- **APPROVED**：所有故事 PASS 或 PASS WITH NOTES；无 S1/S2 Bug 打开
- **APPROVED WITH CONDITIONS**：S3/S4 Bug 打开，或 PASS WITH NOTES 问题已记录；无 S1/S2 Bug
- **NOT APPROVED**：任何 S1/S2 Bug 打开；或故事 FAIL 而没有已记录权宜之计#

向用户展示签署报告。使用 `AskUserQuestion`：
```
question: "QA 签署报告已就绪。写入文件？"
options:
  - "已批准 — 写入签署报告"
  - "修订报告"
  - "取消 — 不要写入文件"
```

如果是：写入 `production/qa/qa-signoff-[sprint]-[date].md`。

判定：**完成** — QA 周期已完成。
判定：**已阻止** — 用户拒绝写入。

---

## 阶段 7: 错误恢复协议#

如果任何生成的代理（通过 Task）返回 **BLOCKED**、错误，或无法完成：

1. **立即表面**：在继续依赖阶段之前，向用户报告 "[AgentName]: BLOCKED — [原因]"。
2. **评估依赖关系**：检查被阻止代理的输出是否是后续阶段所必需的。如果是，在没有用户输入的情况下，不要超过该依赖点。
3. **提供选项** 使用 AskUserQuestion 提供选择：
   - 跳过此代理并将缺口记录在最终报告中
   - 使用更窄的范围重试
   - 在此处停止并首先解决阻止项
4. **始终生成部分报告** — 输出已完成的任何内容。永远不要因为一个代理被阻止而丢弃工作。

**常见阻止项**：
- 输入文件缺失（故事未找到，GDD 缺失）→ 重定向到创建它的技能
- ADR 状态是 Proposed → 不要实施；首先运行 `/architecture-decision`
- 范围太大 → 通过 `/create-stories` 拆分为两个故事
- ADR 和故事之间的指令冲突 → 表面冲突，不要猜测

---

## 阶段 8: 输出#

涵盖以下内容的摘要报告：
- QA 策略状态（已生成 / 需要修订）
- 测试计划状态（已写入 / 部分完成）
- 手动 QA 结果（PASS / FAIL / BLOCKED 计数）
- Bug 提交（已提交 ID 和严重性）
- 签署报告判定（APPROVED / APPROVED WITH CONDITIONS / NOT APPROVED）
- 任何未解决的问题#

判定：**完成** — QA 周期已完成并通过。
判定：**已阻止** — QA 周期已停止；表面阻止项及其阶段。

---

## 文件写入协议#

所有文件写入（QA 计划、测试用例、Bug 报告、签署报告）都委托给子代理和子技能（`/qa-plan`、`/bug-report`）。每个都强制使用"我可以写入 [路径]？"协议。此编排器不直接写入文件。

---

## 协作协议#

此技能遵循每个步骤的协作决策原则：

1. **问题 → 选项 → 决策 → 草稿 → 批准** 对于每个主要阶段
2. **在每个决策点使用 `AskUserQuestion`**（解释 → 捕获模式）：
   - 阶段 2："QA 策略已就绪。继续？"
   - 阶段 3："我可以写入测试计划吗？"
   - 阶段 4："测试用例已准备好。继续到执行？"
   - 阶段 5："手动 QA 已完成。继续到签署？"
   - 阶段 6："签署报告已就绪。写入？"
3. **"我可以写入 [文件路径] 吗？"** 在计划、测试用例、Bug、签署之前
4. **并行化** 当管道允许时（例如，阶段 4 测试用例编写可以并行运行）
5. **会话状态更新**：在每次主要阶段完成后#

**QA 负责人决策是关键**：APPROVED/WITH CONDITIONS/NOT APPROVED 判定必须是有意识的，并附有书面原理。

**冲突表面**：当签署冲突时（例如，手动 QA PASS 但自动化测试 FAIL），表面冲突并暂停。

**永远不要** 在没有用户批准的情况下自动签署。
**永远不要** 在没有冒烟检查通过的情况下继续到手动 QA。
**永远不要** 在 QA 周期完成之前关闭故事。

---

## 下一步#

- 如果签署报告是 APPROVED，运行 `/gate-check` 以验证是否可以进入下一阶段
- 如果任何 Bug 已提交，运行 `/dev-story` 以为修复创建故事
- 如果判定是 APPROVED WITH CONDITIONS，安排条件修复 before 发布
- 运行 `/regression-suite` 以验证已隔离测试仍然通过#

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文#

---

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
