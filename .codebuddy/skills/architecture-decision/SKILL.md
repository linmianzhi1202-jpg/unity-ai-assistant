---
name: architecture-decision
description: "架构决策 — 编写 ADR，记录架构决策"
version: 0.2.0
category: game-development
whenTUse: |
  当需要通过架构决策技能编写 ADR 时使用。
  处理记录架构决策、建立追溯性矩阵、确保架构一致性相关任务时。
  支持参数：无参数（新建 ADR）、retrofit [path]（改造现有 ADR）、coverage（追溯性）、consistency（一致性）、engine（引擎兼容性）、rtm（追溯性矩阵）。
input:
  - 项目根目录路径（默认当前工作区）
  - 操作参数：无 / retrofit [path] / coverage / consistency / engine / single-gdd [path] / rtm
output:
  - ADR 文件（architecture/adr-NNN-[slug].md）
  - 追溯性矩阵（Markdown 表格）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 架构决策技能

## 技能概述

编写 ADR（架构决策记录），记录架构决策和权衡，建立决策追溯性矩阵。

## 使用方式

- 通过 Agent 触发：当用户说「架构决策」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill architecture-decision [参数]`

## 功能说明

当此技能被调用时：

### 0. 解析参数 — 检测 Retrofit 模式

解析审查模式（一次，为此运行的所有门控生成）：

1. 如果传递了 `--review [full|lean|solo]` → 使用那个
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认到 `lean`

参见 `.claude/docs/director-gates.md` 获取完整检查模式。

**如果参数以 `retrofit` 后跟文件路径开头**
（例如，`/architecture-decision retrofit docs/architecture/adr-0001-event-system.md`）：

进入 **retrofit 模式**：

1. 完全读取现有 ADR 文件。
2. 通过扫描标题识别哪些模板章节存在：
   - `## Status` — **BLOCKING 如果缺少**：`/story-readiness` 无法检查 ADR 验收
   - `## ADR Dependencies` — HIGH 如果缺少：依赖排序中断
   - `## Engine Compatibility` — HIGH 如果缺少：post-cutoff 风险未知
   - `## GDD Requirements Addressed` — MEDIUM 如果缺少：追溯性丢失
3. 呈现给用户：
   - ✅ 存在的章节
   - ⚠️ 缺少的章节（标记严重性）
   - 📋 建议：添加缺少的章节以符合模板
4. 在写入更改之前获得批准。

### 1. 检测上下文

1. 检查 `architecture/adr-index.md` 是否存在。
2. 读取 `.claude/settings.json` 中的 `active_addrs`。
3. 如果没有活动 ADR，建议创建一个新 ADR（使用 `AskUserQuestion`）。
4. 如果多个 ADR 存在，让用户选择一个。

### 2. 加载 ADR 模板

1. 读取 `.codebuddy/templates/adr-template.md`。
2. 如果不存在，使用内部默认模板。
3. 识别必需章节：`## Status`、`## Context`、`## Decision`、`## Consequences`。

### 3. 引导决策

使用 **问题优先工作流**：

1. **提出澄清问题：**
   - "决策的上下文是什么？"
   - "涉及哪些利益相关者？"
   - "有哪些备选方案？"
   - "决策的限制是什么？"

2. **提出 2-4 个选项及推理：**
   - 解释每个选项的优缺点
   - 参考架构模式（MVC、ECS、微服务等）
   - 将每个选项与项目支柱对齐
   - 做出推荐，但明确将最终决策推迟给用户

3. **起草 ADR：**
   - 一次一个章节
   - 显示草稿给用户
   - 获得批准后再继续

### 4. 写入 ADR

1. 使用批准的决策创建新 ADR 文件：`architecture/adr-NNN-[slug].md`
2. 更新 `adr-index.md` 以包含新 ADR
3. 更新 `.claude/settings.json` 中的 `active_addrs`
4. 显示确认给用户。

## 参数模式

**审查模式：** `$ARGUMENTS[0]`（空白 = `full`）：

- **无参数 / `full`**：完整审查 — 所有 ADR
- **`coverage`**：仅追溯性 — 哪些 GDD 需求没有 ADR
- **`consistency`**：仅跨 ADR 冲突检测
- **`engine`**：仅引擎兼容性审计
- **`single-gdd [path]`**：审查一个特定 GDD 的架构覆盖
- **`rtm`**：需求追溯性矩阵 — 扩展标准矩阵以包含故事文件路径和测试文件路径；输出 Markdown 表格

## 输出格式

### ADR 模板

```markdown
# ADR-NNN: [Title]

## Status

[Proposed | Accepted | Deprecated | Superseded]

## Context

[问题的描述，驱动因素，限制]

## Decision

[做出的决策，理由]

## Consequences

[正面和负面影响]

## ADR Dependencies

- ADR-NNN: [相关决策]
- ADR-NNN: [相关决策]

## Engine Compatibility

- Engine: [Unity | Unreal | Godot]
- Version: [x.x.x]
- Compatibility Notes: [任何警告]

## GDD Requirements Addressed

- [GDD 需求 ID 和描述]
```

### 追溯性矩阵

```markdown
# 架构追溯性矩阵#

**生成者**：`/architecture-decision rtm`
**用途**：将每个 GDD 技术需求映射到 ADR，识别覆盖差距

| GDD 需求 ID | GDD 文件 | 技术需求 | ADR | 状态 | 故事文件 | 测试文件 |
|------------|----------|------------|-----|------|------------|------------|
| REQ-001 | gdd-combat.md | 战斗系统架构 | ADR-0001 | ✅ 已覆盖 | stories/combat-001.md | tests/combat-tests.md |
| REQ-002 | gdd-progression.md | 进度系统 | ADR-0002 | ⚠️ 部分覆盖 | - | - |
| REQ-003 | gdd-ai.md | AI 行为树 | - | ❌ 未覆盖 | - | - |
```

## 质量检查

- [ ] ADR 有所有 4 个必需章节
- [ ] 决策有清晰的理由
- [ ] 后果包括正面和负面影响
- [ ] 追溯性矩阵完整（如果使用了 `rtm`）
- [ ] 所有 GDD 需求都有 ADR 覆盖
- [ ] 引擎兼容性已记录

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `policy-executable` Rule 进行策略检查
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 清理格式（删除多余的反引号和 # 符号），更新版本号 |
| 0.1.0 | 2026-04-27 | 从 Claude Code Game Studios 迁移并中文化 |
