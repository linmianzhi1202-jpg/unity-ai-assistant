---
name: parity-audit
description: >
  Parity 审计技能 — 基于 9-lane checkpoint 方法论的系统性质量审计框架。
  对增强层的 Rules / Skills / Agents / Hooks / Commands / Docs / Tests / Security / Config
  九个维度进行完整性检查，产出结构化 Parity Audit Report 与 Evidence 链。
version: 0.2.0
category: auditing
whenToUse: >
  需要审计 CodeBuddy 增强层的模块完整性和配置一致性时使用此技能。
  适用场景：审计模块完整性和配置一致性、验证新添加的 Rule/Skill/Hook/Agent 是否符合格式规范、
  检查 settings.json 与 CODEBUDDY.md 的交叉引用一致性、生成增强层覆盖率报告（Coverage Map）、
  Phase 结束后验证所有模块是否正确注册和激活。
input:
  - 目标项目路径（默认当前工作区 codebuddy-enhancement/）
  - 审计范围：full（9维全量）/ quick（5维快速）/ custom（自定义维度列表）
output:
  - 结构化 Parity Audit Report（Markdown 格式），包含：总体评分 + 各维度状态 + 缺失项清单 + 修复建议 + Coverage Map
tools:
  - read_file          # 读取各模块文件验证格式与内容
  - search_file        # 发现目录结构、定位缺失文件
  - search_content     # 在 CODEBUDDY.md 中搜索交叉引用
  - list_dir           # 列出目录内容以验证模块注册完整性
context: inline
references:
  - source: ref/claw-code-main/PARITY.md
    extracted: |
      9-lane checkpoint 方法论核心要素：
      - 每个Lane记录 Status(merged/complete/partial) + Feature commit + Evidence(实际文件+LOC)
      - Migration Readiness checklist（迁移就绪检查）
      - Tool Surface Parity 追踪模式（spec parity 40/40）
      - Behavioral Feature Checkpoints（子模块验证清单思路）
      转化为 CodeBuddy 的「项目模块完整性」9 维度 Checkpoint
  - source: ref/claw-code-main/src/parity_audit.py
    extracted: |
      ParityAuditResult dataclass 结构：
      - root_file_coverage / directory_coverage / total_file_ratio
      - command_entry_ratio / tool_entry_ratio
      - missing_root_targets / missing_directory_targets
      - to_markdown() 输出格式 + run_parity_audit() 执行逻辑
      映射为 CodeBuddy Enhancement Layer 的模块覆盖率计算模型
  - source: ref/claw-code-main/rust/PARITY.md
    extracted: |
      Behavioral Feature Checkpoints 详细模式：
      - 每个工具的子功能完成度矩阵（如 Bash tool 9/9 submodules）
      - Runtime Behavioral Gaps 列表（行为差距追踪）
      - Slash Command parity 计数
      转化为每个 Checkpoint 的子验证项设计思路
---

# S6: Parity Audit — 系统性质量审计框架

> **参考来源**:
> - `ref/claw-code-main/PARITY.md` → **9-lane checkpoint 方法论**: Status/Evidence/Diff stat/Migration Readiness 追踪范式
> - `ref/claw-code-main/src/parity_audit.py` → **ParityAuditResult 数据模型**: 覆盖比率计算 + Markdown 报告输出
> - `ref/claw-code-main/rust/PARITY.md` → **Behavioral Feature Checkpoints**: 子模块级验证矩阵
> - 转化为 CodeBuddy 增强层的**项目完整性审计**能力

## 技能概述

Parity Audit 是一个 **只读审计技能**，用于系统化检验 CodeBuddy 增强层的**模块完整性、配置一致性和文档同步状态**。它不会修改任何文件，仅产出诊断报告。

**核心思想来源**：Claw Code 的 `PARITY.md` 用于追踪 Rust 端口与 TypeScript 上游的**功能对等性**（Feature Parity）。CodeBuddy 将同一套方法论转化为 **Enhancement Layer 内部一致性审计** — 验证声明的模块是否真实存在、格式是否合规、配置是否同步。

## 适用场景

