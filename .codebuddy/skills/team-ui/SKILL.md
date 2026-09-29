---
name: team-ui
description: 团队 UI — 协调多代理开发 UI 系统
version: 0.2.0
category: game-development
whenToUse: >
  当需要协调多代理开发 UI 系统时使用此技能。
  通过结构化管道协调 UI 团队，包括 UX 设计师、
  UI 程序员、美术总监、引擎 UI 专家和可访问性专家。
  适用于：从 UX 规范到实施、审查、打磨的完整 UI 开发流程。
input:
  - 项目根目录路径（默认当前工作区）
  - 功能名称或 "hud"（用于 HUD 设计）
output:
  - UX 规范文档（design/ux/[feature-name].md）
  - HUD 设计文档（design/ux/hud.md）
  - 实施后的 UI 功能
  - 交互模式库更新（design/ux/interaction-patterns.md）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 团队 UI 技能#

## 技能概述#

协调多代理开发 UI 系统。此技能通过结构化管道协调 UI 团队，从 UX 规范创建到实施、审查和打磨。

**团队组成**：
- **ux-designer** — 用户流程、线框图、可访问性、输入处理
- **ui-programmer** — UI 框架、屏幕、小部件、数据绑定、实施
- **art-director** — 视觉样式、布局打磨、与艺术圣经的一致性
- **引擎 UI 专家** — 根据引擎特定最佳实践验证 UI 实施模式
- **accessibility-specialist** — 在阶段 4 审查可访问性合规性

**适用场景**：
- 为新功能或屏幕创建完整的 UI
- 设计游戏 HUD（抬头显示）
- 在实施前验证 UX 规范
- 协调多个代理进行 UI 开发

## 使用方式#

