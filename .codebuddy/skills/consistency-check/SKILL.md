---
name: consistency-check
description: 一致性检查 — 验证跨文档/代码一致性，检测冲突
version: 0.3.0
category: game-development
whenToUse: >
  当需要一致性检查技能时使用。
  验证跨文档/代码一致性，检测冲突。
  生成一致性报告。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标参数（根据技能不同）
output:
  - 结构化结果报告（Markdown 格式）
  - 相关文件生成（根据技能不同）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 一致性检查技能

## 技能概述

验证跨文档/代码一致性，检测冲突。

## 使用方式

- 通过 Agent 触发：当用户说「一致性检查」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill consistency-check [参数]`

## 功能说明

通过比较所有 GDD 与实体注册表（`design/registry/entities.yaml`）来检测跨文档不一致。使用 search_content 优先方法：
- 读取注册表一次，然后仅针对 mention 已注册名称的 GDD 部分 — 除非冲突需要调查，否则不读取完整文档。

**此技能是写入时安全网。** 它捕获 `/design-system`'s 逐节检查可能遗漏的内容，以及 `/review-all-gdds`'s 整体审查捕获太晚的内容。

**何时运行：**
- 在编写每个新 GDD 之后（在转到下一个系统之前）
- 在 `/review-all-gdds` 之前（以便该技能以干净的基线开始）
- 在 `/create-architecture` 之前（不一致会毒化下游 ADR）

**输出：** `design/consistency-report-[date].md` — 持久的一致性报告。

### 参数模式

**模式：**

- `/consistency-check full` — 检查所有已注册条目与所有 GDD
- `/consistency-check since-last-review` — 仅检查自上次审查报告以来修改的 GDD
- `/consistency-check entity:<name>` — 在所有 GDD 中检查一个特定实体
- `/consistency-check item:<name>` — 在所有 GDD 中检查一个特定项目（物品/能力等）
- 无参数 — 如果存在当前 sprint，则运行 sprint 模式，否则为 full 模式

---

## 工作流程

### 阶段 1：解析参数并加载注册表

#### 步骤 1a — 发现注册表文件

搜索注册表文件：

1. `design/registry/entities.yaml` — 首选格式
2. `design/registry/entities.json` — 替代格式
3. `docs/entity-registry.md` — 回退格式

如果未找到注册表文件：
> "实体注册表为空。运行 `/design-system` 以写入 GDD — 注册表在每个 GDD 完成后自动填充。还没有可检查的内容。"

**停止** 并且如果没有 exit 则不继续。

#### 步骤 1b — 解析每个条目

对于每个注册表条目：

1. **提取**：`name`, `source`, `attributes`, `referenced_by`
2. **构建查找表**：
   - `entity_map`: `{ name → { source, attributes, referenced_by } }`
   - `attribute_registry`: `{ attribute_name → [entity_names] }`
   - `reference_graph`: `{ source_doc → [referencing_docs] }`
3. **输出**：`RegistryData { entities[], lookup_tables }`

### 阶段 2：跨文档一致性检查

对于每个已注册的实体：

#### 检查 2a：属性一致性

1. 在源 GDD 中读取实体定义
2. 在所有引用文档中搜索属性引用
3. 标识：
   - **缺失属性**：文档引用实体但使用源中未定义的属性
   - **类型不匹配**：文档假设属性类型与源不同
   - **范围冲突**：文档为属性分配的值超出源中定义的范围
4. **输出**：`PropertyConsistency { entity, issues[] }`

#### 检查 2b：关系一致性

1. 在源 GDD 中读取 `## Relationships` 部分
2. 在所有引用文档中验证关系
3. 标识：
   - **孤立实体**：已注册但未被任何文档引用的实体
   - **孤儿引用**：文档引用实体但实体未注册
   - **循环依赖**：A 引用 B，B 引用 A（设计问题）
4. **输出**：`RelationshipConsistency { entity, orphans[], cycles[] }`

#### 检查 2c：公式一致性

