---
name: gate-check
description: 门控检查 — 阶段门控，验证准备情况，防止不合格工作流向下游
version: 0.2.0
category: game-development
whenToUse: |
  当需要通过门控检查技能验证项目是否准备好进入下一开发阶段时使用。
  处理阶段门控、验证准备情况、防止不合格工作流向下游相关任务时。
  支持参数：无参数（自动检测当前阶段并验证下一次转换）、有参数（指定目标阶段，如 `/gate-check production`）。
  审查模式：--review [full|lean|solo] 或无标志（默认 lean）。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标阶段参数（如 production、polish、release 等）
output:
  - 结构化门控检查报告（Markdown 格式）
  - production/gate-checks/ 目录下的报告文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 门控检查技能

## 技能概述

本技能验证项目是否准备好进入下一开发阶段。它检查必需的制品、质量标准和阻塞项。

**与 `/project-stage-detect` 的区别**：该技能是诊断性的（"我们在哪里？"）。本技能是规范性的（"我们准备好前进了吗？"，带有正式的判定结论）。

## 使用方式

- 通过 Agent 触发：当用户说「门控检查」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/gate-check [阶段名称]` 或 `skill gate-check [阶段名称]`

## 生产阶段（7 个）

项目通过这些阶段推进：

1. **概念（Concept）** — 头脑风暴、游戏概念文档
2. **系统设计（Systems Design）** — 映射系统、编写 GDD
3. **技术设置（Technical Setup）** — 引擎配置、架构决策
4. **预生产（Pre-Production）** — 原型制作、垂直切片验证
5. **生产（Production）** — 功能开发（Epic/Feature/Task 跟踪活跃）
6. **打磨（Polish）** — 性能、试玩测试、Bug 修复
7. **发布（Release）** — 发布准备、认证

**当门控通过时**，将新阶段名称写入 `production/stage.txt`（单行，例如 `Production`）。这立即更新状态行。

---

## 1. 解析参数

**目标阶段：** `$ARGUMENTS[0]`（空白 = 自动检测当前阶段，然后验证下一次转换）

同时解析审查模式（一次性，为此运行中的所有门控生成存储）：
1. 如果传递了 `--review [full|lean|solo]` → 使用那个值
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认为 `lean`

注意：在 `solo` 模式下，总监生成（CD-PHASE-GATE、TD-PHASE-GATE、PR-PHASE-GATE、AD-PHASE-GATE）被跳过 — 门控检查变为仅制品存在性检查。在 `lean` 模式下，所有四个总监仍然运行（阶段门控是 lean 模式的目的）。

- **带参数**：`/gate-check production` — 验证该特定阶段的准备情况
- **无参数**：使用与 `/project-stage-detect` 相同的启发式方法自动检测当前阶段，然后在运行前**与用户确认**：

  使用 `AskUserQuestion`：
  - 提示："检测到的阶段：** [当前阶段] **。正在运行 [当前] → [下一] 转换的门控。这是正确的吗？"
  - 选项：
    - `[A] 是 — 运行此门控`
    - `[B] 否 — 选择不同的门控`（如果选择，显示第二个窗口部件列出所有门控选项：Concept → Systems Design、Systems Design → Technical Setup、Technical Setup → Pre-Production、Pre-Production → Production、Production → Polish、Polish → Release）
  
  当未提供参数时，不要跳过此确认步骤。

---

## 2. 阶段门控定义

### 门控：概念 → 系统设计

**必需制品：**
- [ ] `design/gdd/game-concept.md` 存在且有内容
- [ ] 游戏支柱已定义（在概念文档或 `design/gdd/game-pillars.md` 中）
- [ ] `design/gdd/game-concept.md` 中存在视觉识别锚点部分（来自 brainstorm 阶段 4 art-director 输出）

**质量检查：**
- [ ] 游戏概念已被审查（`/design-review` 判定不是 MAJOR REVISION NEEDED）
- [ ] 核心循环已被描述和理解
- [ ] 目标受众已确定

---

### 门控：系统设计 → 技术设置

**必需制品：**
- [ ] 系统索引存在于 `design/gdd/systems-index.md`，至少枚举了 MVP 系统
- [ ] 所有 MVP 级 GDD 存在于 `design/gdd/` 中并单独通过 `/design-review`
- [ ] 交叉 GDD 审查报告存在于 `design/gdd/`（来自 `/review-all-gdds`）

**质量检查：**
- [ ] 所有 MVP GDD 通过单独设计审查（8 个必需部分，无 MAJOR REVISION NEEDED 判定）
- [ ] `/review-all-gdds` 判定不是 FAIL（交叉 GDD 一致性和设计理论检查通过）
- [ ] `/review-all-gdds` 标记的所有交叉 GDD 一致性问题已解决或明确接受
- [ ] 系统依赖关系已在系统索引中映射并且是双向一致的
- [ ] MVP 优先级层已定义
- [ ] 无标记的陈旧 GDD 引用（较旧的 GDD 已更新以反映后来 GDD 中的决策）

---

### 门控：技术设置 → 预生产

**必需制品：**
- [ ] 引擎已选择（CLAUDE.md 技术栈不是 `[CHOOSE]`）
- [ ] 技术偏好已配置（`.claude/docs/technical-preferences.md` 已填充）
- [ ] 艺术圣经存在于 `design/art/art-bible.md`，至少包含第 1-4 节（视觉识别基础）
- [ ] `docs/architecture/` 中至少存在 3 个架构决策记录，涵盖基础层系统（场景管理、事件架构、保存/加载）
- [ ] 引擎参考文档存在于 `docs/engine-reference/[engine]/`
- [ ] 测试框架已初始化：`tests/unit/` 和 `tests/integration/` 目录存在
- [ ] CI/CD 测试工作流存在于 `.github/workflows/tests.yml`（或等效文件）
- [ ] 至少一个示例测试文件存在以确认框架功能正常
- [ ] 主架构文档存在于 `docs/architecture/architecture.md`
- [ ] 架构可追溯性索引存在于 `docs/architecture/architecture-traceability.md`
- [ ] `/architecture-review` 已运行（审查报告文件存在于 `docs/architecture/`）
- [ ] `design/accessibility-requirements.md` 存在，可访问性层级已承诺
- [ ] `design/ux/interaction-patterns.md` 存在（模式库已初始化，即使是最小的）

**质量检查：**
- [ ] 架构决策涵盖核心系统（渲染、输入、状态管理）
- [ ] 技术偏好已设置命名约定和性能预算
- [ ] 可访问性层级已定义并记录（即使是"基础"也是可接受的 — 未定义是不可接受的）
- [ ] 至少一个屏幕的 UX 规范已启动（通常在技术设置期间设计主菜单或核心 HUD）
- [ ] 所有 ADR 都有**引擎兼容性部分**，带有引擎版本标记
- [ ] 所有 ADR 都有**GDD 需求寻址部分**，带有明确的 GDD 链接
- [ ] 无 ADR 引用 `docs/engine-reference/[engine]/deprecated-apis.md` 中列出的 API
- [ ] 所有高风险引擎域（根据 VERSION.md）已在架构文档中显式寻址，或标记为开放问题
- [ ] 架构可追溯性矩阵有**零个基础层缺口**（所有基础需求必须在预生产之前有 ADR 覆盖）

**ADR 循环依赖检查**：对于 `docs/architecture/` 中的所有 ADR，读取每个 ADR 的"ADR Dependencies" / "Depends On" 部分。构建依赖关系图（ADR-A → ADR-B 意味着 A 依赖于 B）。如果检测到任何循环（例如 A→B→A 或 A→B→C→A）：
- 标记为 **FAIL**："循环 ADR 依赖关系：[ADR-X] → [ADR-Y] → [ADR-X]。在循环存在的情况下，两者都无法达到 Accepted。移除一个 'Depends On' 边以打破循环。"

**引擎验证**（首先读取 `docs/engine-reference/[engine]/VERSION.md`）：
- [ ] 触及截止后引擎 API 的 ADR 被标记为知识风险：HIGH/MEDIUM
- [ ] `/architecture-review` 引擎审计显示无弃用 API 使用
- [ ] 所有 ADR 同意相同的引擎版本（无陈旧版本引用）

---

### 门控：预生产 → 生产

**必需制品：**
- [ ] `prototypes/` 中至少有一个原型，带有 README
- [ ] 第一个冲刺计划存在于 `production/sprints/`
- [ ] 艺术圣经完整（所有 9 个部分），AD-ART-BIBLE 签字判定已记录在 `design/art/art-bible.md`
- [ ] 叙事文档中引用的关键角色视觉配置文件存在
- [ ] 系统索引中的所有 MVP 级 GDD 已完成
- [ ] 主架构文档存在于 `docs/architecture/architecture.md`
- [ ] `docs/architecture/` 中至少存在 3 个涵盖基础层的 ADR
- [ ] 控制清单存在于 `docs/architecture/control-manifest.md`（由 `/create-control-manifest` 从 Accepted ADR 生成）
- [ ] Epic 定义在 `production/epics/` 中，至少存在基础和核心层 epics（使用 `/create-epics layer: foundation` 和 `/create-epics layer: core` 创建它们，然后对每个 epic 使用 `/create-stories [epic-slug]`）
- [ ] 垂直切片构建存在且可玩（不仅仅是范围定义）
- [ ] 垂直切片已进行至少 3 次试玩测试（内部 OK）
- [ ] 垂直切片试玩报告存在于 `production/playtests/` 或等效位置
- [ ] 关键屏幕的 UX 规范存在：主菜单、核心游戏玩法 HUD（在 `design/ux/`），暂停菜单
- [ ] HUD 设计文档存在于 `design/ux/hud.md`（如果游戏有内置 HUD）
- [ ] 所有关键屏幕 UX 规范已通过 `/ux-review`（判定 APPROVED 或 NEEDS REVISION 已接受）

**质量检查：**
- [ ] **核心循环乐趣已验证** — 试玩数据确认核心机制是令人愉快的，不仅仅是功能性的。显式检查垂直切片试玩报告。
- [ ] UX 规范涵盖所有 MVP 级 GDD 的 UI 需求部分
- [ ] 交互模式库记录了关键屏幕中使用的模式
- [ ] 所有关键屏幕 UX 规范中的可访问性层级（来自 `design/accessibility-requirements.md`）已寻址
- [ ] 冲刺计划引用来自 `production/epics/` 的真实故事文件路径（不仅仅是 GDD — 故事必须嵌入 GDD 需求 ID + ADR 引用）
- [ ] **垂直切片完整**，不仅仅是范围定义 — 构建端到端演示完整核心循环。至少一个完整的 [开始 → 挑战 → 解决] 循环工作。
- [ ] 架构文档在基础或核心层中没有未解决的开放问题
- [ ] 所有 ADR 都有引擎兼容性部分，带有引擎版本标记
- [ ] 所有 ADR 都有 ADR 依赖关系部分（即使所有字段都是"None"）
- [ ] 手动验证确认 GDD + 架构 + epics 是连贯的（如果最近未完成，运行 `/review-all-gdds` 和 `/architecture-review`）
- [ ] **核心幻想已交付** — 至少一个试玩者独立描述了与核心系统 GDD 的玩家幻想部分匹配的经验（在没有提示的情况下）。

**垂直切片验证**（任何项目为 NO 时 FAIL）：
- [ ] 人类已在无开发者指导的情况下玩过核心循环
- [ ] 游戏在游戏的前 2 分钟内传达了要做什么
- [ ] 垂直切片构建中没有关键的"乐趣阻塞" Bug
- [ ] 核心机制感觉良好，可以交互（这是主观检查 — 询问用户）

> **注意**：如果任何垂直切片验证项目是 FAIL，则判定自动为 FAIL，无论其他检查如何。在没有经过验证的垂直切片的情况下前进是游戏开发中生产失败的第一原因（根据来自 155 个项目的 GDC 事后分析数据）。

---

### 门控：生产 → 打磨

**必需制品：**
- [ ] `src/` 有活跃代码组织成子系统
- [ ] 来自 GDD 的所有核心机制已实现（交叉引用 `design/gdd/` 与 `src/`）
- [ ] 主游戏路径可端到端游玩
- [ ] 测试文件存在于 `tests/unit/` 和 `tests/integration/` 中，涵盖 Logic 和 Integration 故事
- [ ] 来自此冲刺的所有 Logic 故事在 `tests/unit/` 中有相应的单元测试文件
- [ ] 冒烟检查已运行，判定为 PASS 或 PASS WITH WARNINGS — 报告存在于 `production/qa/`
- [ ] QA 计划存在于 `production/qa/` 中（由 `/qa-plan` 生成），涵盖此冲刺或最终生产冲刺
- [ ] QA 签字报告存在于 `production/qa/` 中（由 `/team-qa` 生成），判定为 APPROVED 或 APPROVED WITH CONDITIONS
- [ ] `production/playtests/` 中记录了至少 3 个不同的试玩测试会话
- [ ] 试玩报告涵盖：新玩家经验、游戏中系统、难度曲线
- [ ] 游戏概念中的乐趣假设已显式验证或修订

**质量检查：**
- [ ] 测试通过（通过 Bash 运行测试套件）
- [ ] 任何 Bug 跟踪器或已知问题中无关键/阻塞 Bug
- [ ] 核心循环按设计游玩（与 GDD 验收标准比较）
- [ ] 性能在预算内（检查 technical-preferences.md 目标）
- [ ] 试玩发现已审查，关键乐趣问题已寻址（不仅仅是记录）
- [ ] 无"混淆循环"标识 — 游戏中没有任何点让 >50% 的试玩者卡住而不知道为什么
- [ ] 难度曲线与难度曲线设计文档匹配（如果存在 `design/difficulty-curve.md`）
- [ ] 所有实现的屏幕都有相应的 UX 规范（无"在代码中设计"的屏幕）
- [ ] 交互模式库与实现中使用的所有模式保持最新
- [ ] 可访问性合规性根据 `design/accessibility-requirements.md` 中的承诺层级进行验证

---

### 门控：打磨 → 发布

**必需制品：**
- [ ] 里程碑计划中的所有功能已实现
- [ ] 内容完整（设计文档中引用的所有关卡、资产、对话存在）
- [ ] 本地化字符串已外部化（`src/` 中无硬编码的玩家面向文本）
- [ ] QA 测试计划存在（`/qa-plan` 输出在 `production/qa/`）
- [ ] QA 签字报告存在（`/team-qa` 输出 — APPROVED 或 APPROVED WITH CONDITIONS）
- [ ] 所有 Must Have 故事测试证据存在（Logic/Integration：测试文件通过；Visual/Feel/UI：签字文档在 `production/qa/evidence/`）
- [ ] 冒烟检查在候选发布构建上干净地通过（PASS 判定）
- [ ] 自上一个冲刺以来无测试回归（测试套件完全通过）
- [ ] 平衡数据已审查（`/balance-check` 已运行）
- [ ] 发布检查清单已完成（`/release-checklist` 或 `/launch-checklist` 已运行）
- [ ] 商店元数据已准备（如果适用）
- [ ] 变更日志 / 补丁说明已起草

**质量检查：**
- [ ] 完整 QA 传递由 `qa-lead` 签字
- [ ] 所有测试通过
- [ ] 在所有目标平台上达到性能目标
- [ ] 无已知的关键、高或中严重性问题 Bug
- [ ] 可访问性基础已涵盖（按键重映射、文本缩放，如果适用）
- [ ] 所有目标语言的本地化已验证
- [ ] 法律要求已满足（EULA、隐私政策、年龄分级，如果适用）
- [ ] 构建编译和打包干净

---

## 3. 运行门控检查

**在运行制品检查之前**，读取 `docs/consistency-failures.md`（如果存在）。提取其域与目标阶段匹配的项（例如，如果检查系统设计 → 技术设置，提取 Economy、Combat 或任何 GDD 域中的项；如果检查技术设置 → 预生产，提取 Architecture、Engine 域中的项）。将这些作为上下文携带 — 目标域中的重复冲突模式保证对这些特定检查进行更严格的审查。

对于目标门控中的每个项目：

### 制品检查
- 使用 `Glob` 和 `Read` 验证文件存在且有有意义的内容
- 不要只检查存在性 — 验证文件有真实内容（不仅仅是模板标头）
- 对于代码检查，验证目录结构和文件计数

**系统设计 → 技术设置门控 — 交叉 GDD 审查检查**：
使用 `Glob('design/gdd/gdd-cross-review-*.md')` 查找 `/review-all-gdds` 报告。如果没有文件匹配，将"交叉 GDD 审查报告存在"制品标记为 **FAIL** 并突出显示："在 `design/gdd/` 中未找到 `/review-all-gdds` 报告。在前进到技术设置之前运行 `/review-all-gdds`。"如果找到文件，读取它并检查判定行：FAIL 判定意味着交叉 GDD 一致性检查失败，必须在前进之前解决。

### 质量检查
- 对于测试检查：如果配置了测试运行器，通过 `Bash` 运行测试套件
- 对于设计审查检查：`Read` GDD 并检查 8 个必需部分
- 对于性能检查：`Read` technical-preferences.md 并与 `tests/performance/` 或最近的 `/perf-profile` 输出中的任何性能分析数据比较
- 对于本地化检查：`Grep` 搜索 `src/` 中的硬编码字符串

### 交叉引用检查
- 将 `design/gdd/` 文档与 `src/` 实现进行比较
- 检查架构文档中引用的每个系统是否有相应的代码
- 验证冲刺计划引用真实工作项

---

## 4. 协作评估

对于无法自动验证的项目，**询问用户**：

- "我无法自动验证核心循环是否玩起来良好。它已经被试玩测试了吗？"
- "未找到试玩报告。是否已完成非正式测试？"
- "性能分析数据不可用。您想运行 `/perf-profile` 吗？"

**永远不要为无法验证的项目假设 PASS。** 将它们标记为需要手动检查。

---

## 4b. 总监面板评估

在生成最终判定之前，使用 `.claude/docs/director-gates.md` 中的并行门控协议，将所有四个总监作为**并行子代理**通过 Task 生成。同时发出所有四个 Task 调用 — 不要在一个开始之前等待下一个。

**并行生成：**

1. **`creative-director`** — 门控 **CD-PHASE-GATE**（`.claude/docs/director-gates.md`）
2. **`technical-director`** — 门控 **TD-PHASE-GATE**（`.claude/docs/director-gates.md`）
3. **`producer`** — 门控 **PR-PHASE-GATE**（`.claude/docs/director-gates.md`）
4. **`art-director`** — 门控 **AD-PHASE-GATE**（`.claude/docs/director-gates.md`）

向每个传递：目标阶段名称、存在的制品列表以及该门控定义中列出的上下文字段。

**收集所有四个响应，然后呈现总监面板摘要：**

```
## 总监面板评估

