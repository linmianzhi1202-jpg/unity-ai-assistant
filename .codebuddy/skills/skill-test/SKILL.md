---
name: skill-test
description: 技能测试 — 验证自定义技能，确保正确执行
version: 0.2.0
category: game-development
whenToUse: >
  需要使用技能测试技能验证自定义技能、确保正确执行、运行结构合规性检查、
  或执行行为正确性验证时，使用此技能。
  支持四种模式：static（结构检查）、spec（行为规范）、category（分类评估）、audit（覆盖报告）。
input:
- 项目根目录路径（默认当前工作区）
- 技能名称、模式参数（static/spec/category/audit）
output:
- 结构化测试结果报告（Markdown 格式）
- 合规性检查清单
- 覆盖报告（audit 模式）
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
context: inline
---

# 技能测试技能

## 技能概述

验证 `.codebuddy/skills/*/SKILL.md` 文件的结构合规性和行为正确性。无外部依赖 — 完全在现有技能/钩子/模板架构内运行。

**四种模式：**

| 模式 | 命令 | 目的 | Token 成本 |
|------|---------|---------|------------|
| `static` | `/skill-test static [name\|all]` | 结构检查器 — 每个技能 7 项合规性检查 | 低（约 1k/技能） |
| `spec` | `/skill-test spec [name]` | 行为验证器 — 评估测试规范中的断言 | 中（约 5k/技能） |
| `category` | `/skill-test category [name\|all]` | 分类评分标准 — 根据技能的分类特定指标检查技能 | 低（约 2k/技能） |
| `audit` | `/skill-test audit` | 覆盖报告 — 技能、代理规范、最后测试日期 | 低（约 3k 总计） |

---

## 阶段 1：解析参数

从第一个参数确定模式：

- `static [name]` → 对一个技能运行 7 项结构检查
- `static all` → 对所有技能（Glob `.codebuddy/skills/*/SKILL.md`）运行 7 项结构检查
- `spec [name]` → 读取技能和测试规范，评估断言
- `category [name]` → 从 `CCGS Skill Testing Framework/quality-rubric.md` 运行分类特定评分标准
- `category all` → 对每个在目录中有 `category:` 的技能运行分类评分标准
- `audit`（或无参数）→ 读取目录，列出所有技能和代理，显示覆盖情况

如果参数缺失或无法识别，输出用法并停止。

---

## 阶段 2A：静态模式 — 结构检查器

对于每个被测试的技能，完整读取其 `SKILL.md` 并运行所有 7 项检查：

### 检查 1 — 必需的 Frontmatter 字段

文件必须包含所有这些 YAML frontmatter 块中的字段：
- `name:`
- `description:`
- `argument-hint:`
- `user-invocable:`
- `allowed-tools:`

**失败** 如果任何字段缺失。

### 检查 2 — 多个阶段

技能必须 ≥2 个编号阶段标题。查找模式如：
- `## Phase N` 或 `## Phase N:`
- `## N.`（编号的顶级部分）
- 如果阶段未明确编号，至少 2 个不同的 `##` 标题

**失败** 如果找到的阶段式标题少于 2 个。

### 检查 3 — 判定关键词

技能必须包含至少一个：`PASS`、`FAIL`、`CONCERNS`、`APPROVED`、`BLOCKED`、`COMPLETE`、`READY`、`COMPLIANT`、`NON-COMPLIANT`

**失败** 如果没有出现这些词。

### 检查 4 — 协作协议语言

技能必须包含写前询问语言。查找：
- `"May I write"`（规范形式）
- `"before writing"` 或 `"approval"` 靠近文件写入指令
- `"ask"` + `"write"` 在接近的位置（在同一部分）

**警告** 如果缺失（一些只读技能可以跳过这个）。
**失败** 如果 `allowed-tools` 包含 `Write` 或 `Edit` 但未找到写前询问语言。

### 检查 5 — 下一步交接

技能必须以推荐的下一步行动或后续路径结束。查找：
- 提到另一个技能的最后部分（例如 `/story-done`、`/gate-check`）
- "Recommended next" 或 "next step" 措辞
- "Follow-Up" 或 "After this" 部分

**警告** 如果缺失。

### 检查 6 — Fork 上下文复杂性

如果 frontmatter 包含 `context: fork`，技能应该有 ≥5 个阶段标题（`##` 级别或编号的 Phase N 标题）。Fork 上下文用于复杂的多阶段技能；简单技能不应使用它。

**警告** 如果设置了 `context: fork` 但找到的阶段少于 5 个。

### 检查 7 — 参数提示合理性

`argument-hint` 必须非空。如果技能主体提到多种模式（例如 "Mode A | Mode B"），提示应该反映它们。交叉引用提示与第一阶段中的 "Parse Arguments" 部分。

**警告** 如果提示为 `""` 或如果记录的模式与提示不匹配。

---

### 静态模式输出格式