| 场景 | 审计模式 | 预计耗时 | 说明 |
|------|----------|----------|------|
| Phase 交付验收 | **full** | 5-8 min | 全量 9 维度 Checkpoint + 完整 Evidence |
| 新增模块后验证 | **quick** | 2-3 min | L1+L2+L3+L8+L9 核心五维快速扫描 |
| 排查配置不一致 | **custom(L8,L9)** | <1 min | 仅检查配置交叉引用 |
| 升级前基线快照 | **full** + save | 5-8 min | 生成基线报告用于升级后对比 |
| A4 编排集成 | **quick** | 2-3 min | 作为 full-audit 模板的前置步骤 T0 |

## 9 维度 Checkpoint 定义

> 从 Claw Code 9-Lane (Bash/CI/File-tool/TaskRegistry/TaskWiring/TeamCron/MCP/LSP/Permission) 语义转化为 CodeBuddy 9 维度。
> 数字保持一致(9)以保留方法论渊源的辨识度。

### L1: Rules 覆盖率（规则层完整度）

**对应原始 Lane**: Permission enforcement（策略门控对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| RULE.mdc 文件存在性 | `search_file("RULE.mdc", rules/*/)` | 每个 Rule 目录下均有 RULE.mdc |
| Frontmatter 格式 | `read_file` + frontmatter 解析 | 含 name/description/version/severity 四字段必填 |
| 内容非空（>50字符） | 文件长度检查 | 不是空壳占位文件 |
| R5 策略条数 | 在 R5 RULE.mdc 中搜索 P1-P7 | 至少 P1-P4 已定义 |

**Evidence 收集**: 每个 Rule 的文件路径 + 行数 + version 字段值 + severity 级别

### L2: Skills 注册表（技能层完整度）

**对应原始 Lane**: File-tool edge cases（工具能力对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| SKILL.md 文件存在性 | `search_file("SKILL.md", skills/*/)` | 每个 active Skill 有 SKILL.md |
| Frontmatter 格式 | frontmatter 解析 | 含 name/version/category/whenToUse 必填 |
| tools 字段声明 | 搜索 frontmatter 中 tools | 声明了使用的工具列表 |
| references 引用 | 搜索 references 字段 | 至少有 1 条 reference 来源标注 |

**Evidence 收集**: 每个 Skill 的 name + version + category + 文件大小

### L3: Agents 定义（代理层完整度）

**对应原始 Lane**: TaskRegistry（任务管理对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| agent.md 存在性 | `search_file("agent.md", agents/*/)` | 每个 Agent 目录下有 agent.md |
| 角色声明 | 搜索 role / whenToUse | 含角色定位和使用时机描述 |
| 工具策略 | 搜索 tools 关键字 | 声明了工具使用策略 |
| 流程定义 | 搜索 process / workflow | 有工作流程或处理步骤说明 |

**Evidence 收集**: 每个 Agent 的 name + model + 角色概述

### L4: Hooks 事件覆盖（钩子层完整度）

**对应原始 Lane**: CI fix + Bash validation（事件校验对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| .mdc 文件存在性 | `search_file("*.mdc", hooks/)` | 每个 Hook 有 .mdc 文件 |
| 事件类型分布 | 统计 event 字段值 | PreToolUse 和 PostToolUse 双向覆盖 |
| matcher 声明 | 检查 matcher 字段 | 有工具匹配表达式 |
| enabled 状态 | 检查 enabled 字段 | settings.json 中已启用 |

**Evidence 收集**: 每个 Hook 的 name + event 类型 + matcher + timeout

### L5: Commands 可用性（命令层完整度）

**对应原始 Lane**: Task wiring + Team+Cron（编排调度对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| .md 文件存在性 | `search_file("*.md", commands/)` | 每个 Command 有 .md 文件 |
| 触发词声明 | 检查 name 字段 | 有明确的命令名称 |
| type 声明 | 检查 type 字段 | type 为 prompt |
| 关联模块 | 检查 description 中的关联说明 | 明确指向对应的 Skill 或 Agent |

**Evidence 收集**: 每个 Command 的 name + 关联模块 + 描述摘要

### L6: 文档同步状态（文档层一致性）

