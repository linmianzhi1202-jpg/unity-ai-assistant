---
name: bug-triage
description: "Bug 分类 — 分类错误报告，分配优先级，规划修复"
version: 0.2.0
category: game-development
whenTUse: |
  当需要通过 Bug 分类技能分类错误报告时使用。
  处理分配优先级、规划修复、生成分类报告相关任务时。
  支持参数：sprint（当前 sprint 分类）、full（完全分类）、trend（趋势分析）、无参数（自动检测）。
input:
  - 项目根目录路径（默认当前工作区）
  - 分类模式参数：sprint / full / trend / 无
output:
  - Bug 分类报告（production/qa/bug-triage-[date].md）
  - Bug 分配矩阵和更新待办事项
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# Bug 分类技能#

## 技能概述#

分类错误报告，分配优先级，规划修复。

## 使用方式#

- 通过 Agent 触发：当用户说「Bug 分类」或相关需求时，Agent 应自动加载此 Skill#
- 手动触发：`/skill bug-triage [参数]`#

## 功能说明#

此技能将开放的 bug 待办事项处理为优先化的、分配给 sprint 的操作列表。它区分 **严重性**（影响有多坏？）和 **优先级**（我们必须多 urgently 修复它？），检测系统性趋势，并确保在 sprint 之间不会丢失关键 bug。

**输出：** `production/qa/bug-triage-[date].md`#

### 何时运行#

- **Sprint 开始** — 将开放的 bugs 分配给新的 sprint 或待办事项#
- 在 `/team-qa` 完成并且新 bugs 已被 filed 之后#
- 当 bug 计数超过 10+ 开放项目时#

---

## 参数模式#

**模式：**

- `/bug-triage sprint` — 针对当前 sprint 进行分类；将可修复的 bugs 分配给 sprint 待办事项；推迟其余的#
- `/bug-triage full` — 完全分类所有 bugs，不考虑 sprint 范围#
- `/bug-triage trend` — 仅趋势分析（无分配）；只读报告#
- 无参数 — 如果存在当前 sprint，则运行 sprint 模式，否则为 full 模式#

---

## 工作流程#

### 阶段 1：加载 Bug 待办事项#

#### 步骤 1a — 发现 bug 文件#

按优先级顺序 Glob bug 报告：

1. `production/qa/bugs/*.md` — 单独的 bug 报告文件（首选格式）#
2. `production/qa/bugs.md` — 单个合并的 bug 日志（回退）#
3. 任何 `production/qa/qa-plan-*.md` 中的 "Bugs Found" 表（最后手段）#

如果未找到 bug 文件：
> "在 `production/qa/bugs/` 中未找到 bug 文件。如果 bugs 在不同位置跟踪，请调整 glob 模式。如果 bugs 还不存在，则没有可分类的内容。"

**停止** 并且如果不 exits bugs 则不继续。

#### 步骤 1b — 解析每个 bug#

对于每个 bug 文件：

1. 读取完整文件#
2. 提取：**ID**、**严重性**、**优先级**、**状态**、**报告日期**#
3. 分类状态：#
   - `Open` — 需要分类#
   - `In Progress` — 已经在处理中#
   - `Verified` — 修复已验证#
   - `Closed` — 已完成，从分类中排除#
4. 输出：`BugList { open[], in_progress[], verified[] }`#

---

### 阶段 2：严重性 vs. 优先级评估#

对于每个开放的 bug：

#### 严重性（影响）#

- **S1-Critical**：崩溃、数据丢失、无法玩游戏#
- **S2-Major**：主要特性损坏、性能严重下降#
- **S3-Minor**：次要特性问题、UI 对齐#
- **S4-Trivial**：视觉瑕疵、拼写错误#

#### 优先级（紧急性）#

- **P1-Immediate**：在下一个构建中修复（阻止发布）#
- **P2-Next Sprint**：在下一个 sprint 中规划#
- **P3-Backlog**：添加到待办事项以供将来考虑#
- **P4-Wishlist**：很好有，但不保证#

#### 决策矩阵#

| 严重性 | 频率 | 优先级 |
|----------|----------|----------|
| S1-Critical | Always | P1-Immediate |
| S2-Major | Often | P1-Immediate |
| S2-Major | Sometimes | P2-Next Sprint |
| S3-Minor | Often | P2-Next Sprint |
| S3-Minor | Rare | P3-Backlog |
| S4-Trivial | Any | P4-Wishlist |

---

### 阶段 3：系统性趋势检测#

1. **按系统分组** bugs：#
   - 哪个系统有最多的 bugs？#
   - 任何模式（例如，所有 UI bugs 都在设置屏幕上）？#

2. **按根本原因分组**：#
   - 空引用？#
   - 边界条件缺失#
   - 资源泄漏#
   - 逻辑错误#

3. **按引入时间分组**：#
   - 大多数 bugs 是在 sprint 3 中引入的吗？#
   - 任何回归（修复的 bug 返回）？#

4. **输出**：`TrendReport { system_clusters[], root_cause_clusters[], sprint_introduction[] }`#

---

### 阶段 4：分配规划#

1. **对于 P1 bugs**：#
   - 分配给当前 sprint#
   - 指定负责人（或标记为"需要分配"）#
   - 添加验收标准#

2. **对于 P2 bugs**：#
   - 添加到下一个 sprint 待办事项#
   - 按影响排序#

3. **对于 P3/P4 bugs**：#
   - 添加到待办事项#
   - 在注释中包含解决方法（如果有）#

4. **生成分配矩阵**：#

