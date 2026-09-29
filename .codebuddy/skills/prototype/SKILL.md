---
name: prototype
description: 原型 — 快速验证想法，测试核心循环可行性
version: 0.2.0
category: game-development
whenToUse: >
  需要快速验证想法或测试核心循环可行性时使用此技能。
  适用于：定义原型要回答的核心问题、规划最小可行原型、实施原型、生成原型报告、
  根据结果决定继续/转向/终止。
input:
  - 项目根目录路径（默认当前工作区）
  - 概念名称或描述（参数）
output:
  - 原型报告（Markdown 格式）
  - protototypes/[concept-name]/REPORT.md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 原型技能#

## 技能概述#

快速验证想法，测试核心循环可行性。此技能提供结构化的原型开发工作流程，包括定义问题、加载项目上下文、规划原型、实施、生成报告、创意主管审查和下一步行动。

## 使用方式#

- 通过 Agent 触发：当用户说「原型」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill prototype [概念名称]`

---

## Phase 1: 定义问题#

解析审查模式（一次性，为本次运行中的所有门控生成存储）：
1. 如果传递了 `--review [full|lean|solo]` → 使用其值
2. 否则读取 `production/review-mode.txt` → 使用其值
3. 否则 → 默认为 `lean`

请参阅 `.claude/docs/director-gates.md` 以获取完整的检查模式。

从参数读取概念描述。识别此原型必须回答的核心问题。如果概念模糊，在继续之前明确陈述问题 — 没有清晰问题的原型是浪费时间。

---

## Phase 2: 加载项目上下文#

读取 `CLAUDE.md` 以获取项目上下文和当前技术栈。了解正在使用什么引擎、语言和框架，以便原型使用兼容的工具构建。

---

## Phase 3: 规划原型#

用 3-5 个要点定义最小可行原型看起来像什么：
- 核心问题是什么？
- 回答它所需的最小代码是什么？
- 可以跳过什么（错误处理、打磨、架构）？

在构建之前向用户展示此计划。如果范围似乎不清晰，询问确认。

---

## Phase 4: 实施#

询问："我可以在 `prototypes/[concept-name]/` 创建原型目录并开始实施吗？"

如果可以，创建目录。每个文件必须以以下内容开头：

```
// PROTOTYPE - NOT FOR PRODUCTION
// Question: [正在测试的核心问题]
// Date: [当前日期]
```

标准有意放宽：
- 自由使用硬编码值
- 使用占位符资源
- 跳过错误处理
- 使用可行的最简单方法
- 从生产复制代码而不是导入

运行原型。观察行为。收集任何可测量的数据（帧时间、交互计数、感觉评估）。

---

## Phase 5: 生成原型报告#

起草报告：

```markdown
## 原型报告：[概念名称]

### 假设
[我们期望为真的 — 我们着手回答的问题]

### 方法
[我们构建了什么，花了多长时间，我们采取了什么捷径]

### 结果
[实际发生了什么 — 具体观察，不是意见]

### 指标
[测试期间收集的任何可测量数据]
- 帧时间：[如果相关]
- 感觉评估：[主观但具体 — "在 200ms 延迟时感觉迟缓" 不是 "感觉不好"]
- 玩家动作计数：[如果相关]
- 迭代计数：[使其工作所需的尝试次数]

### 建议：[PROCEED / PIVOT / KILL]

[用证据解释建议的一段话]

### 如果继续#
[生产质量实施需要什么改变]
- 架构要求
- 性能目标
- 原始设计的范围调整
- 估计的生产工作量

### 如果转向**#
[结果建议的替代方向]

### 如果终止**#
[为什么此概念不起作用以及我们应该做什么代替]