- 通过 Agent 触发：当用户说「团队 UI」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill team-ui [参数]`

**参数模式**：
- `/team-ui [feature-name]` — 为特定功能运行完整管道
- `/team-ui hud` — 设计 HUD（使用 hud-design 模板）
- 无参数 — 使用 `AskUserQuestion` 询问

---

## 阶段 0: 解析参数#

**参数**: `$ARGUMENTS[0]` (空白 = 询问用户）

从参数确定模式：

| 参数 | 模式 | 输出 |
|----------|------|----------|
| `[feature-name]` | 完整 UI 管道 | `design/ux/[feature-name].md` + 实施 |
| `hud` | HUD 设计模式 | `design/ux/hud.md` + HUD 实施 |
| 无参数 | 询问 | 使用 `AskUserQuestion` |

---

## 阶段 1: 上下文收集#

在设计任何内容之前，读取并综合：

### 1a: 必需读取#

- `design/gdd/game-concept.md` — 平台目标和目标受众
- `design/player-journey.md` — 玩家到达此屏幕时的状态和上下文
- 与此功能相关的所有 GDD UI Requirements 部分
- `design/ux/interaction-patterns.md` — 要重用的现有模式（不重新发明）
- `design/accessibility-requirements.md` — 承诺的可访问性层级（例如，Basic、Enhanced、Full）

### 1b: 检查交互模式库状态#

**如果 `design/ux/interaction-patterns.md` 不存在**，立即提出缺口：
> "interaction-patterns.md 不存在 — 没有要重用的现有模式。"

然后使用 `AskUserQuestion` 提供选项：
- (a) 首先运行 `/ux-design patterns` 以建立模式库，然后继续
- (b) 在没有模式库的情况下继续 — ui-programmer 将把所有模式视为新并将每个添加到新的 `design/ux/interaction-patterns.md`

**不要**仅从功能名称或 GDD 发明或假设模式。如果用户在阶段 1b 中选择 (b)，在阶段 3 中明确指示 ui-programmer 将所有模式视为新。

### 1c: 摘要上下文#

向用户展示简要摘要：
> **设计对象**: [屏幕/流程名称]
> - 模式: [完整 UI 管道 / HUD 设计]
> - 旅程阶段: [来自 player-journey.md，或 "未知"]
> - GDD 需求: [计数和名称，或 "未找到"]
> - 现有模式: [计数，或 "尚无模式库"]
> - 可访问性层级: [来自需求文档，或 "尚未定义"]

然后询问："在开始设计之前，我还有什么应该读取的吗，或者我们可以继续？"

---

## 阶段 2: UX 规范创建#

调用 `/ux-design [feature-name]` 技能 OR 直接委托给 **ux-designer** 以生成遵循 `ux-spec.md` 模板的 `design/ux/[feature-name].md`。

如果专门设计 HUD，使用 `hud-design.md` 模板而不是 `ux-spec.md`。

> **关于特殊情况的说明：**
> - 对于 HUD 设计，使用 `argument: hud` 调用 `/ux-design`（例如，`/ux-design hud`）。
> - 对于交互模式库，在项目开始时运行一次 `/ux-design patterns`，并在后续阶段引入新模式时更新它。

**输出**: `design/ux/[feature-name].md`，所有必需部分已填写。

---

## 阶段 3: UX 审查#

规范完成后，调用 `/ux-review design/ux/[feature-name].md`。

**门控**: 在 UX 审查判定为 **APPROVED** 之前，不要继续到阶段 4。

如果判定是 **NEEDS REVISION**，ux-designer 必须解决问题并重新运行审查。用户可能明确接受 NEEDS REVISION 风险并继续，但这必须是有意识的决定 — 在询问是否继续之前，使用 `AskUserQuestion` 呈现特定关注。

---

## 阶段 4: 视觉设计#

委托给 **art-director**：

- 审查完整的 UX 规范（流程、线框图、交互模式、可访问性注释）— 不仅仅是线框图图像
- 应用艺术圣经中的视觉处理：颜色、排版、间距、动画样式
- 检查视觉设计保持可访问性合规：验证颜色对比度比率，并确认颜色不是状态的唯一指示器（形状、文本或图标必须强化它）
- 指定美术管道所需的所有资产要求：指定大小和格式的图标、背景纹理、字体、装饰元素 — 带有精确尺寸和格式要求
- 确保与现有已实施的 UI 屏幕的一致性
- **输出**: 带有样式注释和资产清单的视觉设计规范

---

## 阶段 5: 实施#

### 5a: 引擎 UI 专家审查（可选）#

在实施开始之前，生成**引擎 UI 专家**（从 `.claude/docs/technical-preferences.md` 引擎专家 → UI 专家）以审查 UX 规范和视觉设计规范以获取引擎特定的实施指导：
- 此屏幕应使用哪个引擎 UI 框架？（例如，Unity 中的 UI Toolkit vs UGUI，Godot 中的 Control 节点 vs CanvasLayer，Unreal 中的 UMG vs CommonUI）
- 提议的布局或交互模式是否有任何引擎特定的注意事项？
- 此功能的推荐小部件/节点结构？

**输出**: 引擎 UI 实施注释，在开始时移交给 ui-programmer。

如果未配置引擎，跳过此步骤。

### 5b: 委托给 ui-programmer#

委托给 **ui-programmer**：

- 按照 UX 规范和视觉设计规范实施 UI
- **使用 `design/ux/interaction-patterns.md` 中的模式** — 不要重新发明已指定的模式。如果模式几乎适合但需要修改，注意偏差并标记为 ux-designer 审查。
- **UI 永远不要拥有或修改游戏状态** — 仅显示；为所有玩家操作发出事件
- 所有文本通过本地化系统 — 没有硬编码的面向玩家的字符串
- 支持两种输入方法（键盘/鼠标 AND 游戏手柄）
- 按照 `design/accessibility-requirements.md` 中承诺的层级实施可访问性功能
- 将数据绑定到游戏状态
- **如果在实施期间创建了任何新交互模式**（即，模式库中尚未存在的模式），在实施完成之前将其添加到 `design/ux/interaction-patterns.md`

**输出**: 已实施的 UI 功能

---

## 阶段 6: 审查（并行）#

并行委托：

### ux-designer 审查#
验证实施与线框图和交互规范匹配。测试仅键盘和仅游戏手柄导航。检查可访问性功能是否正确运行。

### art-director 审查#
验证与艺术圣经的视觉一致性。检查最低和最高支持分辨率的实施。

### accessibility-specialist 审查#
按照 `design/accessibility-requirements.md` 中承诺的层级验证合规性。将任何违规标记为阻止项。

所有三个审查流必须在继续到阶段 7 之前报告。

---

## 阶段 7: 打磨#

- 解决所有审查反馈
- 验证动画可跳过并尊重玩家的动作减少偏好
- 确认 UI 声音通过音频事件系统触发（不直接音频调用）
- 在所有支持的分辨率和纵横比下测试
- **验证 `design/ux/interaction-patterns.md` 是最新的** — 如果在此期间引入了任何新模式，确认它们已添加到库
- **确认所有 HUD 元素尊重 `design/ux/hud.md` 中定义的视觉预算**（元素计数、屏幕区域分配、最大不透明度值）

---

## 快速参考 — 何时使用哪个技能#

- `/ux-design` — 从头开始为新屏幕、流程或 HUD 创作 UX 规范
- `/ux-review` — 在实施前验证已完成的 UX 规范
- `/team-ui [feature]` — 从概念到打磨的完整管道（内部调用 `/ux-design` 和 `/ux-review`）
- `/quick-design` — 不需要完整新 UX 的小 UI 更改

---

## 阶段 8: 输出#

涵盖以下内容的摘要报告：
- UX 规范状态（已批准 / 需要修订）
- UX 审查判定（APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED）
- 视觉设计状态（已完成 / 需要修订）
- 实施状态（已完成 / 部分完成）
- 可访问性合规性（通过 / 失败，带有特定违规）
- 输入方法支持（键盘/鼠标、游戏手柄、触摸）
- 交互模式库更新状态（已更新 / 不需要）
- 任何未解决的问题

判定：**完成** — UI 功能通过完整管道交付（UX 规范 → 视觉 → 实施 → 审查 → 打磨）。
判定：**已阻止** — 管道停止；表面阻止项和停止的阶段。

---

## 错误恢复协议#

如果任何生成的代理（通过 Task）返回 **BLOCKED**、错误，或无法完成：

1. **立即表面**：在继续依赖阶段之前，向用户报告 "[AgentName]: BLOCKED — [原因]"。
2. **评估依赖关系**：检查被阻止代理的输出是否是后续阶段所必需的。如果是，在没有用户输入的情况下，不要超过该依赖点。
3. **提供选项** 使用 AskUserQuestion 提供选择：
   - 跳过此代理并将缺口记录在最终报告中
   - 使用更窄的范围重试
   - 在此处停止并首先解决阻止项
4. **始终生成部分报告** — 输出已完成的任何内容。永远不要因为一个代理被阻止而丢弃工作。

**常见阻止项**：
- 输入文件缺失（故事未找到，GDD 缺失）→ 重定向到创建它的技能
- ADR 状态是 Proposed → 不要实施；首先运行 `/architecture-decision`
- 范围太大 → 通过 `/create-stories` 拆分为两个故事
- ADR 和故事之间的指令冲突 → 表面冲突，不要猜测

---

## 文件写入协议#

所有文件写入（UX 规范、交互模式库更新、实施文件）都委托给子代理和子技能（`/ux-design`、`ui-programmer`）。每个都强制使用"我可以写入 [路径]？"协议。此编排器不直接写入文件。

---

## 下一步#

- 如果尚未批准，运行 `/ux-review` 以验证最终规范
- 在关闭故事之前，运行 `/code-review` 对 UI 实施进行
- 如果需要视觉或音频打磨通道，运行 `/team-polish`

---

## 协作协议#

此技能遵循每个步骤的协作设计原则：

1. **问题 → 选项 → 决策 → 草稿 → 批准** 对于每个主要阶段
2. **在每个决策点使用 `AskUserQuestion`**（解释 → 捕获模式）：
   - 阶段 1: "准备好开始，还是需要更多上下文？"
   - 阶段 2: "我可以创建 UX 规范骨架吗？"
   - 阶段 3: "UX 规范已准备好。继续到实施？"
   - 阶段 5: "实施已准备好。运行审查？"
   - 阶段 6: "所有审查完成。继续到打磨？"
3. **"我可以写入 [文件路径] 吗？"** 在骨架之前和每个阶段写入之前
4. **并行化** 当管道允许时（例如，阶段 6 审查代理可以同时运行）
5. **会话状态更新**：在每次主要阶段完成后

**美学 deferment**：当布局或视觉选择取决于个人品味时，展示选项并询问。不要因为"标准"而选择布局 — 始终确认。用户是创意总监。

**冲突表面**：当 GDD 需求和可用屏幕空间冲突时，表面冲突并提供解决选项。永远不要静默删除需求。永远不要静默扩展布局而不标记它。

**永远不要** 自动生成完整规范并将其作为既成事实呈现。
**永远不要** 在没有用户批准的情况下写入阶段。
**永远不要** 在没有标记冲突的情况下与现有批准的 UX 规范相矛盾。
**始终** 显示决策的来源（GDD 需求、玩家旅程、用户选择）。

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

---

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
