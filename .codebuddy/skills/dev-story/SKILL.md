---
name: dev-story
description: 开发故事 — 实施引导，逐故事实现，包含代码审查和测试
version: 0.2.0
category: game-development
whenToUse: |
  当需要通过开发故事技能实施故事时使用。
  处理实施引导、逐故事实现、包含代码审查和测试相关任务时。
  支持参数：故事文件路径（如 /dev-story production/epics/foundation/story-player-movement.md）
  或无参数（自动检测 active.md 中的活跃故事）。
input:
  - 项目根目录路径（默认当前工作区）
  - 故事文件路径参数
output:
  - 源代码 + 测试文件在项目的 src/ 和 tests/ 目录中
  - 实施摘要报告
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 开发故事技能

## 技能概述

本技能连接规划和代码。它完整读取故事文件，组装程序员所需的所有上下文，路由到正确的专家代理，并推动实施完成 — 包括编写测试。

**每个故事的循环：**
```
/qa-plan sprint           ← 在冲刺开始之前定义测试需求
/story-readiness [path]   ← 在开始之前验证
/dev-story [path]         ← 实施它（本技能）
/code-review [files]      ← 审查它
/story-done [path]        ← 验证并关闭它
```

**在所有冲刺故事完成后：** 运行 `/team-qa sprint` 执行完整 QA 周期并在推进项目阶段之前获得签字判定。

**输出：** 项目 `src/` 和 `tests/` 目录中的源代码 + 测试文件。

---

## 阶段 1：查找故事

**如果提供了路径**：直接读取该文件。

**如果没有参数**：检查 `production/session-state/active.md` 中的活跃故事。如果找到，确认："继续在 [故事标题] 上工作 — 这是正确的吗？"

如果未找到，询问："我们正在实施哪个故事？" Glob `production/epics/**/*.md` 并列出状态为 Ready 的故事。

---

## 阶段 2：加载完整上下文

**在加载任何上下文之前，验证必需文件存在。** 从故事的 `ADR Governing Implementation` 字段提取 ADR 路径，然后检查：

| 文件 | 路径 | 如果缺失 |
|------|------|------------|
| TR 注册表 | `docs/architecture/tr-registry.yaml` | **停止** — "未找到 TR 注册表。运行 `/create-epics` 生成它。" |
| 管辖 ADR | 故事 ADR 字段中的路径 | **停止** — "未找到 ADR 文件 [路径]。运行 `/architecture-decision` 创建它，或更正故事 ADR 字段中的文件名。" |
| 控制清单 | `docs/architecture/control-manifest.md` | **警告并继续** — "未找到控制清单 — 无法检查层规则。运行 `/create-control-manifest`。" |

如果 TR 注册表或管辖 ADR 缺失，将故事状态设置为会话状态中的 **BLOCKED**，并且不生成任何程序员代理。

同时读取以下内容 — 这些是独立读取。在实现开始之前不要开始实施，直到所有上下文加载完成：

### 故事文件
提取并保留：
- **故事标题、ID、层、类型**（Logic / Integration / Visual/Feel / UI / Config/Data）
- **TR-ID** — GDD 需求标识符
- **管辖 ADR** 引用
- **清单版本** 嵌入在故事标头中
- **验收标准** — 每个复选框项目，逐字记录
- **实施说明** — 故事中的 ADR 指导部分
- **范围外** 边界
- **测试证据** — 所需的测试文件路径
- **依赖关系** — 在此故事之前必须完成的事项

### TR 注册表
读取 `docs/architecture/tr-registry.yaml`。查找故事的 TR-ID。
读取当前 `requirement` 文本 — 这是 GDD 现在需求的事实来源。不要依赖故事文件中的任何内联文本（可能是陈旧的）。

### 管辖 ADR
读取 `docs/architecture/[adr-file].md`。提取：
- 完整 Decision 部分
- Implementation Guidelines 部分（这是程序员遵循的内容）
- Engine Compatibility 部分（截止后 API、已知风险）
- ADR Dependencies 部分

### 控制清单
读取 `docs/architecture/control-manifest.md`。提取此故事层的规则：
- 必需模式
- 禁止模式
- 性能防护栏

检查：故事的嵌入清单版本是否与当前清单标头日期匹配？
如果它们不同，在继续之前使用 `AskUserQuestion`：
- 提示："故事是针对清单 v[故事日期] 编写的。当前清单是 v[当前日期]。可能适用新规则。您要如何继续？"
- 选项：
  - `[A] 更新故事清单版本并使用当前规则实施（推荐）`
  - `[B] 使用旧规则实施 — 我接受不合规的风险`
  - `[C] 在此停止 — 我想首先审查清单差异`
  
如果 [A]：在生成程序员之前，将故事文件的 `Manifest Version:` 字段编辑为当前清单日期。然后仔细读取清单以了解新规则。
如果 [B]：仍然仔细读取清单以了解新规则，并在阶段 6 摘要中的"偏差"下注意版本不匹配。
如果 [C]：停止。不生成任何代理。让用户审查并重新运行 `/dev-story`。

### 依赖关系验证

