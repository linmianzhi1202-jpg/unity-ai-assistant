---
name: ux-review
description: UX 审查 — 验证 UX 规范、HUD 设计或交互模式库的完整性、可访问性合规性、GDD 一致性和实施准备情况
version: 0.2.0
category: game-development
whenToUse: >
  当需要验证 UX 规范、HUD 设计或交互模式库的完整性、
  可访问性合规性、GDD 一致性和实施准备情况时，使用此技能。
  生成 APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED 判定并指定缺口。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标文件路径或范围参数（specific file / all / hud / patterns）
output:
  - UX 审查报告（Markdown 格式）
  - 判定级别（APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED）
  - 具体缺口列表和改进建议
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# UX 审查技能

## 技能概述

在 UX 设计规范进入实施管道之前进行验证。作为 UX 设计与视觉设计/实施之间的质量门控，位于 `/team-ui` 管道中。

**适用场景**：
- 使用 `/ux-design` 完成 UX 规范后
- 移交给 `ui-programmer` 或 `art-director` 之前
- 预生产到生产门控检查之前（需要关键屏幕有审查过的 UX 规范）
- UX 规范重大修订后

**判定级别**：
- **APPROVED** — 规范完整、一致且准备实施
- **NEEDS REVISION** — 发现特定缺口；移交前修复但不需要完全重新设计
- **MAJOR REVISION NEEDED** — 范围、玩家需求或完整性存在根本问题；需要重大重写

## 使用方式

- 通过 Agent 触发：当用户说「UX 审查」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill ux-review [参数]`

---

## 阶段 0: 解析参数

**参数**: `$ARGUMENTS[0]` (空白 = 询问用户）

- **特定文件路径**（例如 `/ux-review design/ux/inventory.md`）：验证该文档
- **`all`**：查找 `design/ux/` 中的所有文件并逐一验证
- **`hud`**：专门验证 `design/ux/hud.md`
- **`patterns`**：专门验证 `design/ux/interaction-patterns.md`
- **无参数** → 使用 `AskUserQuestion` 询问要验证哪个规范

对于 `all`，首先输出汇总表（文件 | 判定 | 主要问题），然后每个的完整详情。

---

## 阶段 1: 加载交叉引用上下文

在验证任何规范之前，加载：

1. **输入和平台配置**：读取 `.claude/docs/technical-preferences.md` 并提取 `## Input & Platform`。这是游戏支持的输入方法的权威来源 — 使用它来驱动阶段 3A 中的输入方法覆盖检查，而不是规范自己的标头。如果未配置，回退到规范标头。
2. **可访问性层级**：提交到 `design/accessibility-requirements.md`（如果存在）
3. **交互模式库**：位于 `design/ux/interaction-patterns.md`（如果存在）
4. **规范标头中引用的 GDD**：读取其 UI 需求部分
5. **玩家旅程地图**：位于 `design/player-journey.md`（如果存在），用于上下文到达验证

---

## 阶段 2: UX 规范验证清单

对基于 `ux-spec.md` 的文档运行所有检查：

### 完整性（必需章节）

验证规范是否包含：
- [ ] 概述和玩家目标
- [ ] 用户故事和验收标准
- [ ] 信息架构（屏幕地图、导航流程）
- [ ] 线框图或描述
- [ ] 输入方法覆盖
- [ ] 可访问性注释
- [ ] 实施注释

### 一致性检查

- [ ] 与引用的 GDD 一致
- [ ] 与交互模式库一致（如果存在）
- [ ] 与玩家旅程地图一致（如果存在）
- [ ] 跨屏幕术语使用一致

### 可访问性合规性

根据可访问性层级验证：
- [ ] 文本对比度要求
- [ ] 屏幕阅读器支持
- [ ] 键盘导航
- [ ] 颜色不是唯一的信息载体
- [ ] 可调整文本大小

### 实施准备情况

- [ ] 所有交互都有明确的行为
- [ ] 边缘情况已处理
- [ ] 错误处理已定义
- [ ] 性能指标已指定

---

## 阶段 3: HUD 设计验证（如果适用）

如果规范包含 HUD 元素，额外验证：

### HUD 特定检查

- [ ] HUD 元素优先级已定义
- [ ] 屏幕空间和安全性已考虑
- [ ] HUD 在不同分辨率下可读
- [ ] 可访问性覆盖已计划（字幕、色盲模式等）

### 技术可行性

- [ ] 性能影响已评估
- [ ] 引擎限制已考虑
- [ ] 平台特定 UI 指南已遵循

---

## 阶段 4: 生成审查报告

编译所有发现到结构化报告：

```markdown
# UX 审查报告：[规范名称]

**生成日期**: [今天]
**审查员**: [Agent 名称]
**判定**: [APPROVED / NEEDS REVISION / MAJOR REVISION NEEDED]

## 摘要

[高层级摘要审查发现]

## 详细发现

### 完整性
[完整/缺失章节列表及缺口]

### 一致性
[与 GDD、模式库、玩家旅程的一致性检查]

### 可访问性
[合规性状态和发现的问题]

### 实施准备情况
[准备情况评估和阻塞问题]

## 改进建议

[优先改进建议列表]

## 下一步

[基于判定的后续步骤]
```

**判定标准**：

- **APPROVED**：所有检查通过，无关键问题
- **NEEDS REVISION**：1-2 个次要问题，可在实施前快速修复
- **MAJOR REVISION NEEDED**：多个关键问题或根本缺陷

---

## 阶段 5: 展示结果和判定

使用 `AskUserQuestion` 展示审查结果：

```
question: "UX 审查完成。判定：[判定级别]。[主要发现摘要]。"
options:
  - "批准并继续到实施"
  - "需要修订（次要问题）"
  - "需要重大修订（根本问题）"
  - "导出完整报告"
```

仅在用户批准后标记规范为审查通过。

---

## 阶段 6: 导出报告

如果请求，将审查报告写入 `design/ux/reviews/[spec-name]-review.md`。

询问："我可以写入此审查报告到 `design/ux/reviews/` 吗？"

仅在批准后写入。

---

## 协作协议

此技能遵循协作审查原则：

1. **加载完整上下文**：在审查之前，加载所有相关文档
2. **系统检查**：使用结构化清单确保完整性
3. **清晰判定**：明确说明判定和原因
4. **可操作反馈**：提供具体、可操作的改进建议
5. **用户决定**：用户决定是批准、修订还是拒绝
6. **记录决策**：在审查报告中记录所有决策及其原因

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
