---
name: propagate-design-change
description: 传播设计变更 — 级联更新受影响文档，保持一致性
version: 0.2.0
category: game-development
whenToUse: >
  需要级联更新受影响文档或保持文档一致性时使用此技能。
  适用于：当 GDD 变更时，查找所有受影响的 ADR，比较 ADR 假设与 GDD 新内容，并指导用户解决不一致性。
  需要参数：GDD 文件路径（例如 design/gdd/combat-system.md）。
input:
  - 项目根目录路径（默认当前工作区）
  - GDD 文件路径（必需参数）
output:
  - 设计变更影响报告（Markdown 格式）
  - docs/architecture/change-impact-[date]-[system].md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 传播设计变更技能

## 技能概述

级联更新受影响文档，保持一致性。当 GDD 变更时，此技能查找每个受影响的 ADR；比较 ADR 假设与 GDD 现在说的内容，并指导用户通过解决方案。

## 使用方式

- 通过 Agent 触发：当用户说「传播设计变更」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill propagate-design-change design/gdd/[system].md`

---

## 1. 验证参数

GDD 路径参数是**必需的**。如果缺失，失败并显示：
> "用法：`/propagate-design-change design/gdd/[system].md`"
> "提供已更改的 GDD 的路径。"

验证文件是否存在。如果不存在，失败并显示：
> "[路径] 未找到。检查路径并重试。"

---

## 2. 读取更改的 GDD

完整读取当前的 GDD。

---

## 3. 读取先前版本

运行 git 以获取先前提交的版本：

```bash
git show HEAD:design/gdd/[filename].md
```

如果文件没有 git 历史（新文件），报告：
> "git 中没有先前版本 — 这似乎是一个新的 GDD，而不是修订。"
> "没有可传播的内容。"

如果 git 返回先前版本，进行概念性差异：
- 识别更改的部分（新规则、删除的规则、修改的公式、更改的验收标准、更改的调优参数）
- 识别未更改的部分
- 生成更改摘要：

```
## 更改摘要：[GDD 文件名]
修订日期：[今天]

更改的部分：
- [部分名称]：[更改了什么 — 新规则、删除的规则、修改的公式等。]

未更改的部分：
- [部分名称]

影响架构的关键更改：
- [更改 1 — 可能影响 ADR]
- [更改 2]
```

---

## 4. 加载架构输入

读取 `docs/architecture/` 中的所有 ADR：
- 对于每个 ADR，读取完整文件
- 提取 "GDD Requirements Addressed" 表
- 注意每个 ADR 引用的 GDD 文档和需求 ID

读取 `docs/architecture/architecture-traceability.md`（如果存在）。

报告："已加载 [N] 个 ADR。[M] 个引用 [gdd 文件名]。"

---

## 5. 影响分析

对于每个引用更改的 GDD 的 ADR：

比较 ADR 的 "GDD Requirements Addressed" 条目与 GDD 的更改部分。对于每个引用的需求：

1. **在当前的 GDD 中定位需求** — 它仍然存在吗？
2. **比较**：写入 ADR 时 GDD 说了什么 vs. 它现在说什么？
3. **评估 ADR 决策**：架构决策仍然有效吗？

将每个受影响的 ADR 分类为以下之一：

| 状态 | 含义 |
|--------|---------|
| ✅ **仍然有效** | GDD 更改不影响此 ADR 决定的内容 |
| ⚠️ **需要审查** | GDD 更改可能影响此 ADR — 需要人工判断 |
| 🔴 **可能已取代** | GDD 更改直接与此 ADR 假设的矛盾 |

对于每个受影响的 ADR，生成影响条目：

```
### ADR-NNN: [标题]
状态：[仍然有效 / 需要审查 / 可能已取代]

此 ADR 对此 GDD 的假设：
  "[来自 ADR 的 GDD Requirements Addressed 部分的相关引用]"

GDD 现在说：
  "[来自当前 GDD 的相关引用]"

评估：
  [解释 ADR 决策是否仍然有效，以及为什么]

建议操作：
  [保持原样 | 审查和更新 | 标记为已取代并写入新 ADR]