从故事文件中提取 **依赖关系** 列表后，验证每个：

1. Glob `production/epics/**/*.md` 以查找每个依赖故事文件。
2. 读取其 `Status:` 字段。
3. 如果任何依赖关系具有除 `Complete` 或 `Done` 之外的状态：
   - 使用 `AskUserQuestion`：
     - 提示："故事 '[当前故事]' 依赖于 '[依赖关系标题]'，其当前状态为 [状态]，而不是 Complete。您要如何继续？"
     - 选项：
       - `[A] 无论如何继续 — 我接受依赖关系风险`
       - `[B] 在此停止 — 我将首先完成依赖关系`
       - `[C] 依赖关系已完成但状态未更新 — 将其标记为 Complete 并继续`
     - 如果 [B]：将会话状态中的故事状态设置为 **BLOCKED** 并停止。不生成任何程序员代理。
     - 如果 [C]：在继续之前询问"我可以更新 [依赖关系路径] 状态为 Complete 吗？"。
     - 如果 [A]：在阶段 6 摘要中的"偏差"下注意："使用不完整的依赖关系实施：[依赖关系标题] — [状态]。"

如果找不到依赖关系文件：警告"未找到依赖故事：[路径]。验证路径或创建故事文件。"

---

### 引擎引用
读取 `.claude/docs/technical-preferences.md`：
- `Engine:` 值 — 确定要使用哪些程序员代理
- 命名约定（类名、文件名、信号/事件名）
- 性能预算（帧预算、内存上限）
- 禁止模式

---

## 阶段 3：路由到正确的程序员

根据故事的 **层**、**类型** 和 **系统名称**，确定要通过 Task 生成哪个专家。

**Config/Data 故事 — 完全跳过代理生成：**
如果故事的类型是 `Config/Data`，不需要程序员代理或引擎专家。直接跳到阶段 4（Config/Data 注释）。实施是数据文件编辑 — 无路由表评估，无引擎专家。

### 主要代理路由表

| 故事上下文 | 主要代理 |
|---|---|
| 基础层 — 任何类型 | `engine-programmer` |
| 任何层 — 类型：UI | `ui-programmer` |
| 任何层 — 类型：Visual/Feel | `gameplay-programmer`（实施） |
| 核心或功能 — 游戏玩法机制 | `gameplay-programmer` |
| 核心或功能 — AI 行为、路径查找 | `ai-programmer` |
| 核心或功能 — 网络、复制 | `network-programmer` |
| Config/Data — 无代码 | 不需要代理（参见阶段 4 Config 注释） |

### 引擎专家 — 始终作为代码故事的辅助生成

读取 `.claude/docs/technical-preferences.md` 的 `Engine Specialists` 部分以获取配置的主要专家。当故事涉及引擎特定 API、模式或 ADR 具有高风险引擎风险时，与主要代理一起生成它们。

| 引擎 | 可用专家代理 |
|--------|----------------------------|
| Godot 4 | `godot-specialist`、`godot-gdscript-specialist`、`godot-shader-specialist` |
| Unity | `unity-specialist`、`unity-ui-specialist`、`unity-shader-specialist` |
| Unreal Engine | `unreal-specialist`、`ue-gas-specialist`、`ue-blueprint-specialist`、`ue-umg-specialist`、`ue-replication-specialist` |

**当引擎风险为 HIGH 时**（来自 ADR 或 VERSION.md）：始终生成引擎专家，即使对于非引擎面向的故事。高风险意味着 ADR 记录关于截止后引擎 API 的假设，需要专家验证。

---

## 阶段 4：实施

通过 Task 使用完整上下文包生成所选的程序员代理：

向代理提供：
1. 完整故事文件内容
2. 当前 GDD 需求文本（来自 TR 注册表）
3. ADR Decision + Implementation Guidelines（逐字 — 不要总结）
4. 此层的控制清单规则
5. 引擎命名约定和性能预算
6. 来自 ADR 引擎兼容性部分的任何引擎特定注释
7. 必须创建的测试文件路径
8. 显式指令：**实施此故事并编写测试**

代理应该：
- 按照 ADR 指导在 `src/` 中创建或修改文件
- 尊重来自控制清单的所有必需和禁止模式
- 保持在故事的"范围外"边界内（不要触及不相关的文件）
- 编写干净的、有文档注释的公共 API

### Config/Data 故事（不需要代理）

对于类型：Config/Data 故事，不需要程序员代理。实施是编辑数据文件。读取故事的验收标准并直接对数据文件进行指定的更改。注意哪些值已更改以及它们从/到什么。

### Visual/Feel 故事

生成 `gameplay-programmer` 实施代码/动画调用。注意"感觉对吗？"检查发生在 `/story-done` 中通过手动确认。

---

## 阶段 5：编写测试

对于 **Logic** 和 **Integration** 故事，测试必须作为此实施的一部分编写 — 不延迟到以后。

提醒程序员代理：

> "此故事的测试文件要求在：[Test Evidence 部分中的路径]。
> 没有它，故事无法通过 `/story-done` 关闭。与实施一起编写测试，
> 而不是之后。"

