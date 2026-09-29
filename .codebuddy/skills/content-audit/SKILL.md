---
name: content-audit
description: 内容审计 — 验证内容完整性，检测不一致
version: 0.3.0
category: game-development
whenToUse: >
  当需要内容审计技能时使用。
  处理验证内容完整性、检测不一致相关任务时。
  支持参数：无参数（全系统审计）、[system-name]（单个系统审计）、--summary（仅汇总表）
input:
  - 项目根目录路径（默认当前工作区）
  - 目标参数：无 / [system-name] / --summary
output:
  - 结构化结果报告（Markdown 格式）
  - docs/content-audit-[YYYY-MM-DD].md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 内容审计技能

## 技能概述

验证内容完整性，检测设计文档与实际实现之间的不一致。

## 使用方式

- 通过 Agent 触发：当用户说「内容审计」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill content-audit [参数]`

## 参数模式

- 无参数 → 全系统审计
- `[system-name]` → 仅审计指定系统
- `--summary` → 仅输出汇总表，不写入文件

---

## Phase 1 — 上下文收集

1. **读取 `design/gdd/systems-index.md`**，获取完整系统列表、类别和 MVP/优先级层级。

2. **L0 预扫描**：在完整读取任何 GDD 之前，搜索所有 GDD 文件的 `## Summary` 部分和常见内容计数关键词：
   ```
   search_content pattern="(## Summary|N enemies|N levels|N items|N abilities|enemy types|item types)" path="design/gdd/*.md"
   ```
   - 单个系统审计：跳过此步骤，直接完整读取。
   - 全系统审计：仅完整读取匹配内容计数关键词的 GDD。
   - 无内容计数语言的 GDD（纯机制 GDD）标记为"无审计内容计数"而不完整读取。

3. **完整读取范围内的 GDD 文件**（如果指定了系统名称，则仅读取该系统 GDD）。

4. **为每个 GDD 提取明确的内容计数或列表**。查找模式如：
   - "N enemies" / "enemy types:" / 命名敌人列表
   - "N levels" / "N areas" / "N maps" / "N stages"
   - "N items" / "N weapons" / "N equipment pieces"
   - "N abilities" / "N skills" / "N spells"
   - "N dialogue scenes" / "N conversations" / "N cutscenes"
   - "N quests" / "N missions" / "N objectives"
   - 任何明确的枚举列表（命名内容项的项目符号列表）

5. **从提取的数据构建内容清单表**：

   | System | Content Type | Specified Count/List | Source GDD |
   |--------|-------------|---------------------|------------|

   注意：如果 GDD 定性描述内容但未给出计数，记录为"未指定"并标记 — 未指定的计数是值得注意的设计差距。

---

## Phase 2 — 实现扫描

对于 Phase 1 中发现的每种内容类型，扫描相关目录以计数已实现的内容。使用 search_file 和 search_content 定位文件。

**关卡 / 区域 / 地图：**
- search_file pattern="*.tscn" / "*.unity" / "*.umap"
- 查找命名为 `levels/`, `areas/`, `maps/`, `worlds/`, `stages/` 的子目录中的场景文件
- 计数似乎是关卡/场景定义（非 UI 场景）的唯一文件

**敌人 / 角色 / NPC：**
- search_file pattern="*.json" / "*.tres" / "*.asset" / "*.yaml"
- 查找定义实体统计的数据文件
- 查找角色子目录中的场景/预制体文件

**物品 / 装备 / 战利品：**
- search_file pattern="*.json" / "*.tres" / "*.asset"
- 查找 `assets/data/**/items/**`, `assets/data/**/equipment/**`, `assets/data/**/loot/**`

**能力 / 技能 / 法术：**
- search_file pattern="*.json" / "*.tres" / "*.asset"
- 查找 `assets/data/**/abilities/**`, `assets/data/**/skills/**`, `assets/data/**/spells/**`