```

---

## 6. 展示影响报告

在询问任何操作之前，向用户展示完整的影响报告。格式：

```
## 设计变更影响报告
GDD：[文件名]
日期：[今天]
检测到更改：[N 个部分已更改]
引用此 GDD 的 ADR：[M]

### 未受影响
[决策保持有效的 ADR]

### 需要审查 ([计数])
[可能需要的更新的 ADR]

### 可能已取代 ([计数])
[假设现在矛盾的 ADR]
```

---

## 6b. 主管门控 — 技术影响审查

**审查模式检查** — 在生成 TD-CHANGE-IMPACT 之前应用：
- `solo` → 跳过。注意："TD-CHANGE-IMPACT 已跳过 — 单人模式。" 继续阶段 7（解决方案工作流）。
- `lean` → 跳过（不是阶段门控）。注意："TD-CHANGE-IMPACT 已跳过 — 精简模式。" 继续阶段 7（解决方案工作流）。
- `full` → 正常生成。

分类发现后，通过 Task 使用门 **TD-CHANGE-IMPACT**（`.claude/docs/director-gates.md`）生成 `technical-director`。

传递：来自阶段 6 的完整设计变更影响报告（更改摘要、所有受影响的 ADR 及其仍然有效 / 需要审查 / 可能已取代分类和建议操作）。

展示技术主管的评估。如果 CONCERNS 或 REJECT，在报告中添加 `## 技术主管评估` 部分以捕获判定和反馈。如果 APPROVE，在报告中注意批准。

---

## 7. 解决方案工作流

对于每个标记为 "需要审查" 或 "可能已取代" 的 ADR，询问用户要做什么：

逐一询问每个 ADR：
> "ADR-NNN ([标题]) — [状态]。你想做什么？"
> 选项：
> - "标记为已取代（我将写入新 ADR）" — 更新 ADR 状态行到 `Superseded by: [pending]`
> - "就地更新（次要修订）" — 打开 ADR 进行编辑；注意要修订什么
> - "保持原样（更改实际上不影响此决策）"
> - "暂时跳过（稍后重新访问）"

对于标记为**已取代**的 ADR：
- 更新 ADR 的 Status 字段：`Superseded by ADR-[next number] (pending — see change-impact-[date]-[system].md)`
- 询问："我可以更新 [ADR 文件名] 中的状态吗？"

---

## 8. 更新可追踪性索引

如果 `docs/architecture/architecture-traceability.md` 存在：
- 将更改的 GDD 需求添加到 "Superseded Requirements" 表：

```markdown
## 已取代的需求
| 日期 | GDD | 需求 | 已更改到 | ADR 受影响 | 解决方案 |
|------|-----|-------------|------------|---------------|------------|
| [日期] | [gdd] | [旧需求文本] | [新需求文本] | [ADR-NNN] | [已取代/已更新/有效] |
```

询问："我可以更新可追踪性索引吗？"

---

## 9. 输出变更影响文档

询问："我可以将此变更影响报告写入 `docs/architecture/change-impact-[date]-[system-slug].md` 吗？"

文档包含：
- 来自步骤 3 的更改摘要
- 来自步骤 5 的完整影响分析
- 在步骤 7 中做出的解决方案决策
- 需要写入或更新的 ADR 列表

如果用户批准：结论：**完成** — 变更影响报告已保存。

如果用户拒绝：结论：**已锁定** — 用户拒绝写入。

---

## 10. 后续行动

基于解决方案决策，建议：

- **标记为已取代的 ADR**："运行 `/architecture-decision [title]` 以写入替换 ADR。然后重新运行 `/propagate-design-change` 以验证覆盖。"
- **要就地更新的 ADR**：列出每个 ADR 中要更新的特定字段
- **如果许多 ADR 受影响**："所有 ADR 更新后运行 `/architecture-review` 以验证完整可追踪性矩阵仍然连贯。"

---

## 协作协议

1. **静默读取** — 在展示任何内容之前计算完整影响
2. **首先展示完整报告** — 在询问操作之前让用户看到范围
3. **每个 ADR 询问** — 不要批处理决策；每个受影响的 ADR 可能需要不同的处理
4. **在写入之前询问** — 在修改任何文件之前始终确认
5. **非破坏性** — 永远不要删除 ADR 内容；仅添加 "已取代" 注释

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
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