```markdown
# Bug 分配矩阵#

## P1-Immediate（必须在下一个构建中修复）#

| BUG ID | 标题 | 严重性 | 分配给 | Sprint |
|--------|--------|----------|----------|--------|
| BUG-0042 | 玩家在保存时崩溃 | S1-Critical | @devops-engineer | Sprint 15 |

## P2-Next Sprint（在下一个 sprint 中规划）#

| BUG ID | 标题 | 严重性 | 目标 Sprint |
|--------|--------|----------|--------------|
| BUG-0038 | 设置中的 UI 对齐 | S3-Minor | Sprint 16 |
```

---

### 阶段 5：生成分类报告#

创建 `production/qa/bug-triage-[date].md`：

1. **摘要**：分类的 bug 计数、P1/P2 计数#
2. **严重性分布**：表格显示每个严重性级别的 bug#
3. **优先级分配**：表格显示每个优先级的 bug#
4. **趋势分析**：识别的系统性问题#
5. **操作项**：按优先级排序的待办事项列表#

---

## 输出格式#

### Bug 分类报告#

```markdown
# Bug 分类报告#

**日期**：2026-04-27#
**Sprint**：Sprint 15#
**分类的 Bugs**：23#

## 摘要#

- **P1-Immediate**：3 bugs#
- **P2-Next Sprint**：8 bugs#
- **P3-Backlog**：10 bugs#
- **P4-Wishlist**：2 bugs#

## 严重性分布#

| 严重性 | 计数 | 百分比 |
|----------|--------|----------|
| S1-Critical | 2 | 8.7% |
| S2-Major | 5 | 21.7% |
| S3-Minor | 12 | 52.2% |
| S4-Trivial | 4 | 17.4% |

## 优先级分配#

### P1-Immediate（必须在下一个构建中修复）#

1. **BUG-0042**：玩家在保存时崩溃#
   - **分配给**：@devops-engineer#
   - **Sprint**：Sprint 15#
   - **验收标准**：保存游戏不会崩溃；测试所有保存槽位#

2. **BUG-0045**：战斗中的内存泄漏#
   - **分配给**：@engine-programmer#
   - **Sprint**：Sprint 15#
   - **验收标准**：30 分钟游戏后内存稳定#

### P2-Next Sprint（在下一个 sprint 中规划）#

1. **BUG-0038**：设置中的 UI 对齐#
   - **目标 Sprint**：Sprint 16#
   - **注释**：影响所有设置屏幕#

## 趋势分析#

### ⚠️ 系统性问题#

1. **保存系统**（5 个 bugs）#
   - 根本原因：空引用未按边界检查#
   - **建议**：添加保存系统的自动化测试#

2. **UI 对齐**（3 个 bugs）#
   - 根本原因：固定像素定位而不是相对#
   - **建议**：迁移到 UI Toolkit 以获得更好的布局#

## 操作项#

### 高优先级（必须做）#

1. [ ] 修复 BUG-0042（保存崩溃）#
2. [ ] 修复 BUG-0045（内存泄漏）#
3. [ ] 规划 BUG-0038 到 Sprint 16#

### 中优先级（应该做）#

1. [ ] 审查所有保存系统代码以查找空引用#
2. [ ] 为保存系统添加自动化测试#

### 低优先级（可以做）#

1. [ ] 迁移 UI 到 UI Toolkit#
2. [ ] 添加 UI 自动化测试#
```

---

## 质量检查#

- [ ] 所有开放的 bugs 已分类#
- [ ] 严重性评估基于影响，而不是主观意见#
- [ ] 优先级评估考虑 sprint 目标和发布时间表#
- [ ] 趋势分析识别系统性问题#
- [ ] 分配矩阵指定负责人或目标 sprint#
- [ ] 输出使用结构化 Markdown 格式#

---

## 协作协议#

**你是协作实现者，不是自主代码生成器。** 用户批准所有决策。

### 问题优先工作流#

在提出任何建议之前：

1. **提出澄清问题：**#
   - 当前的 sprint 目标是什么？#
   - 发布日期有任何约束吗？#
   - 任何 bugs 有社区或利益相关者的压力？#
   - 我们应优先考虑稳定性还是特性工作？#

2. **提出 2-4 个选项及推理：**#
   - 解释每个选项的优缺点#
   - 参考敏捷规划和 scrum 方法论#
   - 将每个选项与项目目标对齐#
   - 做出推荐，但明确将最终决策推迟给用户#

3. **基于用户选择起草：**#
   - 迭代地创建分类（显示一个部分，获取反馈，优化）#
   - 关于歧义进行询问而不是假设#
   - 标记潜在问题或边缘情况以征求用户输入#

4. **在写入文件之前获得批准：**#
   - 显示完整草稿或摘要#
   - 明确询问："我可以将其写入 [文件路径] 吗？"#
   - 在使用 Write/Edit 工具之前等待"是"#
   - 如果用户说"否"或"更改 X"，则迭代并返回步骤 3#

### 协作心态#

- 你是提供选项和推理的专家顾问#
- 用户是做出最终决策的 Scrum Master#
- 当不确定时，询问而不是假设#
- 解释 WHY 你推荐某事（理论、示例、优先级对齐）#
- 基于反馈迭代而没有防御性#
- 当用户的修改改进你的建议时庆祝#

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `policy-executable` Rule 进行策略检查#
- 使用 `parity-audit` Skill 进行质量审计#
- 使用 `cost-tracker` Skill 估算成本影响#

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 清理格式（删除标题末尾多余的 #），更新版本号 |
| 0.1.0 | 2026-04-27 | 从 Claude Code Game Studios 迁移并中文化 |
