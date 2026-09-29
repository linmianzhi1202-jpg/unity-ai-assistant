---
name: team-level
description: 团队关卡 — 协调多代理关卡设计
version: 0.2.0
category: game-development
whenToUse: >
  需要使用团队关卡技能时，或处理协调多代理关卡设计相关任务时。
  当用户提到「团队关卡」「关卡设计」「关卡规划」「关卡布局」「关卡美术方向」等关键词时，
  应使用此技能协调多个专业代理完成关卡设计工作。
input:
- 项目根目录路径（默认当前工作区）
- 目标关卡或区域名称（例如：tutorial、forest dungeon、hub town、final boss arena）
output:
- 结构化结果报告（Markdown 格式）
- 关卡设计文档（design/levels/[level-name].md）
- 叙事纲要、传说基础、视觉方向目标
- 可访问性审查结果
tools:
- read_file
- search_content
- search_file
- write_to_file
- execute_command
- task
context: inline
---

# 团队关卡技能

## 技能概述

协调多代理团队设计游戏关卡，包括叙事目的、空间布局、系统整合、视觉方向和可访问性审查。

## 使用方式

- **通过 Agent 触发**：当用户说「团队关卡」或相关需求时，Agent 应自动加载此 Skill
- **手动触发**：`/skill team-level [关卡或区域名称]`
- **使用示例**：`/skill team-level forest dungeon`

**决策点**：在每个步骤转换时，使用 `AskUserQuestion` 向用户呈现子代理的方案作为可选选项。在对话中写入代理的完整分析，然后使用简洁的标签捕获决策。用户必须在继续下一步之前批准。

## 工作流程

### 步骤 1：读取参数和收集上下文

1. **读取参数**：获取目标关卡或区域（例如：`tutorial`、`forest dungeon`、`hub town`、`final boss arena`）。

2. **收集上下文**：
   - 读取 `design/gdd/game-concept.md` 中的游戏概念
   - 读取 `design/gdd/game-pillars.md` 中的游戏支柱
   - 读取 `design/levels/` 中的现有关卡文档
   - 读取 `design/narrative/` 中的相关叙事文档
   - 读取该区域/派系的世界构建文档

### 步骤 2：委托方式

使用 Task 工具生成每个团队成员作为子代理：

- `subagent_type: narrative-director` — 叙事目的、角色、情感弧线
- `subagent_type: world-builder` — 传说上下文、环境叙事、世界规则
- `subagent_type: level-designer` — 空间布局、节奏、遭遇战、导航
- `subagent_type: systems-designer` — 敌人组成、战利品表、难度平衡
- `subagent_type: art-director` — 视觉主题、调色板、灯光、资产需求
- `subagent_type: accessibility-specialist` — 导航清晰度、色盲安全、认知负荷
- `subagent_type: qa-tester` — 测试用例、边界测试、试玩检查清单

**重要**：在每个代理的提示中始终提供完整上下文（游戏概念、支柱、现有关卡文档、叙事文档）。

### 步骤 3：编排关卡设计团队

#### 阶段 1：叙事 + 视觉方向（narrative-director + world-builder + art-director，并行）

**同时生成所有三个代理** — 在等待任何结果之前发出所有三个 Task 调用。

**生成 `narrative-director` 代理以**：
- 定义此区域的叙事目的（这里发生什么故事节拍？）
- 识别关键角色、对话触发器和传说元素
- 指定情感弧线（玩家进入时应该感觉如何，期间，离开时？）

**生成 `world-builder` 代理以**：
- 为区域提供传说上下文（历史、派系存在、生态）
- 定义环境叙事机会
- 指定影响此区域游戏玩法的任何世界规则

**生成 `art-director` 代理以**：
- 为此区域建立视觉主题目标 — 这些是布局的输入，不是输出
- 定义此区域的色温 and 灯光情绪（它与相邻区域有何不同？）
- 指定形状语言方向（有角堡垒？有机洞穴？衰败的宏伟？）
- 命名将引导玩家的主要视觉地标
- 如果存在，读取 `design/art/art-bible.md` — 将所有方向锚定在已建立的美术圣经中

**门控**：使用 `AskUserQuestion` 呈现所有三个阶段 1 输出（叙事简报、传说基础、视觉方向目标）并在继续到阶段 2 之前确认。

**重要**：`art-director` 的视觉目标从阶段 1 必须作为显式约束传递给阶段 2 中的 `level-designer`。布局决策在视觉方向内发生，而不是在它之前。

#### 阶段 2：布局和遭遇战设计（level-designer）

使用完整的阶段 1 输出作为上下文生成 `level-designer` 代理：

- 叙事简报（来自 narrative-director）
- 传说基础（来自 world-builder）
- **视觉方向目标（来自 art-director）** — 布局必须在这些目标内工作，不能与之矛盾

`level-designer` 应该：

- 设计空间布局（关键路径、可选路径、秘密）— 确保主要路线与阶段 1 的视觉地标目标对齐
- 定义节奏曲线（紧张峰值、休息区、探索区）— 与 narrative-director 的情感弧线协调
- 放置具有难度进度的遭遇战
- 设计环境谜题或导航挑战
- 定义兴趣点和用于寻路的地标 — 这些必须匹配 art-director 指定的视觉地标
- 指定入口/出口点和与相邻区域的连接

**相邻区域依赖关系检查**：生成布局后，检查 `design/levels/` 中 `level-designer` 引用的每个相邻区域。如果任何引用的区域的 `.md` 文件不存在，上报差距：