**对应原始 Lane**: MCP lifecycle（生命周期对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| CODEBUDDY.md 版本号 | 读取第一行版本 | version 与 settings.json.version 一致 |
| 模块索引表 | 统计 Skills 表格行数 | 声明的 Skill 数与实际目录匹配 |
| 交叉引用一致性 | 搜索 CODEBUDDY.md 中引用的文件路径 | 所有引用路径指向存在的文件 |
| README 同步（如有） | 对比项目结构与 README 描述 | 主要目录结构一致 |

**Evidence 收集**: 版本号对比 + 索引表差异 + 断链引用清单

### L7: 测试覆盖基线（测试层存在性）

**对应原始 Lane**: LSP client（语言服务对等 — 转为质量保障视角）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| 测试目录存在 | `list_dir` tests/__tests__/spec/test | 至少有一个测试相关目录 |
| 测试文件计数 | `search_file(*.test.*/*.spec.*/*.test.js...)` | 如有测试目录则应有测试文件 |
| R4 test-coverage 规则 | 检查 R4 RULE.mdc 是否 active | R4 已启用则应可发现测试配置 |

> **注意**: 此维度为软性 Checkpoint — 项目无测试目录不视为 FAIL，仅记为 WARN。

**Evidence 收集**: 测试目录列表 + 测试文件数量 + R4 状态

### L8: 安全配置（安全层激活状态）

**对应原始 Lane**: Permission enforcement（权限控制对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| H4 security-gate 启用 | 检查 settings.json hooks.security-gate.enabled | enabled: true |
| R5 P2 安全策略 | 检查 R5 RULE.mdc 中 P2 定义 | P2 有完整的 condition + action |
| A2 security-scanner | 检查 agents/security-scanner/agent.md | agent.md 存在且非空 |
| /secure 命令 | 检查 commands/secure.md | secure.md 存在且含 A2 关联 |

**Evidence 收集**: H4 状态 + P2 完整度 + A2 状态 + /secure 可用性

### L9: 配置一致性（元数据交叉验证）

**对应原始 Lane**: Config merge precedence（配置层级对等）

| 检查项 | 验证方法 | 通过标准 |
|--------|----------|----------|
| settings.json vs CODEBUDDY.md version | 两者 version 字段 | 完全一致 |
| settings.json phase vs CODEBUDDY.md Phase | phase 值与最新 Phase 匹配 | 一致（允许 ±1 容差） |
| 活跃 Skill 数量 | settings.json skills 中 enabled:true 数 | 与 CODEBUDDY.md 索引表数量一致 |
| 活跃 Rule 数量 | settings.json rules 中 enabled:true 数 | 与 CODEBUDDY.md 索引表数量一致 |
| models.json 存在且有效 | 读取 models.json | JSON 有效 + 含 profile 定义 |

**Evidence 收集**: version 对比结果 + 数量差异明细 + models.json 摘要

## 审计工作流

### Phase 1: 发现（Discovery）

```
目标：建立完整的增强层资产清单

步骤:
1. 扫描 .codebuddy/ 目录结构
   ├── rules/     → 发现所有 RULE.mdc
   ├── skills/    → 发现所有 SKILL.md（排除 reserved/disabled）
   ├── agents/    → 发现所有 agent.md
   ├── hooks/     → 发现所有 .mdc
   ├── commands/  → 发现所有 .md
   └── plans/     → 检查是否有存档计划

2. 读取 settings.json
   → 提取 enabled/disabled 状态映射
   → 提取 version / phase 信息

3. 读取 CODEBUDDY.md
   → 提取模块索引表（Rules/Skills/Agents/Hooks/Commands）
   → 提取版本号和 Phase 声明
   → 提取协作矩阵

输出: AssetManifest {
  rules: Map<name, {path, size, enabled}>
  skills: Map<name, {path, size, version, category, enabled}>
  agents: Map<name, {path, size, enabled}>
  hooks: Map<name, {path, size, event, enabled}>
  commands: Map<name, {path, size, linked_module}>
}
```

### Phase 2: 验证（Verify）

```
目标：逐维度执行 Checkpoint 检查

for each checkpoint in selected_dimensions:
  result = checkpoint.verify(asset_manifest)
  # 每个 checkpoint 返回:
  # {
  #   status: "PASS" | "WARN" | "FAIL",
  #   score: 0.0 ~ 1.0,
  #   evidence: Evidence[],       # 具体证据条目
  #   gaps: GapItem[],             # 缺失项或异常
  #   detail: string               # 人类可读的详细说明
  # }
```