创意总监：[READY / CONCERNS / NOT READY]
  [反馈]

技术总监：[READY / CONCERNS / NOT READY]
  [反馈]

制作人：[READY / CONCERNS / NOT READY]
  [反馈]

艺术总监：[READY / CONCERNS / NOT READY]
  [反馈]
```

**应用到判定：**
- 任何总监返回 NOT READY → 判定至少为 FAIL（用户可以显式确认覆盖）
- 任何总监返回 CONCERNS → 判定至少为 CONCERNS
- 所有四个 READY → 有资格获得 PASS（仍受第 3 节中的制品和质量检查约束）

---

## 5. 输出判定

```
## 门控检查：[当前阶段] → [目标阶段]

**日期**：[日期]
**检查者**：gate-check 技能

### 必需制品：[X/Y 存在]
- [x] design/gdd/game-concept.md — 存在，2.4KB
- [ ] docs/architecture/ — 缺失（未找到 ADR）
- [x] production/sprints/ — 存在，1 个冲刺计划

### 质量检查：[X/Y 通过]
- [x] GDD 有 8/8 个必需部分
- [ ] 测试 — 失败（tests/unit/ 中有 3 个失败）
- [?] 核心循环已试玩测试 — 需要手动检查

### 阻塞项
1. **无架构决策记录** — 在进入生产之前运行 `/architecture-decision` 创建一个涵盖核心系统架构的决策。
2. **3 个测试失败** — 在前进之前修复 tests/unit/ 中的失败测试。

