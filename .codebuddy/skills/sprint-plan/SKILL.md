---
name: sprint-plan
description: 迭代计划 — 规划冲刺，分配任务，设置冲刺目标
version: 0.2.0
category: game-development
whenToUse: >
  当用户需要规划冲刺、分配任务、设置冲刺目标、生成冲刺计划或检查冲刺状态时，使用此技能。
  支持 new、update、status 三种模式，包含生产者可行性门控和 QA 计划门控。
input:
- 项目根目录路径（默认当前工作区）
- 模式参数（new/update/status）
- 冲刺编号和日期范围
output:
- 结构化冲刺计划文档（Markdown 格式）
- sprint-status.yaml 机器可读状态文件
- 冲刺状态报告
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
context: inline
---

# 迭代计划技能

## 技能概述

规划冲刺，分配任务，设置冲刺目标。此技能生成冲刺计划文档、跟踪故事状态的 YAML 文件，并包含生产者可行性门控和 QA 计划门控。

## 使用方式

- 通过 Agent 触发：当用户说「迭代计划」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：```/skill sprint-plan [参数]```

**参数模式**：
- `new` — 创建新冲刺计划
- `update` — 更新现有冲刺计划
- `status` — 生成冲刺状态报告

---

## 阶段 0: 解析参数

提取模式参数（`new`、`update` 或 `status`）并解析审查模式（一次设置，用于存储此次运行的所有门生成）：

1. 如果传递了 `--review [full|lean|solo]` → 使用那个值
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认为 `lean`

有关完整的检查模式，请参见 `.claude/docs/director-gates.md`。

---

## 阶段 1: 收集上下文

1. **读取当前里程碑** 从 `production/milestones/`。

2. **读取之前的冲刺**（如果有）从 `production/sprints/` 以了解速度和结转。

3. **扫描设计文档** 在 `design/gdd/` 中寻找标记为准备好实施的功能。

4. **检查风险登记册** 在 `production/risk-register/`。

---

## 阶段 2: 生成输出

对于 `new`：

**生成冲刺计划** 遵循此格式并向用户展示。还不要询问写入——生产者可行性门控（阶段 4）首先运行，可能需要在写入文件之前进行修订。

```markdown
# 冲刺 [N] -- [开始日期] 到 [结束日期]

## 冲刺目标
[一句话描述此冲刺如何实现里程碑]

## 容量
- 总天数: [X]
- 缓冲（20%): [Y] 天保留用于计划外工作
- 可用: [Z] 天

## 任务

### 必须有（关键路径）
| ID | 任务 | 代理/负责人 | 预估天数 | 依赖项 | 验收标准 |
|----|------|-------------|-----------|-------------|-------------------|

### 应该有
| ID | 任务 | 代理/负责人 | 预估天数 | 依赖项 | 验收标准 |
|----|------|-------------|-----------|-------------|-------------------|

### 最好有
| ID | 任务 | 代理/负责人 | 预估天数 | 依赖项 | 验收标准 |
|----|------|-------------|-----------|-------------|-------------------|

## 从上一冲刺结转
| 任务 | 原因 | 新预估 |
|------|--------|-------------|

## 风险
| 风险 | 概率 | 影响 | 缓解措施 |
|------|------------|--------|------------|

## 外部因素依赖
- [列出任何外部依赖]

## 此冲刺的完成定义
- [ ] 所有"必须有"任务完成
- [ ] 所有任务通过验收标准
- [ ] QA 计划存在 (`production/qa/qa-plan-sprint-[N].md`)
- [ ] 所有逻辑/集成故事有通过的单元/集成测试
- [ ] 冒烟检查通过 (`/smoke-check sprint`)
- [ ] QA 签核报告：批准或附条件批准 (`/team-qa sprint`)
- [ ] 交付功能中没有 S1 或 S2 错误
- [ ] 任何偏差的设计文档已更新
- [ ] 代码审查并合并
```

对于 `status`：

**生成状态报告**：

```markdown
# 冲刺 [N] 状态 -- [日期]

## 进度: [X/Y 任务完成] ([Z%])

### 已完成
| 任务 | 完成者 | 备注 |
|------|-------------|-------|

### 进行中
| 任务 | 负责人 | 完成% | 阻塞项 |
|------|-------|--------|----------|

### 未开始
| 任务 | 负责人 | 有风险？ | 备注 |
|------|-------|----------|-------|

### 已阻塞
| 任务 | 阻塞项 | 阻塞项负责人 | 预计解决时间 |
|------|---------|-----------------|-----|

## 燃尽评估
[按计划 / 落后 / 提前]
[如果落后：正在削减或延迟什么]

## 新出现的风险
- [此冲刺中识别的任何新风险]
```

---

## 阶段 3: 写入冲刺状态文件

生成新冲刺计划后，还要写入 `production/sprint-status.yaml`。
这是故事状态的机器可读事实来源——由 `/sprint-status`、`/story-done` 和 `/help` 读取，无需 Markdown 解析。

询问："我还可以写入 `production/sprint-status.yaml` 来跟踪故事状态吗？"

格式：