### Phase 3: 评分（Score）

```
总体评分公式:

Parity Score = Σ(checkpoint.weight × checkpoint.score) / Σ(weights)

默认权重:
  L1(Rules):     weight=1.5  # 核心行为约束
  L2(Skills):    weight=1.5  # 核心能力提供者
  L3(Agents):    weight=1.0  # 专业代理
  L4(Hooks):     weight=1.0  # 事件自动化
  L5(Commands):  weight=0.8  # 快捷入口
  L6(Docs):      weight=1.2  # 文档一致性
  L7(Tests):     weight=0.5  # 软性指标
  L8(Security):  weight=1.0  # 安全保障
  L9(Config):    weight=1.3  # 元数据一致性

等级划分:
  ★★★★★  0.95~1.00  —  Excellent（优秀，几乎无缺口）
  ★★★★☆  0.85~0.94  —  Good（良好，有小缺口）
  ★★★☆☆  0.70~0.84  —  Acceptable（可接受，有明显缺口需关注）
  ★★☆☆☆  0.50~0.69  —  Needs Attention（需关注，多个维度缺失）
  ★☆☆☆☆  <0.50      —  Critical（严重，核心模块缺失或不一致）
```

### Phase 4: 报告（Report）

## 输出模板

```markdown
# Parity Audit Report

**项目**: CodeBuddy Enhancement Layer
**审计时间**: `<timestamp>`
**审计范围**: `<full/quick/custom(Lx,Ly...)>`
**审计引擎**: S6 parity-audit v0.2.0

## 总体评分: X.X/10 (★★★★☆ Good)

| 维度 | ID | 状态 | 得分 | 权重 | 加权分 | 关键发现 |
|------|-----|------|------|------|--------|----------|
| Rules 覆盖率 | L1 | ✅ PASS | 1.0 | 1.5 | 1.50 | 5/5 Rules 就绪 |
| Skills 注册表 | L2 | ⚠️ WARN | 0.83 | 1.5 | 1.25 | S6 缺少 SKILL.md |
| Agents 定义 | L3 | ✅ PASS | 1.0 | 1.0 | 1.00 | 4/4 Agents 完整 |
| Hooks 事件覆盖 | L4 | ✅ PASS | 1.0 | 1.0 | 1.00 | 5/5 Hooks 全部 active |
| Commands 可用性 | L5 | ✅ PASS | 1.0 | 0.8 | 0.80 | 5/5 Commands 就绪 |
| 文档同步状态 | L6 | ⚠️ WARN | 0.75 | 1.2 | 0.90 | 3 处断链引用 |
| 测试覆盖基线 | L7 | ⚠️ WARN | 0.5 | 0.5 | 0.25 | 无测试目录(soft) |
| 安全配置 | L8 | ✅ PASS | 1.0 | 1.0 | 1.00 | H4+P2+A2 全部激活 |
| 配置一致性 | L9 | ❌ FAIL | 0.67 | 1.3 | 0.87 | version 不匹配 |

**加权总分**: 8.57 / 10.0
**通过率**: 5 PASS / 3 WARN / 1 FAIL

---

## 各维度详情

### L1: Rules 覆盖率 — ✅ PASS (1.0)

| Rule | 文件 | 大小 | Version | Severity | 状态 |
|------|------|------|---------|----------|------|
| R1 engineering-baseline | rules/engineering-baseline/RULE.mdc | 3.2KB | — | warning | ✅ Active |
| ... | ... | ... | ... | ... | ... |

**Evidence**: 所有 5 个 RULE.mdc 文件均存在且内容有效。

### [其他维度按相同格式展开...]

---

## 缺失项汇总

| 优先级 | 维度 | 缺失项 | 影响 | 建议 |
|--------|------|--------|------|------|
| 🔴 High | L9 | settings.json v0.8.0 ≠ CODEBUDDY.md v0.7.0 | 版本混淆 | 统一版本号 |
| 🟠 Med | L2 | S6 parity-audit/SKILL.md 缺失 | Skill 不可用 | 创建 SKILL.md |
| 🟠 Med | L6 | CODEBUDDY.md 第270行引用 /docs 但 docs.md 缺少 api 模式 | 命令不完整 | 补充文档 |

## Enhancement Layer Coverage Map

```
                    声明(Declared)    实际(Actual)    覆盖率
