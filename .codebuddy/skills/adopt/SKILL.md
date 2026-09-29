---
name: adopt
description: "采用 — 将现有项目迁移到本模板，改造项目"
version: 0.2.0
category: game-development
whenTUse: |
  当需要通过采用技能将现有项目迁移到本模板时使用。
  处理项目改造、格式合规性审计、生成迁移计划相关任务时。
  支持参数：无参数（完整审计）、gdds（仅GDD）、adrs（仅ADR）、stories（仅故事）。
input:
  - 项目根目录路径（默认当前工作区）
  - 审计模式参数：full / gdds / adrs / stories
output:
  - 采用审计结果（Markdown 格式）
  - docs/adoption-plan-[date].md 迁移计划文件
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 采用技能

## 技能概述

将现有项目迁移到本模板，改造项目，审计现有工件的格式合规性。

## 使用方式

- 通过 Agent 触发：当用户说「采用」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill adopt [参数]`

## 功能说明

此技能审计现有项目的工件 **格式合规性**与模板的技能管道，然后生成优先迁移计划。

**这与 `/project-stage-detect` 不同**：
- `/project-stage-detect` 回答：*存在什么？*
- `/adopt` 回答：*现有内容是否实际适用于模板的技能？*

一个项目可以有 GDD、ADR 和故事 — 但如果这些工件内部格式错误，每个对格式敏感的技能仍将静默失败或产生错误结果。

**输出：** `docs/adoption-plan-[date].md` — 一个持久的、可检查的迁移计划。

### 参数模式

**审计模式：** `$ARGUMENTS[0]`（空白 = `full`）：

- **无参数 / `full`**：完整审计 — 所有工件类型
- **`gdds`**：仅 GDD 格式合规性
- **`adrs`**：仅 ADR 格式合规性
- **`stories`**：仅故事格式合规性

**示例**：
```
/skill adopt
/skill adopt gdds
/skill adopt adrs
/skill adopt stories
```

## 工作流程

### 阶段 1：项目检测

1. 运行 `/project-stage-detect` 识别现有工件
2. 读取 `.codebuddy/` 目录结构
3. 识别已启用的 Rules/Skills/Agents
4. 输出：`ProjectState { artifacts, skills_enabled, gaps }`

### 阶段 2：格式合规性审计

对每个现有工件类型：

1. **GDD 审计**：
   - 检查 8 个必需章节是否存在
   - 检查公式格式是否正确
   - 检查边缘情况部分是否存在
   - 输出：`GddCompliance { file, missing_sections[], format_errors[] }`

2. **ADR 审计**：
   - 检查状态字段是否存在
   - 检查依赖关系部分是否存在
   - 检查引擎兼容性部分是否存在
   - 输出：`AdrCompliance { file, missing_fields[], risk_level }`

3. **故事审计**：
   - 检查故事格式（AS A User...）
   - 检查验收标准是否存在
   - 检查估算是否存在
   - 输出：`StoryCompliance { file, format_errors[], estimable }`

### 阶段 3：生成迁移计划

1. 按优先级排序差距：
   - **BLOCKING**：无法使用模板技能（缺少必需格式）
   - **HIGH**：可以工作但有警告
   - **MEDIUM**：改进但非必需

2. 生成迁移计划：`docs/adoption-plan-[date].md`
   - 摘要：项目状态、合规水平、估计工作量
   - 按优先级排序的迁移步骤
   - 每个步骤：操作、受影响文件、估计时间
   - 质量门控：每个步骤后的验证检查

3. 呈现计划给用户批准

### 阶段 4：执行迁移（可选）

1. 获得用户批准后，逐个执行迁移步骤
2. 每步后验证格式合规性
3. 更新迁移计划以标记完成的步骤
4. 输出最终报告：`MigrationReport { completed_steps, remaining_gaps, new_capabilities }`

## 输出格式

### 审计模式输出

```markdown
# 采用审计结果

## 项目状态
- 检测到工件：GDD (3), ADR (2), Stories (5)
- 启用技能：5/8
- 估计工作量：中等（4-6 小时）

## 格式合规性

### GDD 合规性
- `design/gdd/combat.md`：✅ 通过所有检查
- `design/gdd/progression.md`：⚠️ 缺少"公式"章节
- `design/gdd/character.md`：❌ 缺少 3 个必需章节