> "关卡引用 [area-name] 作为相邻区域，但 `design/levels/[area-name].md` 不存在。"

使用 `AskUserQuestion` 提供选项：
- (a) 使用占位符引用继续 — 在关卡文档中将连接标记为 UNRESOLVED，并在总结报告的开放跨关卡依赖关系部分列出
- (b) 暂停并首先运行 `/team-level [area-name]` 以建立该区域

**不要为缺失的相邻区域发明内容。**

**门控**：使用 `AskUserQuestion` 呈现阶段 2 布局（包括任何未解决的相邻区域依赖关系）并在继续到阶段 3 之前确认。

#### 阶段 3：系统集成（systems-designer）

生成 `systems-designer` 代理以：

- 指定敌人组成和遭遇战公式
- 定义战利品表和奖励放置
- 相对于预期玩家等级/装备平衡难度
- 设计任何区域特定机制或环境危害
- 指定资源分配（生命值拾取、保存点、商店）

**门控**：使用 `AskUserQuestion` 呈现阶段 3 输出并在继续到阶段 4 之前确认。

#### 阶段 4：制作概念 + 可访问性（art-director + accessibility-specialist，并行）

**注意**：`art-director` 的方向传递（视觉主题、颜色目标、情绪）发生在阶段 1。此传递是特定于位置的制作概念 — 给定最终确定的布局，每个特定空间看起来如何？

使用最终确定的布局从阶段 2 生成 `art-director` 代理：

- 为关键空间（入口、关键遭遇战区域、地标、出口）生成特定于位置的概念规格
- 指定哪些美术资产是此区域独有的 vs. 从全局池中共享
- 为每个关键空间定义视线 and 灯光设置（这些现在是基于布局的，不是方向性的）
- 指定特定于此区域布局的 VFX 需求（天气体积、粒子、大气效果）
- 标记布局创建与阶段 1 目标视觉方向冲突的任何位置 — 将这些作为制作风险上报

**并行生成 `accessibility-specialist` 代理以**：
- 审查关卡布局的导航清晰度（玩家可以在不依赖颜色的情况下定位自己吗？）
- 检查关键路径路标使用形状/图标/声音提示以及颜色
- 审查任何谜题机制的认知负荷 — 标记任何需要保持超过 3 个同时状态的内容
- 检查关键游戏玩法区域对色盲玩家有足够的对比度
- **输出**：具有严重性（BLOCKING / RECOMMENDED / NICE TO HAVE）的可访问性问题列表

**在继续之前等待两个代理返回。**

**门控**：使用 `AskUserQuestion` 呈现两个阶段 4 结果。如果 `accessibility-specialist` 返回任何 BLOCKING 问题，突出显示它们并提供：
- (a) 返回到 level-designer 和 art-director 在阶段 5 之前重新设计标记的元素
- (b) 记录为已知的可访问性差距并继续到阶段 5，将问题明确记录在最终报告中

**在没有用户确认任何 BLOCKING 可访问性问题的情况下，不要继续到阶段 5。**

#### 阶段 5：QA 规划（qa-tester）

生成 `qa-tester` 代理以：

- 为关键路径编写测试用例
- 识别边界和边缘情况（序列中断、软锁定）
- 为此区域创建试玩检查清单
- 定义关卡完成的验收标准

### 步骤 4：编译关卡设计文档

将所有团队输出合并到关卡设计模板格式中。

### 步骤 5：保存到 `design/levels/[level-name].md`

### 步骤 6：输出总结

包含以下内容的总结：区域概述、遭遇战计数、估计资产列表、叙事节拍、任何跨团队依赖关系或开放问题、开放跨关卡依赖关系（引用但未设计的相邻区域，每个标记为 UNRESOLVED），以及具有其解决状态的可访问性问题。

## 文件写入协议

所有文件写入（关卡设计文档、叙事文档、测试检查清单）都委托给通过 Task 生成的子代理。每个子代理强制执行"我可以写入 [path] 吗？"协议。此编排器不直接写入文件。

**判定**：**COMPLETE** — 关卡设计文档已生成并且所有团队输出已编译。

**判定**：**BLOCKED** — 一个或多个代理被阻止；生成部分报告并列出未解决的项目。

## 下一步

- 运行 `/design-review design/levels/[level-name].md` 以验证已完成的关卡设计文档。
- 设计批准后，运行 `/dev-story` 以实现关卡内容。
- 运行 `/qa-plan` 为此关卡生成 QA 测试计划。

## 错误恢复协议

如果任何生成的代理（通过 Task）返回 BLOCKED、错误或无法完成：

1. **立即上报**：在继续依赖阶段之前，向用户报告 `[AgentName]: BLOCKED — [reason]`
2. **评估依赖关系**：检查被阻止代理的输出是否被后续阶段需要。如果是，在没有用户输入的情况下不要超过该依赖点。
3. **通过问题确认提供选项**，选择包括：
   - 跳过此代理并在最终报告中注明差距
   - 以更窄的范围重试
   - 停在此处并首先解决阻止程序
4. **始终生成部分报告** — 输出任何已完成的工作。永远不要因为一个代理被阻止而丢弃工作。

常见阻止程序：

- 输入文件缺失（未找到故事、GDD 缺失）→ 重定向到创建它的技能
- ADR 状态为 Proposed → 不要实现；首先运行 `/architecture-decision`
- 范围太大 → 通过 `/create-stories` 拆分为两个故事
- ADR 和故事之间的指令冲突 → 上报冲突，不要猜测

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
