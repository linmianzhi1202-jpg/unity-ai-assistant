---
name: asset-spec
description: 资产规格 — 创建设计规格，定义资产创建要求
version: 0.3.0
category: game-development
whenToUse: >
  当需要通过资产规格技能创建设计规格时使用。
  处理定义资产创建要求、生成资产清单和检查清单相关任务时。
  支持参数：system:[name]（系统资产）、level:[name]（关卡资产）、character:[name]（角色资产）。
input:
  - 项目根目录路径（默认当前工作区）
  - 目标参数：system:[name] / level:[name] / character:[name]
output:
  - 结构化资产规格文档（Markdown 格式）
  - design/assets/specs/[target]-spec.md 文件生成
  - design/assets/asset-manifest.md 文件更新
  - design/assets/checklists/[target]-checklist.md 文件生成
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 资产规格技能

## 技能概述

创建设计规格，定义资产创建要求，生成资产清单和检查清单。

## 使用方式

- 通过 Agent 触发：当用户说「资产规格」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill asset-spec [参数]`

---

## 功能说明

### 阶段 0：解析参数

提取：
- **目标类型**：`system`、`level` 或 `character`
- **目标名称**：冒号后的名称（规范化为 kebab-case）
- **审查模式**：如果存在 `--review [full|lean|solo]`

**参数模式**：
- `system:[name]` — 为指定系统创建资产规格
- `level:[name]` — 为指定关卡创建资产规格
- `character:[name]` — 为指定角色创建资产规格

如果没有提供参数，检查 `design/assets/asset-manifest.md` 是否存在：
1. 如果存在：读取它，找到状态为 "Needed" 但还没有编写规格文件的目标，使用询问用户：
   - 提示："下一个未规格化的目标是 **[target]**。为其生成资产规格？"
   - 选项：`[A] 是 — 规格 [target]` / `[B] 选择不同的目标` / `[C] 停止`
2. 如果 `[A]`：继续使用该系统名称。如果 `[B]`：询问要规格哪个目标（纯文本）。如果 `[C]`：退出。
3. 如果没有清单，失败并显示：
   > "用法：`/asset-spec <system-name>` — 例如：`/asset-spec tower-defense`"
   > "或对现有规格中的空白进行填充：`/asset-spec retrofit design/assets/specs/[system-name].md`"
   > "未找到资产清单。首先运行 `/asset-audit` 来映射您的资产并获取规格顺序。"

### 阶段 1：收集上下文

**在询问用户任何内容之前**，按此顺序读取完整项目上下文：

1. **相关 GDD**：读取 `design/gdd/[system].md`（如果存在）
2. **艺术圣经**：读取 `design/art-bible.md`（如果存在）
3. **资产清单**：读取 `design/assets/asset-manifest.md`（如果存在）
4. **现有规格**：读取 `design/assets/specs/[target].md`（如果存在）

**展示上下文摘要**：在开始规格工作之前，向用户展示简要摘要：
> **正在规格化：[Target Name]**
> - 相关 GDD：[system-name]
> - 艺术圣经指南：[已加载/未找到]
> - 资产清单：[已加载/未找到]

---

## 阶段 2：创建规格文件

用户确认后，**立即**创建资产规格文件。这确保增量写入有目标。

使用 `.claude/docs/templates/asset-spec-document.md` 的模板结构：
```markdown
# [Target Name] 资产规格