对于单个技能：
```
=== Skill Static Check: /[name] ===

Check 1 — Frontmatter Fields:    PASS
Check 2 — Multiple Phases:       PASS (7 phases found)
Check 3 — Verdict Keywords:      PASS (PASS, FAIL, CONCERNS)
Check 4 — Collaborative Protocol: PASS ("May I write" found)
Check 5 — Next-Step Handoff:     WARN (no follow-up section found)
Check 6 — Fork Context Complexity: PASS (8 phases, context: fork set)
Check 7 — Argument Hint:         PASS

Verdict: WARNINGS (1 warning, 0 failures)
Recommended: Add a "Follow-Up Actions" section at the end of the skill.
```

对于 `static all`，生成汇总表然后列出任何不合规的技能：
```
=== Skill Static Check: All 52 Skills ===

Skill                  | Result       | Issues
-----------------------|--------------|-------
gate-check             | COMPLIANT    |
design-review          | COMPLIANT    |
story-readiness        | WARNINGS     | Check 5: no handoff
...

Summary: 48 COMPLIANT, 3 WARNINGS, 1 NON-COMPLIANT
Aggregate Verdict: N WARNINGS / N FAILURES
```

---

## 阶段 2B：规范模式 — 行为验证器

### 步骤 1 — 定位文件

在 `.codebuddy/skills/[name]/SKILL.md` 找到技能。
从 `CCGS Skill Testing Framework/catalog.yaml` 查找规范路径 — 使用匹配技能条目的 `spec:` 字段。

如果任一缺失：
- 缺失技能："在 `.codebuddy/skills/` 中未找到技能 '[name]'。"
- 目录中缺失规范路径："在 catalog.yaml 中未设置 '[name]' 的规范路径。"
- 在路径未找到规范文件："在 [path] 缺失规范文件。运行 `/skill-test audit` 查看覆盖差距。"

### 步骤 2 — 读取两个文件

完整读取技能文件和测试规范文件。

### 步骤 3 — 评估断言

对于规范中的每个 **测试用例**：

1. 读取 **Fixture** 描述（假定项目文件状态）
2. 读取 **Expected behavior** 步骤
3. 读取每个 **Assertion** 复选框

对于每个断言，评估如果给定 Fixture 状态正确遵循技能书面的指令，是否会满足它。这是一个 Claude 评估的推理检查，不是代码执行。

标记每个断言：
- **PASS** — 技能指令清楚满足此断言
- **PARTIAL** — 技能指令部分解决它，但有歧义
- **FAIL** — 给定 Fixture，技能指令将不会满足此断言

对于 **Protocol Compliance** 断言（始终存在）：
- 检查技能在文件写入前是否要求 "May I write"
- 检查技能是否在请求批准前呈现发现
- 检查技能是否以避免在未批准的情况下自动创建文件结束

### 步骤 4 — 构建报告

```
=== Skill Spec Test: /[name] ===
Date: [date]
Spec: CCGS Skill Testing Framework/skills/[category]/[name].md

Case 1: [Happy Path — name]
  Fixture: [summary]
  Assertions:
    [PASS] [assertion text]
    [FAIL] [assertion text]
       Reason: The skill's Phase 3 says "..." but the fixture state means "..."
  Case Verdict: FAIL

Case 2: [Edge Case — name]
  ...
  Case Verdict: PASS

Protocol Compliance:
  [PASS] Uses "May I write" before file writes
  [PASS] Presents findings before asking approval
  [WARN] No explicit next-step handoff at end

Overall Verdict: FAIL (1 case failed, 1 warning)
```

### 步骤 5 — 提供写入结果

"我可以将这些结果写入 `CCGS Skill Testing Framework/results/skill-test-spec-[name]-[date].md` 并更新 `CCGS Skill Testing Framework/catalog.yaml` 吗？"

如果 yes：
- 将结果文件写入 `CCGS Skill Testing Framework/results/`
- 更新技能在 `CCGS Skill Testing Framework/catalog.yaml` 中的条目：
  - `last_spec: [date]`
  - `last_spec_result: PASS|PARTIAL|FAIL`

---

## 阶段 2D：分类模式 — 评分标准评估

### 步骤 1 — 定位技能和分类

在 `.codebuddy/skills/[name]/SKILL.md` 找到技能。
从 `CCGS Skill Testing Framework/catalog.yaml` 查找 `category:` 字段。

如果未找到技能："未找到技能 '[name]'。"
如果无 `category:` 字段："在 catalog.yaml 中未为 '[name]' 分配分类。首先将 `category: [name]` 添加到技能条目。"
对于 `category all`：收集所有带有 `category:` 字段的技能并处理每个。

`category: utility` 技能仅根据 U1（静态检查通过）和 U2（门模式正确，如果适用）评估 — 跳过 U3-U5。

### 步骤 2 — 读取评分标准部分

读取 `CCGS Skill Testing Framework/quality-rubric.md`。
提取匹配技能分类的部分（例如 `### gate`、`### team`）。