### ADR 合规性
- `architecture/adr-0001-event-system.md`：⚠️ 缺少"引擎兼容性"章节
- `architecture/adr-0002-save-system.md`：✅ 通过所有检查

## 迁移计划
生成：`docs/adoption-plan-2026-04-26.md`
```

### 迁移计划格式

```markdown
# 项目采用计划

**日期**：2026-04-26
**项目**：My Game Project
**估计工作量**：6 小时

## 差距分析

### BLOCKING（必须修复）
1. GDD 缺少必需章节（3 个文件）
2. ADR 缺少状态字段（2 个文件）

### HIGH（应该修复）
1. 故事格式不一致（2 个故事）
2. 缺少验收标准（3 个故事）

## 迁移步骤

### 步骤 1：修复 GDD 格式（估计：2 小时）
- **操作**：添加缺少的章节到 3 个 GDD 文件
- **受影响文件**：
  - `design/gdd/progression.md`
  - `design/gdd/character.md`
  - `design/gdd/level-design.md`
- **验证**：运行 `/design-review` 确认通过

### 步骤 2：修复 ADR 格式（估计：1 小时）
- **操作**：添加缺少的字段到 2 个 ADR 文件
- **受影响文件**：
  - `architecture/adr-0001-event-system.md`
  - `architecture/adr-0002-save-system.md`
- **验证**：运行 `/architecture-review` 确认通过

### 步骤 3：标准化故事格式（估计：2 小时）
- **操作**：重构 5 个故事以符合模板格式
- **验证**：运行 `/review` 确认质量

### 步骤 4：启用缺失技能（估计：1 小时）
- **操作**：启用 3 个缺失技能
- **技能**：`parity-audit`、`cost-tracker`、`context-compactor`
- **验证**：运行 `/status` 确认所有技能已启用

## 质量门控

每个步骤后：
- [ ] 格式合规性检查通过
- [ ] 模板技能可以成功运行
- [ ] 没有新的格式错误引入

## 完成标准

- [ ] 所有 GDD 文件通过 `/design-review`
- [ ] 所有 ADR 文件通过 `/architecture-review`
- [ ] 所有故事文件通过 `/review`
- [ ] 所有模板技能可以成功运行
- [ ] 生成的项目状态报告显示 100% 合规
```

## 协作协议

**你是协作顾问，不是自主执行器。** 用户做出所有决策；你提供专家指导。

### 问题优先工作流

在提出任何建议之前：

1. **提出澄清问题：**
   - 项目的当前状态是什么（原型、MVP、生产）？
   - 约束是什么（时间、资源、优先级）？
   - 用户想要完全迁移还是部分采用？
   - 哪些模板技能是优先的？

2. **提出 2-4 个选项及推理：**
   - 解释每个选项的优缺点
   - 参考模板架构和最佳实践
   - 将每个选项与用户陈述的目标对齐
   - 做出推荐，但明确将最终决策推迟给用户

3. **基于用户选择起草：**
   - 迭代地创建迁移计划（显示一个部分，获取反馈，优化）
   - 关于歧义进行询问而不是假设
   - 标记潜在问题或边缘情况以征求用户输入

4. **在编写文件之前获得批准：**
   - 显示完整草稿或摘要
   - 明确询问："我可以将其写入 [文件路径] 吗？"
   - 在使用 Write/Edit 工具之前等待"是"
   - 如果用户说"否"或"更改 X"，则迭代并返回步骤 3

### 协作心态

- 你是提供选项和推理的专家顾问
- 用户是做出最终决策的创意总监
- 当不确定时，询问而不是假设
- 解释 WHY 你推荐某事（理论、示例、模板对齐）
- 基于反馈迭代而没有防御性
- 当用户的修改改进你的建议时庆祝

## 质量检查

- [ ] 审计覆盖所有检测到的工件类型
- [ ] 格式合规性检查使用模板架构规则
- [ ] 迁移计划按优先级排序（BLOCKING → HIGH → MEDIUM）
- [ ] 每个迁移步骤都有估计时间和验证检查
- [ ] 输出使用结构化 Markdown 格式
- [ ] 所有建议都参考模板最佳实践

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `policy-executable` Rule 进行策略检查
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 清理格式（删除标题末尾多余的 #），更新版本号 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