```yaml
# 由 /sprint-plan 自动生成。通过 /story-done 更新。
# 不要手动编辑——使用 /story-done 更新故事状态。

sprint: [N]
goal: "[冲刺目标]"
start: "[YYYY-MM-DD]"
end: "[YYYY-MM-DD]"
generated: "[YYYY-MM-DD]"
updated: "[YYYY-MM-DD]"

stories:
  - id: "[epic-story, 例如 1-1]"
    name: "[故事名称]"
    file: "[production/stories/path.md]"
    priority: must-have        # must-have | should-have | nice-to-have
    status: ready-for-dev      # backlog | ready-for-dev | in-progress | review | done | blocked
    owner: ""
    estimate_days: 0
    blocker: ""
    completed: ""
```

从冲刺计划的任务表初始化每个故事：
- 必须有任务 → `priority: must-have`, `status: ready-for-dev`
- 应该有任务 → `priority: should-have`, `status: backlog`
- 最好有任务 → `priority: nice-to-have`, `status: backlog`

对于 `update`：读取现有 `sprint-status.yaml`，结转未更改故事的状态，添加新故事，移除丢弃的故事。

---

## 阶段 4: 生产者可行性门控

**审查模式检查**——在生成 PR-SPRINT 之前应用：
- `solo` → 跳过。注意："PR-SPRINT 已跳过——单人模式。"继续到阶段 5（QA 计划门控）。
- `lean` → 跳过（不是 PHASE-GATE）。注意："PR-SPRINT 已跳过——精简模式。"继续到阶段 5（QA 计划门控）。
- `full` → 正常生成。

在最终确定冲刺计划之前，通过 Task 使用门控 **PR-SPRINT**（`.claude/docs/director-gates.md`）生成 `producer`。

传递：提议的故事列表（标题、预估、依赖项）、团队总容量（小时/天）、上一冲刺的任何结转、里程碑约束和截止日期。

展示生产者的评估。如果 UNREALISTIC，在询问写入批准之前修订故事选择（将故事推迟到应该有或最好有）。如果 CONCERNS，提出它们并让用户决定是否调整。

处理生产者的判定后，询问："我可以将此冲刺计划写入 `production/sprints/sprint-[N].md` 吗？"如果是，写入文件，根据需要创建目录。判定：**完成**——冲刺计划已创建。如果否：判定：**已阻塞**——用户拒绝写入。

写入后，添加：

> **范围检查：** 如果此冲刺包含超出原始史诗范围添加的故事，在实现开始之前运行 `/scope-check [epic]` 以检测范围蠕变。

---

## 阶段 5: QA 计划门控

在关闭冲刺计划之前，检查此冲刺是否存在 QA 计划。

使用 `Glob` 查找 `production/qa/qa-plan-sprint-[N].md` 或 `production/qa/` 中引用此冲刺编号的任何文件。

**如果找到 QA 计划**：在冲刺计划输出中注意它——"QA 计划：`[路径]`"——然后继续。

**如果不存在 QA 计划**：不要静默继续。明确提出此问题：

> "此冲刺没有 QA 计划。没有 QA 计划的冲刺计划意味着测试要求未定义——开发者不会知道从 QA 角度来看'完成'是什么样子，并且没有 QA 计划就无法通过生产 → 抛光门控。
>
> 现在运行 `/qa-plan sprint`，在开始任何实施之前。它需要一个会话并为每个故事生成测试用例要求。"

使用 `AskUserQuestion`：
- 提示："未找到此冲刺的 QA 计划。您希望如何继续？"
- 选项：
  - `[A] 现在运行 /qa-plan sprint——我会在开始实施之前做那个（推荐）`
  - `[B] 暂时跳过——我理解 QA 签核将在生产 → 抛光门控处被阻塞`

如果 [A]：以"冲刺计划已写入。接下来运行 `/qa-plan sprint`——然后开始实施。"结束
如果 [B]：向冲刺计划文档添加警告块：

```markdown
> ⚠️ **无 QA 计划**：此冲刺在没有 QA 计划的情况下启动。在最后一个故事实施之前运行 `/qa-plan sprint`
> 生产 → 抛光门控需要 QA
> 签核报告，这需要 QA 计划。
```

---

## 阶段 6: 后续步骤

在冲刺计划写入且 QA 计划状态解决后：

- `/qa-plan sprint` — **开始实施之前需要**——为每个故事定义测试用例，以便开发者根据 QA 规范实施，而不是白板
- `/story-readiness [story-file]` — 在开始之前验证故事已准备好
- `/dev-story [story-file]` — 开始实施第一个故事
- `/sprint-status` — 在冲刺中期检查进度
- `/scope-check [epic]` — 在实施开始之前验证没有范围蠕变

---

## 协作协议

- **审查模式影响门控**——`solo` 和 `lean` 模式跳过 PR-SPRINT 生成；只有 `full` 模式运行生产者可行性门控
- **在写入之前始终询问**——冲刺计划和 sprint-status.yaml 都需要明确的用户批准
- **QA 计划门控是强制性的**——没有 QA 计划的冲刺计划会向开发者发出关于未完成定义的警告
- **范围检查是可选的但推荐的**——在添加的故事超出原始史诗范围时运行 `/scope-check [epic]`

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