测试需求（来自 coding-standards.md）：
- 文件名：`[system]_[feature]_test.[ext]`
- 函数名：`test_[scenario]_[expected_outcome]`
- 每个验收标准必须至少有一个测试函数覆盖它
- 无随机种子、无时间相关断言、无外部 I/O
- 测试 GDD 公式部分中的公式边界

对于 **Visual/Feel** 和 **UI** 故事：无自动测试。提醒代理在實施摘要中注意需要哪些手动证据：
"证据文档要求在 `production/qa/evidence/[slug]-evidence.md`。"

对于 **Config/Data** 故事：无测试文件。冒烟检查将作为证据。

---

## 阶段 6：收集并总结

在程序员代理完成之后，收集：

- 创建或修改的文件（带路径）
- 创建的测试文件（路径和编写的测试函数数量）
- 来自故事"范围外"边界的任何偏差（标记这些）
- 代理提出的任何问题或阻塞项
- 专家标记的任何引擎特定风险

呈现简洁的实施摘要：

```
## 实施完成：[故事标题]

**更改的文件**：
- `src/[路径]` — 创建 / 修改（[简要描述]）
- `tests/[路径]` — 测试文件（[N] 个测试函数）

**验收标准覆盖**：
- [x] [标准] — 在 [文件:函数] 中实施
- [x] [标准] — 由测试 [测试名称] 覆盖
- [ ] [标准] — 延迟：需要试玩测试（Visual/Feel）

**与范围的偏差**：[无] 或 [在故事边界外触及的文件列表]
**引擎风险标记**：[无] 或 [专家发现]
**阻塞项**：[无] 或 [描述]

准备好：/code-review [文件1] [文件2] 然后 /story-done [故事路径]
```

---

## 阶段 7：更新会话状态

静默附加到 `production/session-state/active.md`：

```
## 会话提取 — /dev-story [日期]
- 故事：[故事路径] — [故事标题]
- 更改的文件：[逗号分隔列表]
- 编写的测试：[路径，或 "无 — Visual/Feel/Config 故事"]
- 阻塞项：[无，或描述]
- 下一步：/code-review [文件] 然后 /story-done [故事路径]
```

如果 `active.md` 不存在，创建它。确认："会话状态已更新。"

---

## 错误恢复协议

如果任何生成的代理（通过 Task）返回 BLOCKED、错误或超过令牌限制：

1. **立即呈现**：在继续到依赖阶段之前向用户报告 "[代理名称]：BLOCKED — [原因]"
2. **评估依赖关系**：检查被阻塞代理的输出是否由后续阶段需要。如果是，在没有用户输入的情况下不要超过该依赖点。
3. **提供选项** 通过带有选择的 AskUserQuestion：
   - 跳过此代理并注意最终报告中的缺口
   - 使用较窄的范围重试
   - 在此停止并首先解决阻塞项
4. **始终生成部分报告** — 输出任何已完成的内容。永远不要因为一个代理被阻塞而丢弃工作。

常见阻塞项：
- 输入文件缺失（未找到故事、GDD 缺失）→ 重定向到创建它的技能
- ADR 状态是 Proposed → 不要实施；首先运行 `/architecture-decision`
- 范围太大 → 通过 `/create-stories` 拆分为两个故事
- ADR 与故事之间的指令冲突 → 呈现冲突，不要猜测
- 清单版本不匹配 → 向用户显示差异，询问是继续旧规则还是首先更新故事

## 协作协议

- **文件写入被委托** — 所有源代码、测试文件和证据文档由通过 Task 生成的子代理编写。每个子代理单独强制执行"我可以写入 [路径]？"协议。此编排器不直接写入文件。
- **在实施之前加载** — 不要在所有上下文加载之前开始编码（故事、TR-ID、ADR、清单、引擎偏好）。不完整的上下文产生与设计漂移的代码。
- **ADR 是法律** — 实施必须遵循 ADR 的 Implementation Guidelines。如果指导与看似"更好"的东西冲突，在摘要中标记它而不是静默偏离。
- **保持在范围内** — "范围外"部分是一个契约。如果实施故事需要触及范围外的文件，停止并呈现它：
  "实施 [标准] 需要修改 [文件]，这在范围外。我应该继续还是创建单独的故事？"
- **测试和 Logic/Integration 不是可选的** — 没有测试文件存在就不要将实施标记为完成
- **Visual/Feel 标准被延迟，而不是跳过** — 在摘要中将它们标记为 DEFERRED；它们将在 `/story-done` 中手动验证
- **在大型结构决策之前询问** — 如果故事需要 ADR 未涵盖的架构模式，在实施之前呈现它：
  "ADR 未指定如何处理 [案例]。我的计划是 [X]。继续吗？"

---

## 推荐的下一步

- 运行 `/code-review [文件1] [文件2]` 在关闭故事之前审查实施
- 运行 `/story-done [故事路径]` 验证验收标准并将故事标记为完成
- 在所有冲刺故事完成后：在推进项目阶段之前运行 `/team-qa sprint` 进行完整 QA 周期

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 完整中文化，删除"原始英文提示词"部分，修复 whenToUse 字段 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