> **状态**: Draft
> **类型**: system / level / character
> **最后更新**: [today's date]
> **作者**: [user + agents]

## 概述

[资产用途和上下文的详细描述]

## 视觉设计

### 风格参考
- [参考 1]
- [参考 2]

### 颜色调色板
- 主色：[颜色代码和描述]
- 辅助色：[颜色代码和描述]

### 形状语言
- [形状描述 — 棱角分明、圆润、有机等]

## 技术规格

### 模型要求
- **多边形预算**：< [数字] 三角形
- **纹理分辨率**：[分辨率，例如 2048x2048]
- **UV 布局**：[描述]

### LOD 要求
- **LOD 0**：[多边形计数] 三角形（近距离）
- **LOD 1**：[多边形计数] 三角形（中距离）
- **LOD 2**：[多边形计数] 三角形（远距离）

### 优化要求
- **遮挡剔除**：[是/否]
- **批处理**：[是/否]
- **光照**：[烘焙/实时]

## 动画要求

[如果需要动画 — 详细描述所需的动画状态、过渡、混合树]

## 音频要求

[如果需要音频 — 详细描述所需的音效、音乐、触发条件]

## 验收标准

- [ ] 视觉风格与艺术圣经匹配
- [ ] 多边形计数在预算内
- [ ] 纹理分辨率正确
- [ ] LOD 已配置
- [ ] 优化已验证
- [ ] 集成到引擎中

## 开放问题

[在规格化过程中出现的、未完全解决的任何事情]
```

询问："我可以将规格文件创建到 `design/assets/specs/[target]-spec.md` 吗？"

写入后，更新 `production/session-state/active.md`：
- 使用 搜索文件 检查文件是否存在。
- 如果**不**存在：使用 write_to_file 工具创建它。
- 如果它**已经**存在：使用 replace_in_file 工具更新相关字段。

---

## 阶段 3：逐部分填写

按顺序遍历每个章节。对于每个章节，遵循此循环：

```
上下文  ->  问题  ->  选项  ->  决策  ->  草稿  ->  批准  ->  写入
```

1. **上下文**：陈述此章节需要包含的内容，并暴露约束此章节的任何依赖项文档的决策。
2. **问题**：询问此章节特定的澄清问题。
3. **选项**：如果章节涉及设计选择（不仅仅是文档），展示 2-4 个方法，附带利弊。
4. **决策**：用户选择一个方法或提供自定义方向。
5. **草稿**：在对话文本中为审查编写章节内容。
6. **批准**：在草稿之后 — 在**同一**响应中 — 使用询问用户。
   - 提示："批准 [Chapter Name] 章节吗？"
   - 选项：`[A] 批准 — 写入文件` / `[B] 进行更改 — 描述要修复的内容` / `[C] 重新开始`
7. **写入**：使用 replace_in_file 工具将批准的内容替换占位符。

写入每个章节后，更新 `production/session-state/active.md` 和已完成的章节名称。

---

## 阶段 4：后规格验证

所有章节写入后：

### 4a：自检

读取完整的资产规格（从文件，不是来自对话记忆 — 文件是真相来源）。验证：
- 所有必需章节都有真实内容（不是占位符）
- 视觉设计与艺术圣经一致
- 技术规格明确且可测量
- 验收标准是可测试的

### 4b：更新资产清单

扫描已完成的规格，查找应注册的资产：
1. 读取 `design/assets/asset-manifest.md`。
2. 将新条目添加到清单。
3. 更新状态从 "Needed" 到 "Speced"。

询问："我可以用这些 [N] 个新条目更新 `design/assets/asset-manifest.md` 并为现有条目更新状态吗？"

---

## 阶段 5：生成检查清单

创建 `design/assets/checklists/[target]-checklist.md`：

```markdown
# [Target Name] 资产创建检查清单

## 建模检查清单

- [ ] 多边形计数在预算内
- [ ] UV 布局已优化
- [ ] 法线已烘焙
- [ ] 纹理分辨率正确

## 纹理检查清单

- [ ] 所有纹理已打包
- [ ] 纹理格式已优化
- [ ] Mipmap 已生成

## 优化检查清单

- [ ] 遮挡剔除已配置
- [ ] 批处理已设置
- [ ] 光照已烘焙（如果需要）

## 集成检查清单

- [ ] 资产已导入引擎
- [ ] LOD 已配置
- [ ] 碰撞体已设置
- [ ] 材质已分配
```

---

## 阶段 6：建议后续步骤

写入规格后：

- 如果史诗/故事还不存在："运行 `/create-epics layer: [layer]` 然后 `/create-stories [epic-slug]` — 艺术家现在可以在创建资产时使用此规格。"
- 如果这是重新生成（规格已存在）："已更新。建议通知团队规格变更 —— 特别是任何新的技术要求。"

使用询问用户：

- 提问："[N] 个规格已写入到 `design/assets/specs/`。接下来什么？"
- 选项（包含所有适用的）：
  - `[A] 开始创建资产 — 运行 `/asset-create [target]`（推荐）
  - `[B] 为 [next-target] 创建规格 — 运行 `/asset-spec [target]`（仅当其他目标还没有规格时）
  - `[C] 规划冲刺 — 运行 `/sprint-plan`（仅当所有目标都有规格时）
  - `[D] 在此会话停止此处`

---

## 协作协议

此技能在每一步都遵循协作设计原则：

1. **首先扫描** — 检查所有制品和质量门控
2. **询问一次** — 在摘要中展示所有规格章节，而不是一次一个
3. **在写入之前询问** — 在写入任何文件之前获得完整规格的批准
4. **无发明** — 所有内容来自 GDD、艺术圣经和资产清单
5. **永远不要开始创建** — 此技能在规格级别停止
6. **增量写入** — 每个批准后立即写入章节

---

## 推荐后续步骤

- 运行 `/asset-audit` 以验证所有资产需求是否已覆盖
- 运行 `/create-epics layer: [layer]` 为此系统创建史诗
- 当所有资产规格都已编写时，运行 `/gate-check production`

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
| **0.3.0** | 2026-04-27 | 修复 YAML 格式（description/whenToUse），清理标题多余# 符号，升级版本号 |
| 0.2.0 | 2026-04-27 | 清理格式（删除多余的反引号和 # 符号），更新版本号 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