### 经验教训#
[影响其他系统或未来工作的发现]
```

询问："我可以将此报告写入 `prototypes/[concept-name]/REPORT.md` 吗？"

如果可以，写入文件。

---

## Phase 6: 创意主管审查#

**审查模式检查** — 在生成 CD-PLAYTEST 之前应用：
- `solo` → 跳过。注意："CD-PLAYTEST 已跳过 — 单人模式。" 使用原型制作者的建议作为最终判定，继续 Phase 7 摘要。
- `lean` → 跳过（不是阶段门控）。注意："CD-PLAYTEST 已跳过 — 精简模式。" 使用原型制作者的建议作为最终判定，继续 Phase 7 摘要。
- `full` → 正常生成。

分类发现后，通过 Task 使用门 **CD-PLAYTEST**（`.claude/docs/director-gates.md`）生成 `creative-director`。

传递：完整 REPORT.md 内容、原始设计问题、游戏支柱和核心幻想（来自 `design/gdd/game-concept.md`，如果存在）。

在保存报告之前展示创意主管的评估。如果 CONCERNS 或 REJECT，在报告中添加 `## 创意主管评估` 部分以捕获判定和反馈。如果 APPROVE，在报告中注意批准。

---

## Phase 7: 摘要和下一步#

向用户输出摘要：核心问题、结果、原型制作者的初始建议，以及创意主管的最终决策。链接到 `prototypes/[concept-name]/REPORT.md` 中的完整报告。

如果 **PROCEED**：运行 `/design-system` 开始此机制的生产 GDD，或在实施之前运行 `/architecture-decision` 以记录关键技术决策。

如果 **PIVOT** 或 **KILL**：不需要进一步行动 — 原型报告是可交付成果。

结论：**完成** — 原型已完成。建议根据发现继续、转向或终止。

### 重要约束#

- 原型代码绝不能从生产源文件导入
- 生产代码绝不能从原型目录导入
- 如果建议是 PROCEED，生产实施必须从头开始编写 — 原型代码不会重构为生产
- 总原型工作量应限制在相当于 1-3 天的工作
- 如果原型范围开始增长，停止并重新评估问题是否可以简化

---

## 推荐下一步#

- **如果 PROCEED**：运行 `/design-system [mechanic]` 以编写生产 GDD，或在实施之前运行 `/architecture-decision` 以记录关键技术决策
- **如果 PIVOT**：运行 `/prototype [revised-concept]` 以测试调整后的方向
- **如果 KILL**：不需要进一步行动 — 原型报告是可交付成果
- 运行 `/playtest-report` 以正式记录原型期间进行的任何试玩会话

---

## Unity C# 原型代码参考索引

在构建 Unity 原型时，可以参考以下 Template 项目中的现成实现：

| 原型领域 | 参考项目 | 路径 | 文件数 | 关键类 |
|----------|---------|------|--------|--------|
| 角色控制 | 2D-Character-Controller | `referrence/Template/2D-Character-Controller-master/` | ~5 | PlayerController2D |
| 时间回退 | InGameReplay | `referrence/Template/InGameReplay-master/` | ~2 | ReplayRecorder |
| 抓钩效果 | Grapple-Effect | `referrence/Template/Grapple-Effect-master/` | ~2 | GrappleHook |
| 战争迷雾 | FogOfWar | `referrence/Template/FogOfWar-master/` | ~2 | FogOfWarRevealer |
| 切割效果 | ezy-slice | `referrence/Template/ezy-slice-master/` | ~10 | EzySlice |
| 八叉树 | UnityOctree | `referrence/Template/UnityOctree-master/` | ~4 | Octree |
| 运行时变换 | RuntimeTransformGizmo | `referrence/Template/Unity3DRuntimeTransformGizmo-master/` | ~20 | TransformGizmo |
| 泛型背包 | Inventory | `referrence/Template/Inventory-master/` | ~21 | InventoryManager |
| 简单 MOBA | UnityMoba | `referrence/Template/UnityMoba-master/` | ~914 | HeroController |
| 完整 RPG | RPGCore | `referrence/Template/RPGCore-main/` | ~425 | RPGCharacterController |
| RTS 教程 | UnityTutorials-RTS | `referrence/Template/UnityTutorials-RTS-master/` | ~96 | RTSManager |

**使用方式**：在 Phase 4 实施时，读取对应参考项目的核心 .cs 文件作为原型起点。

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文
- 使用 `unity-csharp-patterns` Rule 检查 C# 编码正反例
- 使用 `unity-performance` Rule 检查性能正反例

---

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