### 步骤 3 — 读取技能

完整读取技能的 `SKILL.md`。

### 步骤 4 — 评估评分标准指标

对于分类的评分标准表中的每个指标：
1. 检查技能的书面的指令是否清楚满足标准
2. 标记 PASS、FAIL 或 WARN
3. 对于 FAIL/WARN，识别技能文本中的确切差距（引用相关部分或注意其缺失）

### 步骤 5 — 输出报告

```
=== Skill Category Check: /[name] ([category]) ===

Metric G1 — Review mode read:      PASS
Metric G2 — Full mode directors:   FAIL
  Gap: Phase 3 spawns only CD-PHASE-GATE; TD-PHASE-GATE, PR-PHASE-GATE, AD-PHASE-GATE absent
Metric G3 — Lean mode: PHASE-GATE only: PASS
Metric G4 — Solo mode: no directors:    PASS
Metric G5 — No auto-advance:       PASS

Verdict: FAIL (1 failure, 0 warnings)
Fix: Add TD-PHASE-GATE, PR-PHASE-GATE, and AD-PHASE-GATE to the full-mode director
     panel in Phase 3.
```

### 步骤 6 — 提供更新目录

"我可以更新 `CCGS Skill Testing Framework/catalog.yaml` 以为 [name] 记录此分类检查（`last_category`、`last_category_result`）吗？"

---

## 阶段 2C：审计模式 — 覆盖报告

### 步骤 1 — 读取目录

读取 `CCGS Skill Testing Framework/catalog.yaml`。如果缺失，注意目录尚不存在（首次运行状态）。

### 步骤 2 — 枚举所有技能和代理

Glob `.codebuddy/skills/*/SKILL.md` 以获取完整的技能列表。
从每个路径提取技能名称（目录名称）。

同时读取 `CCGS Skill Testing Framework/catalog.yaml` 中的 `agents:` 部分以获取完整的代理列表。

### 步骤 3 — 构建技能覆盖表

对于每个技能：
- 检查规范文件是否存在（使用目录中的 `spec:` 路径，或 Glob `CCGS Skill Testing Framework/skills/*/[name].md`）
- 从目录查找 `last_static`、`last_static_result`、`last_spec`、`last_spec_result`、`last_category`、`last_category_result`、`category`（或如果不在目录中则标记为 "never" / "—"）
- 优先级来自目录 `priority:` 字段（critical/high/medium/low）

### 步骤 3b — 构建代理覆盖表

对于目录 `agents:` 部分中的每个代理：
- 检查规范文件是否存在（使用目录中的 `spec:` 路径，或 Glob `CCGS Skill Testing Framework/agents/*/[name].md`）
- 从目录查找 `last_spec`、`last_spec_result`、`category`

### 步骤 4 — 输出报告

```
=== Skill Test Coverage Audit ===
Date: [date]

SKILLS (72 total)
Specs written: 72 (100%) | Never static tested: 72 | Never category tested: 72

Skill                  | Cat      | Has Spec | Last Static | S.Result | Last Cat | C.Result | Priority
-----------------------|----------|----------|-------------|----------|----------|----------|----------
gate-check             | gate     | YES      | never       | —        | never    | —        | critical
design-review          | review   | YES      | never       | —        | never    | —        | critical
...

AGENTS (49 total)
Agent specs written: 49 (100%)

Agent                  | Category   | Has Spec | Last Spec   | Result
-----------------------|------------|----------|-------------|--------
creative-director      | director   | YES      | never       | —
technical-director     | director   | YES      | never       | —
...

Top 5 Priority Gaps (skills with no spec, critical/high priority):
(none if all specs are written)

Skill coverage:  72/72 specs (100%)
Agent coverage:  49/49 specs (100%)
```

审计模式中不写入文件。

提供："您想运行 `/skill-test static all` 以检查所有技能的结构合规性吗？`/skill-test category all` 以运行分类评分标准检查？或 `/skill-test spec [name]` 以运行特定行为测试？"

---

## 阶段 3：推荐的下一步

在任何模式完成后，提供上下文后续行动：

- 在 `static [name]` 后："如果测试规范存在，运行 `/skill-test spec [name]` 以验证行为正确性。"
- 在带有失败的 `static all` 后："首先解决 NON-COMPLIANT 技能。运行 `/skill-test static [name]`  individually 以获取详细的修复指导。"
- 在 `spec [name]` PASS 后："更新 `CCGS Skill Testing Framework/catalog.yaml` 以记录此次通过日期。考虑运行 `/skill-test audit` 以找到下一个规范差距。"
- 在 `spec [name]` FAIL 后："审查失败的断言并更新技能或测试规范以解决不匹配。"
- 在 `audit` 后："从关键优先级差距开始。使用 `CCGS Skill Testing Framework/templates/skill-test-spec.md` 的规范模板创建新规范。"

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：

- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 修复 whenToUse 格式；删除原始英文提示词；完全中文化；升级版本号 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
