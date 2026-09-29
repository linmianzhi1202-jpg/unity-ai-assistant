---
name: create-stories
description: 创建故事 — 将史诗分解为可操作任务，创建用户故事
version: 0.3.0
category: game-development
whenToUse: >
  当需要创建故事技能时使用。
  处理将史诗分解为可操作任务、创建用户故事相关任务时。
  支持参数：[epic-slug]（史诗名称）、production/epics/[name]/EPIC.md（完整路径）。
input:
  - 项目根目录路径（默认当前工作区）
  - 史诗路径参数：[epic-slug] 或完整路径
output:
  - 结构化结果报告（Markdown 格式）
  - production/epics/[epic-slug]/story-NNN-[slug].md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 创建故事技能

## 技能概述

将史诗分解为可操作任务，创建用户故事。

故事是单个可实现的任务 — 足够小可以在一个专注的会话中完成，并且完全可追溯到 GDD 需求和 ADR 决策。故事是开发人员领取的工作单元。史诗是架构师定义的。

**每个史诗运行此技能一次**，不是每层一次。优先为基础史诗运行，然后是 Core，以此类推 — 匹配依赖顺序。

**输出：** `production/epics/[epic-slug]/story-NNN-[slug].md` 文件

**前一步骤：** `/create-epics [system]`

**故事存在后的下一步：** `/story-readiness [story-path]` 然后 `/dev-story [story-path]`

## 使用方式