**对话 / 对话 / 过场动画：**
- search_file pattern="*.dialogue" / "*.csv" / "*.ink"
- 在 `assets/data/` 中查找对话数据文件

**任务 / 使命：**
- search_file pattern="*.json" / "*.yaml"
- 查找 `assets/data/**/quests/**`, `assets/data/**/missions/**`

**引擎特定说明（在报告中确认）：**
- 计数是近似值 — 此技能无法完美解析每种引擎格式或区分编辑器专用文件与发布内容
- 场景文件可能同时包含游戏内容和系统/UI 场景；扫描计数所有匹配项并注明此注意事项

---

## Phase 3 — 差距报告

生成差距表：

```
| System | Content Type | Specified | Found | Gap | Status |
|--------|-------------|-----------|-------|-----|--------|
```

**状态类别：**
- `COMPLETE` — Found ≥ Specified (100%+)
- `IN PROGRESS` — Found 是 Specified 的 50–99%
- `EARLY` — Found 是 Specified 的 1–49%
- `NOT STARTED` — Found 是 0

**优先级标志：**
如果满足以下条件，在报告中将系统标记为 `HIGH PRIORITY`：
- Status 是 `NOT STARTED` 或 `EARLY`，并且
- 系统在系统索引中标记为 MVP 或 Vertical Slice，或者
- 系统索引显示系统阻塞下游系统

**汇总行：**
- 指定的内容项总数（所有 Specified 列值之和）
- 找到的内容项总数（所有 Found 列值之和）
- 总体差距百分比：`(Specified - Found) / Specified * 100`

---

## Phase 4 — 输出

### 全审计和单系统模式

向用户展示差距表和汇总。询问："我可以将完整报告写入 `docs/content-audit-[YYYY-MM-DD].md` 吗？"

如果是，写入文件：

```markdown
# Content Audit — [Date]

## Summary
- **Total specified**: [N] content items across [M] systems
- **Total found**: [N]
- **Gap**: [N] items ([X%] unimplemented)
- **Scope**: [Full audit | System: name]

> 注意：计数基于文件扫描的近似值。
> 审计无法区分已发布内容与编辑器/测试资源。
> 建议对任何 HIGH PRIORITY 差距进行手动验证。

## Gap Table

| System | Content Type | Specified | Found | Gap | Status |
|--------|-------------|-----------|-------|-----|--------|

## HIGH PRIORITY Gaps

[List systems flagged HIGH PRIORITY with rationale]

## Per-System Breakdown

### [System Name]
- **GDD**: `design/gdd/[file].md`
- **Content types audited**: [list]
- **Notes**: [any caveats about scan accuracy for this system]

## Recommendation

Focus implementation effort on:
1. [Highest-gap HIGH PRIORITY system]
2. [Second system]
3. [Third system]

## Unspecified Content Counts

The following GDDs describe content without giving explicit counts.
Consider adding counts to improve auditability:
[List of GDDs and content types with "Unspecified"]
```

写入报告后，询问：

> "您想为任何内容差距创建待办事项吗？"

如果是：对于用户选择的每个系统，建议一个故事标题并指向 `/create-stories [epic-slug]` 或 `/quick-design`（取决于差距大小）。

### --summary 模式

直接将差距表和汇总打印到对话。不写入文件。
结束于："运行 `/content-audit`（无 `--summary`）以写入完整报告。"

---

## Phase 5 — 后续步骤

审计后，建议最高价值的后续行动：

- 如果任何系统标记为 `NOT STARTED` 且 MVP 标记 → "运行 `/design-system [name]` 以在实现开始前将缺失的内容计数添加到 GDD。"
- 如果总差距 >50% → "运行 `/sprint-plan` 以将内容工作分配到即将到来的 sprint。"
- 如果需要待办事项 → "为每个 HIGH PRIORITY 差距运行 `/create-stories [epic-slug]`。"
- 如果使用了 `--summary` → "运行 `/content-audit`（无标志）以将完整报告写入 `docs/`。"

结论：**COMPLETE** — 内容审计完成。

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