### 建议
- [解决阻塞项的优先操作]
- [可选的改进，不阻塞]

### 判定：[PASS / CONCERNS / FAIL]
- **PASS**：所有必需制品存在，所有质量检查通过
- **CONCERNS**：存在轻微缺口，但可以在下一阶段解决
- **FAIL**：必须解决关键阻塞项才能前进
```

---

## 5a. 验证链

在第 5 阶段起草判定后，在最终确定之前挑战它。

**第 1 步 — 生成 5 个挑战问题**，旨在反驳判定：

对于 **PASS** 草案：
- "我通过实际读取文件验证了哪些质量检查，vs. 推断它们通过？"
- "我是否将需要用户确认标记为 PASS 的手动检查项目？"
- "我是否确认所有列出的制品都有真实内容，而不仅仅是空标头？"
- "是否有任何阻塞项我将其淡化为轻微以避免更严格的判定？"
- "哪个检查是我最不自信的，为什么？"

对于 **CONCERNS** 草案：
- "考虑到项目的当前状态，是否有任何列出的 CONCERN 可以提升为阻塞项？"
- "此关切是否可以在下一阶段内解决，还是随着时间的推移而复合？"
- "我是否将任何 FAIL 条件柔化为 CONCERN 以避免更难的判定？"
- "是否有我未检查的可能揭示其他阻塞项的制品？"
- "所有 CONCERN 一起是否创建一个阻塞问题，即使每个单独都是轻微的？"

对于 **FAIL** 草案：
- "我是否准确分离了硬阻塞项和强建议？"
- "是否有任何我过于宽松的 PASS 项目？"
- "我是否遗漏了用户应该知道的任何其他阻塞项？"
- "我能否提供一条通往 PASS 的最小路径 — 必须更改的 3 个具体事项？"
- "失败条件是可解决的，还是表明更深层次的设计问题？"

**第 2 步 — 独立回答每个问题。**
不要引用草案判定文本 — 重新检查特定文件或询问用户。

**第 3 步 — 如果需要则修订：**
- 如果任何回答揭示了错过的阻塞项 → 升级判定（PASS→CONCERNS 或 CONCERNS→FAIL）
- 如果任何回答揭示了过度陈述的阻塞项 → 仅在使用特定证据时降级
- 如果回答一致 → 确认判定不变

**第 4 步 — 在最终报告输出中注意验证**：
`验证链：[N] 个问题已检查 — 判定 [不变 | 从 X 修订为 Y]`

---

## 6. 在 PASS 时更新阶段

当判定为 **PASS** 且用户确认他们要前进时：

1. 将新阶段名称写入 `production/stage.txt`（单行，无尾随换行符）
2. 这立即更新所有未来会话的状态行

示例：如果通过"预生产 → 生产"门控：
```bash
echo -n "Production" > production/stage.txt
```

**在写入之前总是询问**："门控通过。我可以更新 `production/stage.txt` 为 'Production' 吗？"

---

## 7. 关闭下一步窗口部件

在判定呈现并且任何 stage.txt 更新完成之后，使用 `AskUserQuestion` 以结构化的下一步提示关闭。

**根据刚刚运行的门控定制选项：**

对于 **系统设计 PASS**：
```
门控通过。您想接下来做什么？
[A] 运行 /create-architecture — 生成主架构蓝图和 ADR 工作计划（推荐的下一步）
[B] 首先设计更多 GDD — 当所有 MVP 系统完成时返回此处
[C] 在此会话停止
```

> **系统设计 PASS 注意事项**：`/create-architecture` 是在编写任何 ADR 之前必需的下一步。它生成主架构文档和要编写的 ADR 的优先列表。在没有此步骤的情况下运行 `/architecture-decision` 意味着在没有蓝图的情况下编写 ADR — 自担风险跳过它。

对于 **技术设置 PASS**：
```
门控通过。您想接下来做什么？
[A] 开始预生产 — 开始原型制作垂直切片
[B] 首先编写更多 ADR — 运行 /architecture-decision [next-system]
[C] 在此会话停止
```

对于所有其他门控，为该阶段提供两个最合理的下一步加上"在此停止"。

---

## 8. 后续行动

根据判定，建议具体的下一步：

- **无艺术圣经？** → `/art-bible` 创建视觉识别规范
- **艺术圣经存在但无资产规格？** → `/asset-spec system:[name]` 从批准的 GDD 生成每个资产的视觉规格和生成提示
- **无游戏概念？** → `/brainstorm` 创建一个
- **无系统索引？** → `/map-systems` 将概念分解为系统
- **缺少设计文档？** → `/reverse-document` 或委托给 `game-designer`
- **需要小设计变更？** → `/quick-design` 用于约 4 小时以下的变更（绕过完整 GDD 管道）
- **无 UX 规范？** → `/ux-design [screen name]` 编写规范，或 `/team-ui [feature]` 用于完整管道
- **UX 规范未审查？** → `/ux-review [file]` 或 `/ux-review all` 验证
- **无可访问性需求文档？** → 使用 `AskUserQuestion` 提供现在创建它：
  - 提示："门控需要 `design/accessibility-requirements.md`。我要不要现在从模板创建它？"
  - 选项：`现在创建它 — 我将选择可访问性层级`、`我将自己创建它`、`现在跳过`
  - 如果"现在创建它"：使用第二个 `AskUserQuestion` 询问层级：
    - 提示："哪个可访问性层级适合这个项目？"
    - 选项：`基础 — 仅按键重映射 + 字幕（最低工作量）`、`标准 — 基础 + 色盲模式 + 可缩放 UI`、`全面 — 标准 + 运动可访问性 + 完整设置菜单`、`模范 — 全面 + 外部审计 + 完整自定义`
  - 然后使用 `.claude/docs/templates/accessibility-requirements.md` 中的模板写入 `design/accessibility-requirements.md`，填入选择的层级。确认："我可以写入 `design/accessibility-requirements.md` 吗？"
- **无交互模式库？** → `/ux-design patterns` 初始化它
- **GDD 未交叉审查？** → `/review-all-gdds`（在所有 MVP GDD 单独批准之后运行）
- **交叉 GDD 一致性问题？** → 修复标记的 GDD，然后重新运行 `/review-all-gdds`
- **无测试框架？** → `/test-setup` 为您的引擎搭建框架
- **当前冲刺无 QA 计划？** → `/qa-plan sprint` 在实施开始之前生成一个
- **缺少 ADR？** → `/architecture-decision` 用于单独决策
- **无主架构文档？** → `/create-architecture` 用于完整蓝图
- **ADR 缺少引擎兼容性部分？** → 重新运行 `/architecture-decision` 或手动将引擎兼容性部分添加到现有 ADR
- **缺少控制清单？** → `/create-control-manifest`（需要 Accepted ADR）
- **缺少 epics？** → `/create-epics layer: foundation` 然后 `/create-epics layer: core`（需要控制清单）
- **epic 缺少故事？** → `/create-stories [epic-slug]`（在每个 epic 创建后运行）
- **故事未准备好实施？** → `/story-readiness` 在开发者接收之前验证故事
- **测试失败？** → 委托给 `lead-programmer` 或 `qa-tester`
- **无试玩数据？** → `/playtest-report`
- **少于 3 次试玩会话？** → 在前进之前运行更多试玩测试。使用 `/playtest-report` 结构化发现。
- **无难度曲线文档？** → 在打磨之前考虑在 `design/difficulty-curve.md` 创建一个
- **无玩家旅程文档？** → 使用玩家旅程模板创建 `design/player-journey.md`
- **需要快速冲刺检查？** → `/sprint-status` 用于当前冲刺进度快照
- **性能未知？** → `/perf-profile`
- **未本地化？** → `/localize`
- **准备好发布？** → `/launch-checklist`

---

## 协作协议

本技能遵循协作设计原则：

1. **首先扫描**：检查所有制品和质量门控
2. **询问未知事项**：不要为您无法验证的事项假设 PASS
3. **呈现发现**：显示带状态的完整检查清单
4. **用户决定**：判定是建议 — 用户做出最终决定
5. **获得批准**："我可以将此门控检查报告写入 production/gate-checks/ 吗？"

**永远不要**阻止用户前进 — 判定是建议性的。记录风险并让用户决定是否尽管有顾虑仍继续。

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