1. 在源 GDD 中读取公式（如果有）
2. 在所有引用文档中验证公式使用
3. 标识：
   - **公式参数不匹配**：文档使用公式但参数计数或名称不同
   - **输出格式不一致**：公式输出格式在文档之间不匹配
4. **输出**：`FormulaConsistency { formula_id, usage[] }`

---

## 输出格式

### 一致性报告

```markdown
# 一致性检查报告

**日期**：2026-04-27
**模式**：full
**检查的实体**：12

## 摘要

- **检查的实体**：12
- **通过**：8 (66.7%)
- **失败**：4 (33.3%)

## 属性一致性

### ❌ 失败 (4 个实体)

1. **玩家实体** (`design/gdd/combat.md`)
   - ❌ 属性 `mana` 在 `design/gdd/magic.md` 中引用但源中未定义
   - ❌ 属性 `health` 类型不匹配：源说 `float`，`design/gdd/combat.md` 假设 `int`

2. **敌人实体** (`design/gdd/enemy.md`)
   - ❌ 属性 `attack_power` 在 `design/gdd/combat.md` 中引用但源中未定义

## 关系一致性

### ❌ 孤立实体 (2 个)

1. **物品实体** — 已注册但未被任何文档引用
2. **NPC 实体** — 已注册但未被任何文档引用

### ❌ 孤儿引用 (1 个)

1. **Boss 实体** — `design/gdd/boss.md` 引用但实体未注册

## 公式一致性

### ❌ 公式参数不匹配 (1 个)

1. **伤害公式** (`design/gdd/combat.md`)
   - 公式 `calculate_damage` 在 `design/gdd/magic.md` 中使用但参数计数不同

## 建议

### 高优先级（必须修复）

1. 将缺失属性添加到源 GDD
2. 修复类型不匹配的属性
3. 注册孤儿引用

### 中优先级（应该修复）

1. 为孤立实体添加引用或取消注册
2. 标准化公式参数
```

---

## 质量检查

- [ ] 检查覆盖注册表中的所有已注册实体
- [ ] 属性一致性检查使用源 GDD 作为真相来源
- [ ] 关系一致性检查标识孤立和孤儿
- [ ] 公式一致性检查验证参数和输出格式
- [ ] 建议按优先级排序（HIGH → MEDIUM → LOW）
- [ ] 输出使用结构化 Markdown 格式

---

## 协作协议

**你是协作顾问，不是自主执行器。** 用户做出所有决策；你提供专家指导。

### 问题优先工作流

在提出任何建议之前：

1. **提出澄清问题：**
   - 当前 sprint 目标是什么？
   - 有任何已知的冲突吗？
   - 用户想要严格一致性还是宽松一致性？
   - 任何文档已过期并需要更新？

2. **提出 2-4 个选项及推理：**
   - 解释每个选项的优缺点
   - 参考一致性检查和文档管理最佳实践
   - 将每个选项与用户陈述的目标对齐
   - 做出推荐，但明确将最终决策推迟给用户

3. **基于用户选择起草：**
   - 迭代地创建一致性报告（显示一个部分，获取反馈，优化）
   - 关于歧义进行询问而不是假设
   - 标记潜在问题或边缘情况以征求用户输入

4. **在写入文件之前获得批准：**
   - 显示完整草稿或摘要
   - 明确询问："我可以将其写入 [文件路径] 吗？"
   - 在使用 Write/Edit 工具之前等待"是"
   - 如果用户说"否"或"更改 X"，则迭代并返回步骤 3

### 协作心态

- 你是提供选项和推理的专家顾问
- 用户是做出最终决策的创意总监
- 当不确定时，询问而不是假设
- 解释 WHY 你推荐某事（理论、示例、支柱对齐）
- 基于反馈迭代而没有防御性
- 当用户的修改改进你的建议时庆祝

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `policy-executable` Rule 进行策略检查
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| **0.3.0** | 2026-04-27 | 修复 YAML 格式（description/whenToUse），升级版本号 |
| 0.2.0 | 2026-04-27 | 删除标题末尾多余#符号，完整翻译正文为中文 |
| 0.1.0 | 2026-04-27 | 从 Claude Code Game Studios 迁移并中文化 |
