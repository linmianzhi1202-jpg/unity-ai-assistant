---
name: architecture-review
description: "architecture-review — 验证项目架构的完整性和一致性，对照所有 GDD。构建追溯性矩阵，将每个 GDD 技术需求映射到 ADR，识别覆盖差距，检测跨 ADR 冲突，验证所有决策的引擎兼容性一致性，并生成 PASS/CONCERNS/FAIL 判定。这是架构等效于 /design-review 的技能。"
version: 0.2.0
category: game-development
whenTUse: |
  当需要通过架构审查技能验证项目架构时使用。
  处理构建追溯性矩阵、检测跨 ADR 冲突、验证引擎兼容性一致性相关任务时。
  支持参数：无参数（完整审查）、coverage（追溯性）、consistency（一致性）、engine（引擎兼容性）、single-gdd [path]（单个 GDD）、rtm（追溯性矩阵）。
input:
  - 项目根目录路径（默认当前工作区）
  - 审查模式参数：full / coverage / consistency / engine / single-gdd [path] / rtm
output:
  - 架构审查报告（Markdown 格式）
  - 追溯性矩阵表格
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 架构审查技能

## 技能概述

验证项目架构的完整性与一致性，对照所有 GDD。构建追溯性矩阵，将每个 GDD 技术需求映射到 ADR，识别覆盖差距，检测跨 ADR 冲突，验证所有决策的引擎兼容性一致性，并生成 PASS/CONCERNS/FAIL 判定。这是架构等效于 /design-review 的技能。

## 使用方式

