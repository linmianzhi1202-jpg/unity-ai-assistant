---
name: skill-improve
description: 技能改进 — 基于测试反馈改进技能，提升提示词质量
version: 0.2.0
category: game-development
whenToUse: >
  需要基于测试反馈改进技能、提升提示词质量、运行技能改进循环、
  或根据静态/分类测试结果修复技能问题时，使用此技能。
  当用户提到「技能改进」「提示词优化」「技能迭代」等关键词时，应使用此技能。
input:
- 项目根目录路径（默认当前工作区）
- 技能名称参数（例如：tech-debt、gate-check）
output:
- 结构化改进报告（Markdown 格式）
- 修复前后的对比评分
- 改进后的技能文件
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
context: inline
---

# 技能改进技能

## 技能概述

对单个技能运行改进循环：测试 → 修复 → 重新测试 → 保留或还原。

此技能基于 `/skill-test` 的测试结果，自动诊断技能的问题并生成针对性修复，然后重新测试以验证改进效果。

**改进循环**： Phase 1（解析参数） → Phase 2（基线测试） → Phase 3（诊断） → Phase 4（提出修复） → Phase 5（写入并重新测试） → Phase 6（判定） → Phase 7（下一步）

---

## 使用方式

- **通过 Agent 触发**：当用户说「技能改进」或相关需求时，Agent 应自动加载此 Skill
- **手动触发**：`/skill skill-improve [技能名称]`
- **使用示例**：`/skill skill-improve tech-debt`

**参数要求**：必须提供技能名称。如果缺失，输出用法并停止：
```
用法：/skill-improve [技能名称]
示例：/skill-improve tech-debt
```

验证 `.codebuddy/skills/[name]/SKILL.md` 是否存在。如果不存在，停止并显示："未找到技能 '[name]'。"

---

## Phase 1：解析参数

从第一个参数读取技能名称。

如果缺失，输出用法并停止。

验证 `.codebuddy/skills/[name]/SKILL.md` 是否存在。如果不存在，停止并显示："未找到技能 '[name]'。"

---

## Phase 2：基线测试

运行 `/skill-test static [name]` 并记录基线评分：
- FAIL 计数
- WARN 计数
- 哪些具体检查失败（Check 1–7）

显示给用户：
```
静态基线：[N] 个失败，[M] 个警告
失败项：Check 4（无写前询问）、Check 5（无交接部分）
```

如果基线是 0 个 FAIL 和 0 个 WARN，注意它并继续到 Phase 2b。

### Phase 2b：分类基线

从 `CCGS Skill Testing Framework/catalog.yaml` 查找技能的 `category:` 字段。

如果未找到 `category:` 字段，显示：
"分类：尚未分配 — 跳过分类检查。"

并跳到 Phase 3。

如果找到分类，运行 `/skill-test category [name]` 并记录分类基线：
- FAIL 计数
- WARN 计数
- 哪些具体分类评分标准失败

显示给用户：
```
分类基线：[N] 个失败，[M] 个警告（[category] 评分标准）
```

如果静态和分类基线都是 0 个 FAIL 和 0 个 WARN，停止：
"此技能已通过所有静态和分类检查。无需改进。"

---

## Phase 3：诊断

读取 `.codebuddy/skills/[name]/SKILL.md` 的完整内容。

对于每个失败或警告的 **静态** 检查，识别确切的差距：

- **Check 1 失败** → 哪个 frontmatter 字段缺失
- **Check 2 失败** → 找到的阶段数 vs. 最低要求
- **Check 3 失败** → 技能主体中任何地方都没有判定关键词
- **Check 4 失败** → allowed-tools 中有 Write 或 Edit 但没有写前询问语言
- **Check 5 警告** → 结尾处无后续或下一步部分
- **Check 6 警告** → 设置了 `context: fork` 但找到的阶段少于 5 个
- **Check 7 警告** → argument-hint 为空或与记录的模式不匹配

对于每个失败或警告的 **分类** 检查（如果在 Phase 2b 中分配了分类），识别技能文本中的确切差距。例如：
- 如果 G2 失败（门模式，未生成完整指挥器）：技能主体从未引用所有 4 个 PHASE-GATE 指挥器提示
- 如果 A2 失败（创作，无每部分 May-I-write）：技能在结尾处询问一次，而不是在每部分写入之前
- 如果 T3 失败（团队，BLOCKED 未上报）：技能不会在依赖工作受阻时停止

在提出任何更改之前，向用户显示完整的组合诊断。

---

## Phase 4：提出修复

为每个失败和警告编写针对性修复。将提议的更改显示为清晰标记的 before/after 块。**仅更改失败的内容 — 不要重写通过的部分。**

询问："我可以将此改进版本写入 `.codebuddy/skills/[name]/SKILL.md` 吗？"

如果用户说否，在此处停止。

---

## Phase 5：写入并重新测试

记录技能文件的当前内容（用于必要时还原）。

将改进后的技能写入 `.codebuddy/skills/[name]/SKILL.md`。

重新运行 `/skill-test static [name]` 并记录新的静态评分。
如果分配了分类，也重新运行 `/skill-test category [name]` 并记录新的分类评分。

显示对比：
```
静态：   之前 [N] 个失败，[M] 个警告  →  之后 [N'] 个失败，[M'] 个警告
分类：  之前 [N] 个失败，[M] 个警告  →  之后 [N'] 个失败，[M'] 个警告（如适用）
组合更改：改进 / 无更改 / 更差
```

---

## Phase 6：判定

计算组合失败总数：静态 FAIL + 分类 FAIL + 静态 WARN + 分类 WARN。

**如果组合评分改进（组合失败计数低于基线）：**
报告："评分改进。更改已保留。"
显示每个维度的修复摘要。

**如果组合评分相同或更差：**
报告："组合评分未改进。"
显示更改内容以及为什么可能没有帮助。
询问："我可以使用 git checkout 还原 `.codebuddy/skills/[name]/SKILL.md` 吗？"
如果 yes：运行 `git checkout -- .codebuddy/skills/[name]/SKILL.md`

---

## Phase 7：下一步

- 运行 `/skill-test static all` 以找到下一个有失败的技能。
- 运行 `/skill-improve [next-name]` 以继续对另一个技能进行循环。
- 运行 `/skill-test audit` 以查看整体覆盖进度。

---

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