Rules                  5                5            100% ██████████
Skills                 7(active)        6             86% ████████░░
  ├─ Active(S1-S4,S7)   6                6            100%
  └─ Reserved(S5,S6)     2                0              0% (预期)
Agents                 4                4            100% ██████████
Hooks                  5                5            100% ██████████
Commands               5                5            100% ██████████
─────────────────────────────────────────────────────────────
总计                  26(active)        25             96% █████████░
```

## 修复建议优先级队列

1. **[L9-F01]** 统一 settings.json 和 CODEBUDDY.md 版本号 → 改为 v0.9.0
2. **[L2-G01]** 创建 S6 parity-audit/SKILL.md → 激活预留技能
3. **[L6-G01]** 修复 CODEBUDDY.md 中 3 处断链引用 → 更新路径

## 下一步行动

- [ ] 按「修复建议优先级队列」逐项修复
- [ ] 修复后重新运行 `/audit parity quick` 验证
- [ ] 目标: 所有维度达到 PASS 或至少 WARN（无 FAIL）
```

## 使用方式

### 通过 /audit 命令触发

```
/audit parity              # 默认 quick 模式（L1-L3+L8+L9）
/audit parity full         # 全量 9 维度审计
/audit parity custom L1,L2,L6,L9  # 自定义维度
```

### 通过 Agent 触发

当用户说「检查增强层完整性」「验证所有模块是否正常」「运行 parity audit」时，
Agent 应自动加载此技能并执行 quick 模式（如需深度分析再切换 full）。

### 手动调用

```
请使用 parity-audit 技能对当前增强层执行 full 审计
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| scope | enum{full,quick,custom} | quick | 审计范围 |
| dimensions | string[] | — | custom 模式时指定维度（如 L1,L2,L9） |
| output-format | enum{markdown,json,score-only} | markdown | 输出格式 |
| fail-on | enum{fail,warn,none} | warn | 遇到该级别时是否中止后续维度 |

## 与其他模块的协作关系

```
S6 parity-audit (审计执行者)
│
├── 数据读取源（只读）:
│   ├── settings.json         → 模块启用状态 + 版本信息
│   ├── CODEBUDDY.md          → 模块索引表 + 交叉引用声明
│   ├── rules/*/RULE.mdc      → L1 验证对象
│   ├── skills/*/SKILL.md     → L2 验证对象
│   ├── agents/*/agent.md     → L3 验证对象
│   ├── hooks/*.mdc           → L4 验证对象
│   └── commands/*.md         → L5 验证对象
│
├── 协作消费方:
│   ├── A4 coordinator        → full-audit 模板可集成 S6 作为 T0 前置步骤
│   └── /audit 命令           → 可扩展增加 parity 模式选项
│
├── 被引用者:
│   └── R5 policy-executable  → S6 审计结果可作为策略评估输入（未来扩展）
│
└── 互补审计技能:
    ├── S1 state-flow-auditor → S1 审计应用内部状态流，S6 审计增强层自身完整性
    ├── S2 commit-auditor     → S2 审计提交规范性，S6 审计模块结构性
    └── S3 dependency-auditor → S3 审计依赖安全，S6 审计配置一致性
```

## 限制与边界

- ✅ 支持 codebuddy-enhancement 项目结构的全量审计
- ✅ 三种审计模式适应不同场景需求
- ✅ 只读操作，不会修改任何文件
- ⚠️ L7（测试覆盖）为软性 Checkpoint — 无测试目录不视为硬性失败
- ⚠️ Coverage Map 中的 Reserved 模块（S5/S6 disabled）标记为"预期内缺失"
- ❌ 不执行代码逻辑分析或运行时验证
- ℹ️ full 模式需要读取 20+ 个文件，大型增强层可能需要 5-8 分钟

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计（自引用）
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 修复 YAML frontmatter 格式（whenToUse、version 引号问题），标准化字段格式 |
| 0.1.0 | 2026-04-07 | 初始版本，Phase 7 创建 — 9 维度 Checkpoint + Evidence 收集 + ParityAuditReport 输出 |