- 通过 Agent 触发：当用户说「创建故事」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill create-stories [参数]`

---

## 阶段 1：解析参数

提取 `--review [full|lean|solo]`（如果存在）并存储为此运行的审查模式覆盖。如果未提供，读取 `production/review-mode.txt`（如果缺失，默认为 `full`）。此解析的模式应用于此技能中的所有门控生成 —— 在每次门控调用之前应查阅 `.claude/docs/director-gates.md` 的检查模式。

- `/create-stories [epic-slug]` — 例如 `/create-stories combat`
- `/create-stories production/epics/combat/EPIC.md` — 也接受完整路径
- 无参数 — 询问："您想将哪个史诗分解为故事？"

搜索 `production/epics/*/EPIC.md` 并列出可用的史诗及其状态。

---

## 阶段 2：为此史诗加载所有内容

完整读取：

- `production/epics/[epic-slug]/EPIC.md` — 史诗概述、管辖 ADR、GDD 需求表
- 史诗的 GDD（`design/gdd/[filename].md`）— 读取所有 8 个部分，特别是验收标准、公式和边缘情况
- 史诗中列出的所有管辖 ADR — 读取决策、实施指南、引擎兼容性、引擎笔记部分
- `docs/architecture/control-manifest.md` — 提取此史诗层的规则；注意标头中的清单版本日期
- `docs/architecture/tr-registry.yaml` — 加载此系统的所有 TR-ID

**ADR 存在验证**：从史诗中读取管辖 ADR 列表后，确认每个 ADR 文件在磁盘上存在。如果任何 ADR 文件无法找到，**立即停止** 在分解任何故事之前：

> "史诗引用 [ADR-NNN: title] 但 `docs/architecture/[adr-file].md` 未找到。
> 检查史诗的管辖 ADR 列表中的文件名，或运行 `/architecture-decision`
> 创建它。在所有引用的 ADR 文件存在之前，无法创建故事。"

在继续阶段 3 之前，不要继续，直到所有引用的 ADR 文件确认为存在。

报告："已加载史诗 [名称]、GDD [filename]、[N] 个管辖 ADR（全部确认为存在）、清单版本 [日期]。"

---

## 阶段 3：按类型分类故事

**故事类型分类** — 根据验收标准分配每个故事一个类型：

| 故事类型 | 当标准引用时分配... |
|---|---|
| **Logic（逻辑）** | 公式、数值阈值、状态转换、AI 决策、计算 |
| **Integration（集成）** | 两个或多个系统交互、信号跨边界、保存/加载往返 |
| **Visual/Feel（视觉/感觉）** | 动画行为、VFX、"感觉响应迅速"、时机、屏幕震动、音频同步 |
| **UI** | 菜单、HUD 元素、按钮、屏幕、对话栏、工具提示 |
| **Config/Data（配置/数据）** | 平衡调整值、仅数据文件更改 — 无新代码逻辑 |

混合故事：分配承担最高实现风险的类型。

类型决定在 `/story-done` 可以关闭故事之前需要什么测试证据。

---

## 阶段 4：将 GDD 分解为故事

对于每个 GDD 验收标准：

1. 将需要相同核心实现的相关标准分组
2. 每个组 = 一个故事
3. 排序故事：基础行为先，边缘情况最后，UI 最后

**故事拆分规则：** 每个故事 = 一个专注的会话（约 2-4 小时）。如果一组标准需要更长时间，拆分为两个故事。

对于每个故事，确定：

- **GDD 需求**：它满足哪个（些）验收标准？
- **TR-ID**：在 `tr-registry.yaml` 中查找。使用稳定的 ID。如果不匹配，使用 `TR-[system]-???` 并警告。
- **管辖 ADR**：哪个 ADR 管辖如何实现这个？
  - `Status: Accepted` → 正常嵌入
  - `Status: Proposed` → 设置故事 `Status: Blocked` 并注释："BLOCKED: ADR-NNN is Proposed — run `/architecture-decision` to advance it"
- **故事类型**：来自阶段 3 分类
- **引擎风险**：来自 ADR 的 Knowledge Risk 字段

---

## 阶段 4b：QA 负责故事准备就绪门控

**审查模式检查** —— 在生成 QL-STORY-READY 之前应用：
- `solo` → 跳过。注意："QL-STORY-READY 跳过 — 单独模式。" 继续阶段 5（展示故事供审查）。
- `lean` → 跳过（不是 PHASE-GATE）。注意："QL-STORY-READY 跳过 — Lean 模式。" 继续阶段 5（展示故事供审查）。
- `full` → 正常生成。

分解所有故事（阶段 4 完成）但在展示它们供写入批准之前，通过 Task 使用门控 **QL-STORY-READY**（`.claude/docs/director-gates.md`）生成 `qa-lead`：

传递：完整故事列表（带验收标准、故事类型、TR-ID）、史诗的 GDD 验收标准供参考。

展示 QA 负责的评估。对于每个标记为 GAPS 或 INADEQUATE 的故事，在继续之前修订验收标准 —— 具有不可测试标准的故事无法正确实现。一旦所有故事达到 ADEQUATE，继续。

**在 ADEQUATE 之后**：对于每个 Logic 和 Integration 故事，要求 qa-lead 产生具体的测试用例规范 —— 每个验收标准一个 —— 使用此格式：

```
Test: [criterion text]
  Given: [pre-condition]
  When: [action]
  Then: [expected result / assertion]
  Edge cases: [boundary values or failure states to test]
```

对于 Visual/Feel 和 UI 故事，改为产生手动验证步骤：

```
Manual check: [criterion text]
  Setup: [how to reach the state]
  Verify: [what to look for]
  Pass condition: [unambiguous pass description]
```

这些测试用例规范直接嵌入到每个故事的 `## QA Test Cases` 部分。开发人员针对这些案例实现。程序员不需要从头编写测试 —— QA 已经定义了"完成"看起来像什么。

---

## 阶段 5：展示故事供审查

在写入任何文件之前，展示完整故事列表：

```
## 史诗的故事：[名称]

故事 001: [标题] — Logic — ADR-NNN
  覆盖：TR-[system]-001 ([需求 1 行摘要])
  需要的测试：tests/unit/[system]/[slug]_test.[ext]

故事 002: [标题] — Integration — ADR-MMM
  覆盖：TR-[system]-002, TR-[system]-003
  需要的测试：tests/integration/[system]/[slug]_test.[ext]

故事 003: [标题] — Visual/Feel — ADR-NNN
  覆盖：TR-[system]-004
  需要的证据：production/qa/evidence/[slug]-evidence.md

[N 个故事总数：N 个 Logic，N 个 Integration，N 个 Visual/Feel，N 个 UI，N 个 Config/Data]
```

使用询问用户：

- 提问："我可以将这 [N] 个故事写入到 `production/epics/[epic-slug]/` 吗？"
- 选项：`[A] 是 — 写入所有 [N] 个故事` / `[B] 还不行 — 我想先审查或调整`

---

## 阶段 6：写入故事文件

对于每个故事，写入 `production/epics/[epic-slug]/story-[NNN]-[slug].md`：

```markdown
# 故事 [NNN]: [标题]

> **史诗**：[史诗名称]
> **状态**：Ready
> **层**：[Foundation / Core / Feature / Presentation]
> **类型**：[Logic | Integration | Visual/Feel | UI | Config/Data]
> **清单版本**：[来自 control-manifest.md 标头的日期]

## 上下文

**GDD**：`design/gdd/[filename].md`
**需求**：`TR-[system]-NNN`
*（需求文本位于 `docs/architecture/tr-registry.yaml` — 在审查时重新读取）*

**管辖 ADR**：[ADR-NNN: title]
**ADR 决策摘要**：[ADR 决定的 1-2 句摘要]

**引擎**：[名称 + 版本] | **风险**：[LOW / MEDIUM / HIGH]
**引擎笔记**：[来自 ADR 引擎兼容性部分 — 截断后 API、需要验证]

**控制清单规则（此层）**：
- 必需：[相关必需模式]
- 禁止：[相关禁止模式]
- 防护栏：[相关性能防护栏]

---

## 验收标准

*来自 GDD `design/gdd/[filename].md`，限定为此故事：*

- [ ] [标准 1 — 直接来自 GDD]
- [ ] [标准 2]
- [ ] [性能标准（如果适用）]

---

## 实施笔记

*派生自 ADR-NNN 实施指南：*

[来自 ADR 的具体、可操作的指导。不要以改变含义的方式改述。这是程序员阅读的，不是 ADR。]

---

## 范围外

*由相邻故事处理 — 不要在此处实现：*

- [故事 NNN+1]: [它处理的内容]

---

## QA 测试用例

*由 qa-lead 在故事创建时编写。程序员针对这些实现 — 不要在实施期间发明新的测试用例。*

**[对于 Logic / Integration 故事 — 自动化测试规范]：**

- **AC-1**: [标准文本]
  - Given: [前提条件]
  - When: [操作]
  - Then: [断言之结果]
  - Edge cases: [边界值 / 失败状态]

**[对于 Visual/Feel / UI 故事 — 手动验证步骤]：**

- **AC-1**: [标准文本]
  - Setup: [如何达到该状态]
  - Verify: [要查找什么]
  - Pass condition: [无歧义的通过描述]

---

## 测试证据

**故事类型**：[类型]
**需要的证据**：
- Logic: `tests/unit/[system]/[story-slug]_test.[ext]` — 必须存在并通过
- Integration: `tests/integration/[system]/[story-slug]_test.[ext]` OR playtest doc
- Visual/Feel: `production/qa/evidence/[story-slug]-evidence.md` + sign-off
- UI: `production/qa/evidence/[story-slug]-evidence.md` or interaction test
- Config/Data: smoke check pass (`production/qa/smoke-*.md`)

**状态**：[ ] 尚未创建

---

## 依赖关系

- 依赖于：[故事 NNN-1 必须为 DONE，或"None"]
- 解锁：[故事 NNN+1，或"None"]
```

### 也更新 `production/epics/[epic-slug]/EPIC.md`

替换"故事：尚未创建"行为填充的表格：

```markdown
## 故事

| # | 故事 | 类型 | 状态 | ADR |
|---|-------|------|---------|-----|
| 001 | [标题] | Logic | Ready | ADR-NNN |
| 002 | [标题] | Integration | Ready | ADR-MMM |
```

---

## 阶段 7：写入后

使用询问用户以上下文感知的下一步关闭：

检查：
- `production/epics/` 中是否有其他史诗还没有故事？列出它们。
- 这是最后一个史诗吗？如果是，将 `/sprint-plan` 作为选项包含。

小部件：
- 提问："[N] 个故事已写入到 `production/epics/[epic-slug]/`。接下来什么？"
- 选项（包含所有适用的）：
  - `[A] 开始实现 — 运行 /story-readiness [first-story-path]`（推荐）
  - `[B] 为 [next-epic-slug] 创建故事 — 运行 /create-stories [slug]`（仅当其他史诗还没有故事时）
  - `[C] 规划 sprint — 运行 /sprint-plan`（仅当所有史诗都有故事时）
  - `[D] 在此会话停止此处`

在输出中注释："按顺序处理故事 — 每个故事的 `依赖于：` 字段告诉您在可以开始之前必须完成什么。"

---

## 协作协议

1. **在展示之前读取** — 在展示故事列表之前静默加载所有输入
2. **询问一次** — 在一个摘要中展示史诗的所有故事，而不是一次一个
3. **在阻塞故事上警告** — 在写入之前标记任何具有 Proposed ADR 的故事
4. **在写入之前询问** — 在写入任何文件之前获得完整故事集的批准
5. **无发明** — 验收标准来自 GDD、实施笔记来自 ADR、规则来自清单
6. **永远不要开始实现** — 此技能在故事文件级别停止

写入（或拒绝）后：

- **裁决：COMPLETE** — [N] 个故事已写入到 `production/epics/[epic-slug]/`。运行 `/story-readiness` → `/dev-story` 开始实现。
- **裁决：BLOCKED** — 用户拒绝。没有故事文件被写入。

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
| **0.3.0** | 2026-04-27 | 修复 whenToUse 格式，清理乱码字符，升级版本号 |
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