- 通过 Agent 触发：当用户说「架构审查」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill architecture-review [参数]`

## 功能说明

架构审查验证完整架构决策是否覆盖所有游戏设计需求，内部一致，并正确锁定项目的引擎版本。

### 参数模式

**无参数 / `full`**：完整审查 — 所有阶段
**`coverage`**：仅追溯性 — 哪些 GDD 需求没有 ADR
**`consistency`**：仅跨 ADR 冲突检测
**`engine`**：仅引擎兼容性审计
**`single-gdd [path]`**：审查一个特定 GDD 的架构覆盖
**`rtm`**：需求追溯性矩阵 — 扩展标准矩阵以包含故事文件路径和测试文件路径；输出 Markdown 表格

### 阶段 0：解析参数 — 检测审查模式#

解析审查模式（一次，为此运行的所有生成设置）：

1. 如果传递了 `--review [full|lean|solo]` → 使用那个
2. 否则读取 `production/review-mode.txt` → 使用那个值
3. 否则 → 默认到 `lean`

参见 `.claude/docs/director-gates.md` 获取完整检查模式。

## 工作流程#

### 阶段 1：建立追溯性矩阵#

1. 读取所有 GDD 文件（`design/gdd/*.md`）
2. 提取所有技术需求 ID（例如，`REQ-001`）
3. 读取所有 ADR 文件（`architecture/adr-*.md`）
4. 映射需求 → ADR（从 `## GDD Requirements Addressed`）
5. 输出：`TraceabilityMatrix { gdd_reqs[], adr_coverage[], gaps[] }`

### 阶段 2：覆盖分析#

1. 识别没有 ADR 的需求（覆盖差距）
2. 识别没有需求覆盖的 ADR（过度工程）
3. 检查每个 ADR 的 `## Status`：
   - `Proposed`：HIGH 风险 — 决策未批准
   - `Accepted`：✅ 好
   - `Deprecated`：检查替换 ADR 是否存在
4. 输出：`CoverageReport { covered, gaps, over_engineering }`

### 阶段 3：一致性检查#

1. 检测跨 ADR 冲突：
   - 技术栈冲突（例如，ADR-001 说"使用 Unity"，ADR-002 说"使用 Godot"）
   - 模式冲突（例如，ADR-003 说"ECS"，ADR-004 说"MonoBehaviour"）
   - 依赖循环（ADR-005 依赖 ADR-006，ADR-006 依赖 ADR-005）
2. 检查 `## ADR Dependencies` 部分：
   - 缺少依赖 → MEDIUM 风险
   - 循环依赖 → HIGH 风险
3. 输出：`ConsistencyReport { conflicts[], dependency_issues[] }`

### 阶段 4：引擎兼容性验证#

1. 检查每个 ADR 的 `## Engine Compatibility`：
   - 缺少 → HIGH 风险（post-cutoff 风险未知）
   - 版本不匹配跨 ADR → HIGH 风险
2. 验证引擎版本与 `settings.json` 中的 `engine.version` 匹配
3. 检查引擎特定约束（例如，Unity DOTS 仅在 2022.3+ 中完全支持）
4. 输出：`EngineCompatibilityReport { compatible, warnings[], blockers[] }`

### 阶段 5：生成判定#

1. 收集所有发现：
   - 覆盖差距
   - 一致性冲突
   - 引擎兼容性问题
2. 计算整体健康评分：
   - PASS：无 HIGH 风险问题
   - CONCERNS：1-2 个 MEDIUM 风险问题
   - FAIL：任何 HIGH 风险问题
3. 输出结构化报告：`ArchitectureReviewReport { verdict, score, details }`

## 输出格式#

### 架构审查报告#

```markdown
# 架构审查报告

**日期**：2026-04-27
**项目**：My Game Project
**审查模式**：full

## 追溯性矩阵

| GDD 需求 ID | GDD 文件 | 技术需求 | ADR | 状态 | 故事文件 | 测试文件 |
|------------|----------|------------|-----|------|------------|------------|
| REQ-001 | gdd-combat.md | 战斗系统架构 | ADR-0001 | ✅ 已覆盖 | stories/combat-001.md | tests/combat-tests.md |
| REQ-002 | gdd-progression.md | 进度系统 | ADR-0002 | ⚠️ 部分覆盖 | - | - |
| REQ-003 | gdd-ai.md | AI 行为树 | - | ❌ 未覆盖 | - | - |

## 覆盖分析

### ✅ 已覆盖（5/8 需求）
- REQ-001：战斗系统 → ADR-0001
- REQ-004：保存系统 → ADR-0003
- ...

### ⚠️ 部分覆盖（2/8 需求）
- REQ-002：进度系统 → ADR-0002（缺少服务器实现细节）
- REQ-005：多人游戏 → ADR-0004（缺少延迟补偿细节）

### ❌ 未覆盖（1/8 需求）
- REQ-003：AI 行为树 → 无 ADR

## 一致性检查

### ❌ 冲突检测
1. **技术栈冲突**：
   - ADR-0001：使用 Unity DOTS
   - ADR-0005：使用 Unity MonoBehaviour
   - **风险**：HIGH — 混合 ECS 和 OOP 导致代码不一致

2. **依赖循环**：
   - ADR-0002 依赖 ADR-0003
   - ADR-0003 依赖 ADR-0002
   - **风险**：HIGH — 循环依赖阻止独立实现

## 引擎兼容性

### ✅ 兼容（6/8 ADR）
- ADR-0001：Unity 2022.3.15f1 ✅
- ADR-0002：Unity 2022.3.15f1 ✅
- ...

### ⚠️ 警告（2/8 ADR）
- ADR-0005：引擎版本未指定 → MEDIUM 风险
- ADR-0006：Unity 版本与项目设置不匹配 → HIGH 风险

## 判定

**判定**：⚠️ CONCERNS

**健康评分**：65/100

**阻止问题**（必须修复）：
1. 1 个 HIGH 风险覆盖差距（REQ-003 未覆盖）
2. 1 个 HIGH 风险一致性冲突（技术栈冲突）
3. 1 个 HIGH 风险引擎兼容性问题（版本不匹配）

**应该修复**（推荐）：
1. 2 个 MEDIUM 风险覆盖差距（部分覆盖）
2. 1 个 MEDIUM 风险引擎兼容性问题（版本未指定）

## 下一步

1. **立即**：创建 ADR 以覆盖 REQ-003（AI 行为树）
2. **本周**：解决技术栈冲突（选择 DOTS 或 MonoBehaviour）
3. **本周**：修复引擎版本不匹配
4. **可选**：添加更多细节到部分覆盖的 ADR
```

## 质量检查#

- [ ] 追溯性矩阵完整（所有 GDD 需求已映射）
- [ ] 覆盖分析识别所有差距
- [ ] 一致性检查检测所有冲突
- [ ] 引擎兼容性验证所有 ADR
- [ ] 判定基于客观标准
- [ ] 报告使用清晰 Markdown 格式

---

## CodeBuddy 增强集成#

此技能与 CodeBuddy 增强层集成：
- 使用 `policy-executable` Rule 进行策略检查
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响

## 版本历史#

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 清理格式（删除标题末尾多余的 #），更新版本号 |
| 0.1.0 | 2026-04-27 | 从 Claude Code Game Studios 迁移并中文化 |
