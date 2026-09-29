---
name: documentation-generator
description: >
  文档生成技能 — 当用户需要生成 API 文档、CHANGELOG、更新 README、
  创建 ADR、自动化维护和同步项目文档时使用。
  提供四种文档生成模式（API Reference、CHANGELOG、README 同步、ADR）。
version: 0.3.0
category: documentation
whenToUse: >
  当用户需要为项目生成 API 参考文档时使用（JSDoc/docstring/TSDoc 注释提取）。
  需要从 git 历史生成 CHANGELOG（Conventional Commits 格式）。
  需要检查 README 是否与当前项目结构同步。
  需要创建 ADR 架构决策记录。
  需要批量更新项目文档以反映最新代码变更。
input:
  - 目标项目路径（默认当前工作区）
  - 文档模式：api / changelog / readme / adr / full（全量）
  - 输出路径（默认项目根目录或 docs/ 子目录）
output: >
  按类型分格的结构化 Markdown 文档，包含 API Reference / CHANGELOG /
  差异报告或 ADR 记录文件
references:
  - source: .codebuddy/skills/commit-auditor/SKILL.md
    extracted: Step 1 提交数据收集逻辑 + Conventional Commits 格式解析正则（CHANGELOG 生成复用）
  - source: .codebuddy/hooks/change-log.mdc
    extracted: 变更日志条目数据结构（变更条目作为文档更新触发信号）
  - source: .codebuddy/rules/engineering-baseline/RULE.mdc
    extracted: C6 文档规范要求（README 必备章节、注释标准）
  - source: ref/claw-code-main/PARITY.md
    extracted: Evidence 收集方法论（多源交叉验证确保文档准确性）
context: inline
---

# S4: Documentation Generator — 自动文档生成技能

## 用途

自动化生成和维护项目文档，确保代码与文档的持续同步。

**核心能力**：
1. **API 文档** — 从源码 JSDoc/docstring/TSDoc 注释中自动提取和组装参考文档
2. **CHANGELOG** — 从 git 历史按 Conventional Commits 规范生成 Keep a Changelog 格式变更日志
3. **README 同步** — 对比当前项目结构与 README 描述，输出差异报告并建议更新
4. **ADR** — 按 MADR (Markdown Architecture Decision Record) 标准模板生成架构决策记录

---

## 文档生成工作流

### Step 0: 项目上下文收集（所有模式共用前置步骤）

在执行任何文档模式前，先完成上下文收集：

```yaml
输入: 项目路径（默认当前工作区）

执行:
  list_dir: {project_root}                    # 顶层目录结构
  read_file: package.json / pyproject.toml / Cargo.toml / go.mod  # 项目元数据
  execute_command: git remote get-url origin    # 仓库地址
  execute_command: git describe --tags --always # 版本号（如有 tag）
```

输出上下文：
```
project_name: "{name}"
version: "{version}"
language: "{primary_language}"
framework: "{detected_frameworks[]}"
build_tool: "{npm/cargo/go/maven/gradle}"
has_git: true/false
repo_url: "{url}"
```

**语言/框架检测规则**：

| 特征文件 | 语言 | 框架推测 |
|----------|------|----------|
| `package.json` | TypeScript/JavaScript | React/Vue/Angular/Next.js（依赖判断） |
| `tsconfig.json` | TypeScript | — |
| `pyproject.toml` / `setup.py` | Python | Django/FastAPI/Flask |
| `Cargo.toml` | Rust | Actix/Axum（依赖判断） |
| `go.mod` | Go | Gin/Echo/Fiber |
| `pom.xml` / `build.gradle` | Java/Kotlin | Spring Boot |

---

### Mode A: API 文档生成

#### Step A1: 扫描导出符号

定位所有公开 API（导出的类、函数、接口、类型别名）：

```bash
# TypeScript / JavaScript
search_file: pattern="export\s+(function|class|const|type|interface|enum)\s+\w+"
             recursive=true target_directory=src/
search_content: pattern="^export\s+" glob="*.{ts,tsx,js,jsx}" path=src/

# Python
search_file: pattern="^\s*(def|class)\s+[a-zA-Z]"
             recursive=true target_directory=src/
# 排除以 _ 开头的私有成员

# Rust
search_file: pattern="^(pub\s+)?(fn|struct|enum|trait|type|impl)\s+\w+"
             recursive:true target_directory=src/

# Go
search_file: pattern="^(func|type|interface|const|var)\s+[A-Z]\w+"
             recursive:true target_directory=.
```

#### Step A2: 提取注释块

对每个导出符号，提取其关联的文档注释：

```
支持格式:
┌─────────────────────────────────────┐
│ TypeScript / JavaScript (JSDoc)      │
│ /**                                  │
│  * @description 函数描述              │
│  * @param {string} name 参数说明       │
│  * @returns {number} 返回值说明        │
│  * @example                           │
│  * const result = foo("hello");       │
│  */                                   │
│ export function foo(name: string): number {} │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ Python (docstring)                   │
│ def foo(name: str) -> int:           │
│     """函数描述。                     │
│                                      │
│     Args:                            │
│         name: 参数说明                │
│                                      │
│     Returns:                         │
│         返回值说明                    │
│                                      │
│     Example:                         │
│         >>> foo("hello")             │
│         42                           │
│     """                              │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ Rust (doc comments)                  │
│ /// 函数描述。                        │
│                                   │
│ # Arguments                       │
│ /// * `name` - 参数说明               │
│                                   │
│ /// # Returns                        │
│ /// 返回值说明                         │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ Go (godoc style)                     │
│ // Foo 函数描述。                     │
│                                    │
│ // name 是参数说明。                   │
│ // 返回值说明。                        │
│ func Foo(name string) int {}          │
└─────────────────────────────────────┘
```

**提取正则**：

```
# JSDoc/TSDoc 注释块
(/\*\*[\s\S]*?\*/)\s*\n(?:export\s+)?(?:function|class|const|type|interface|enum)

# Python docstring (三引号)
("""[\s\S]*?"""|'''[\s\S]*?''')]\s*\n(?:def|class)

# Rust doc comment
(///[\s\S]*?)\s*\n(?:pub\s+)?(?:fn|struct|enum|trait|type|impl)

# Go doc comment (行注释)
(// [\s\S]*?)\s*\n(func|type|interface|const|var)\s+[A-Z]
```

#### Step A3: 组织生成 API Reference 文档

按模块/目录组织输出：

```markdown
# {Project Name} API Reference

> 自动生成于 {timestamp} | 基于 v{version} | 源码分支: {branch}

---

## 目录

- [{Module A}](#{module_a_slug})
- [{Module B}](#{module_b_slug})
- ...

---

## {Module A}

> 路径: `{relative_path}`

### Functions

#### {function_name}({params})

**签名**: `{full_signature}`

**描述**: {description from comment}

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| {param} | {type} | ✅/❌ | {default} | {param_desc} |

**返回**: {return_type} — {return_description}

**示例**:

```{language}
{example_code}
```

**抛出**: {throws if applicable}

---

### Classes / Types

#### {Class/Type Name}

**描述**: {description}

| 属性 | 类型 | 访问级别 | 说明 |
|------|------|----------|------|
| {prop} | {type} | public/private | {desc} |

| 方法 | 签名 | 说明 |
|------|------|------|
| {method} | {sig} | {desc} |

---

## {Module B}
...（同上格式）

---

## 文档覆盖率报告

| 模块 | 导出符号总数 | 已文档化 | 覆盖率 | 缺失文档 |
|------|------------|----------|--------|----------|
| {module_a} | {N} | {M} | {pct}% | [list] |
| **总计** | {Total} | {Doced} | {Overall}% | — |

> ⚠️ 覆盖率 < 80% 的模块建议补充文档注释
```

---

### Mode B: CHANGELOG 生成

#### Step B1: Git Log 提交解析

从 git 历史提取提交信息（复用 S2 commit-auditor 的格式解析逻辑）：

```bash
# 获取上次 tag 以来的提交（或最近 N 次）
execute_command: git log {last_tag}..HEAD --format="%H|%s|%b|%an|%ai" --no-merges

# 如果没有 tag:
execute_command: git log -{N} --format="%H|%s|%b|%an|%ai" --no-merges

# 获取 tag 列表用于版本分组
execute_command: git tag --sort=-v:refname
```

**Conventional Commits 解析正则**（与 S2 共享）：

```
^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?:\\s(.+)$
```

字段提取：
- type: $1        # feat/fix/...
- scope: $2       # (括号内内容)
- subject: $3     # 描述文本

#### Step B2: 按版本分组

根据 git tag 或语义版本推断进行分组：

```yaml
分组策略（按优先级）：
  1. 有 tag: 使用 git tag 作为版本边界（git log tagA..tagB）
  2. 无 tag 有版本号: 从 package.json/Cargo.toml 读取当前版本作为 "Unreleased"
  3. 无任何版本标记: 全部归入 "Unreleased"，按日期分子组
  
版本排序: 降序（最新的在前）
```

**分类映射**：

```
Conventional Commit Type → CHANGELOG Section:
  feat      → ### Added
  fix       → ### Fixed
  perf      → ### Changed (性能优化)
  refactor  → ### Changed (内部重构)
  docs      → ### Documentation
  style     → ### Changed (样式调整)
  test      → ### Changed (测试相关)
  build     → ### Build System
  ci        → ### CI/CD
  chore     → ### Changed (杂项)
  revert    → ### Fixed (回退修复)
```

#### Step B3: 生成 Keep a Changelog 格式

```markdown
# Changelog

All notable changes to {project_name} will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0).

## [Unreleased]

### Added
- **({scope})**: {subject} ({short_hash}) [@{author}]
- ...

### Fixed
- **({scope})**: {subject} ({short_hash}) [@{author}]
- ...

### Changed
- **({scope})**: {subject} ({short_hash}) [@{author}]
- ...

### Documentation
- ...

### Build System / CI/CD
- ...

---

## [{version}] - {date}

### Added
- ...（同上格式）

### Fixed
- ...

...
```

**与 H3 change-log 联动**：
当 H3 change-log 已有会话期间的变更数据时，可将其合并到 Unreleased 区块：

```
H3 数据 → Unreleased 补充来源:
  change_entry.action_summary → 作为 Additional Changes 条目
  change_entry.timestamp → 时间戳参考
  change_entry.related_skill → 来源标注（如 [via code-reviewer]）
```

---

### Mode C: README 同步检查

#### Step C1: 解析当前项目结构

```yaml
执行:
  list_dir: {project_root}                          # 顶层结构
  list_dir: {project_root}/src                      # 源码目录
  list_dir: {project_root}/tests                    # 测试目录
  list_dir: {project_root}/docs                     # 文档目录
  search_file: pattern="*.md" recursive=false       # 所有 MD 文件
  search_file: pattern=".github/**/*" recursive=true # CI/CD 配置
  search_file: pattern="docker*" recursive=false     # Docker 相关
  search_file: pattern=".env*" recursive=false       # 环境配置
```

#### Step C2: 对比 README 内容

读取现有 README 并逐节对比：

```markdown
## README 标准章节清单（来自 R1 C6 文档规范）

必须有的章节:
  ① Project Title + 一行描述（badge 可选）
  ② Features / 功能特性列表
  ③ Quick Start / 快速开始（安装 + 最小运行示例）
  ④ Directory Structure / 目录结构（树形图）
  ⑤ Usage / 使用指南
  ⑥ Configuration / 配置说明
  ⑦ API Reference 链接 或 文档链接
  ⑧ Contributing / 开发指南
  ⑨ License / 许可证

推荐有的章节:
  ⑩ Screenshots / Demo 截图
  ⑪ Roadmap / 版本规划
  ⑫ Changelog 链接
  ⑬ FAQ / 常见问题
```

**差异检测维度**：

| 维度 | 检测方法 | 差异类型 |
|------|----------|----------|
| 目录结构 | 对比 README 中的树形图 vs 实际 `list_dir` 结果 | 🟡 过时/缺失/多余 |
| 安装命令 | 对比 README 中的 install 步骤 vs 实际依赖管理器 | 🔴 命令不匹配 |
| 技术栈 | 对比 README 中声明的框架 vs 实际 package.json 依赖 | 🟡 不一致 |
| Badge 状态 | 检查 CI badge 链接是否有效 | 🔵 链接失效 |
| 示例代码 | 运行 README 中的示例验证可用性 | 🔴 代码过时 |
| 版本号 | 对比 README vs package.json 中的 version | 🟡 不同步 |

#### Step C3: 输出差异报告 + 更新建议

```markdown
## README Sync Report — {project_name}

**检查时间**: {timestamp}
**README 路径**: {path_to_readme}

### 总体状态: {✅ 同步 / ⚠️ 需更新 / 🔴 严重过时}

---

## 章节完整性

| 章节 | 存在 | 状态 | 备注 |
|------|------|------|------|
| Project Title | ✅/❌ | — | — |
| Features | ✅/❌ | — | — |
| Quick Start | ✅/❌ | — | — |
| Directory Structure | ✅/❌ | {🟢/🔴} | 详情见下方 |
| Usage | ✅/❌ | — | — |
| Configuration | ✅/❌ | — | — |
| Contributing | ✅/❌ | — | — |
| License | ✅/❌ | — | — |

---

## 结构差异详情

### 目录结构
**README 中的描述**:
```
{readme_tree_snapshot}
```

**实际目录结构**:
```
{actual_tree_from_listdir}
```

**差异**:
- ➕ 实际存在但 README 未提及: {missing_items}
- ❌ README 提及但实际不存在: {ghost_items}
- 🔄 路径已变更: {moved_items}

---

## 内容差异

| 位置 | README 声称 | 实际情况 | 严重程度 | 建议 |
|------|------------|----------|----------|------|
| Installation | `npm install` | 项目使用 pnpm | 🔴 | 改为 `pnpm install` |
| Version | v1.2.0 | package.json 显示 v1.5.3 | 🟡 | 更新版本号 |
| Framework | Vue 3 | 实际使用 React 18 | 🔴 | 修正技术栈声明 |
| CI Badge | Travis CI | 实际使用 GitHub Actions | 🟡 | 替换 badge |

---

## 自动生成的 README 更新草案

> 以下是基于实际项目状态生成的更新建议。
> **请人工审核后采纳。**

```markdown
# {Updated README Content Draft}
```
```

---

### Mode D: ADR 架构决策记录

#### Step D1: 收集决策上下文

通过交互方式收集决策要素：

```yaml
所需信息（按优先级）：
  required:
    title: 决策简短标题（如 "选择 TypeScript 严格模式"）
    status: proposed / accepted / deprecated / superseded
    context: 决策背景和问题陈述
    decision: 最终决定是什么
    consequences: 决策带来的影响（正面 + 负面）
  optional:
    alternatives: 考虑过的替代方案（至少 1 个）
    date: 决策日期
    decision_drivers: 影响决策的关键因素
    references:
      related_issue: 关联的 issue / PR 编号
      related_adr: 关联的其他 ADR（如替代了 ADR-003）
```

**如果用户未提供完整信息**，使用以下引导提问：

```
请提供以下信息以生成 ADR（可直接回答或跳过）：
1. 这个决策解决什么问题？（背景）
2. 我们考虑了哪些选项？（替代方案）
3. 最终选择了什么方案？为什么？（决定 + 理由）
4. 这个决定有什么影响？（后果）
```

#### Step D2: 按 MADR 模板格式化

使用 [MADR (Markdown Architecture Decision Record)](https://adr.github.io/madr/) 规范：

```markdown
# {ADR_NUMBER}: {Title}

- Status: {status}
- Date: {date}

## Context

{context — 问题陈述和决策背景}

## Decision

{最终选择的方案及其理由}

## Consequences

### Advantages
- {positive_consequence_1}
- {positive_consequence_2}

### Disadvantages
- {negative_consequence_1}
- {negative_consequence_2}

## Alternatives Considered

### Option A: {name}
- **优点**: ...
- **缺点**: ...
- **未选择原因**: ...

### Option B: {name}
- **优点**: ...
- **缺点**: ...
- **未选择原因**: ...

## References
- {related_issue_link}
- {related_adr_link}
- {technical_references}
```

*ADR 格式遵循 [MADR 2.1.0](https://adr.github.io/madr/)*

#### Step D3: 写入目标目录

```yaml
输出路径: docs/decisions/{NNNN}-{slugified-title}.md

编号规则:
  - 自动递增: 扫描 docs/decisions/ 目录已有 ADR 编号
  - 取最大 N + 1 作为新编号
  - 4 位零填充: ADR-0001, ADR-0002, ...
  - 如果目录不存在则创建

索引维护: 更新 docs/decisions/index.md（如果存在）
```

**ADR index.md 格式**：

```markdown
# Architecture Decisions

<!-- ADR_INDEX_START — 请勿手动修改此标记之间的内容 -->
<!-- DO NOT EDIT BETWEEN THESE MARKERS -->

| # | Title | Status | Date |
|---|-------|--------|------|
| [ADR-0001](0001-title.md) | {title} | {status} | {date} |
| [ADR-0002](0002-title.md) | {title} | {status} | {date} |

<!-- ADR_INDEX_END -->
```

---

## 输出质量保证（Evidence 收集方法论）

为确保生成文档的准确性，采用以下交叉验证策略（参考 Claw Code PARITY.md 思路）：

```
Evidence Collection Pipeline:
  Source Code ──→ Extract ──→ Raw Evidence ──→ Cross-Validate ──→ Final Output
       ↑                                              │
       │                                              ↓
       └─────────── Verification Loop ←──────── Discrepancy Report
```

验证规则：
- V1: 符号存在性 — 生成的每个 API 条目必须能在源码中找到对应定义
- V2: 签名一致性 — 文档中的参数签名必须与源码完全匹配（含类型注解）
- V3: 示例可运行 — README 中的代码示例语法必须在语义上合法
- V4: 版本一致性 — 引用的版本号必须与构建配置文件一致
- V5: 链接可达性 — 文档中的外部链接和交叉引用必须指向存在的目标

**当发现证据冲突时的处理策略**：

| 冲突类型 | 处理方式 | 输出标注 |
|----------|----------|----------|
| 文档注释与签名矛盾 | 以签名为准，标注 `⚠️ 注释可能过时` | 在冲突行添加警告 |
| README 与实际不符 | 两者都保留，标注差异 | Mode C 差异表格 |
| CHANGELOG 缺失提交 | 标注 `📋 可能遗漏` | 在对应位置补充 |
| ADR 引用不存在的外部 ADR | 保留引用但添加 `❓ 待确认` | References 区域 |

---

## 模式选择速查表

| 用户需求 | 推荐模式 | 输出位置 | 耗时估算 |
|----------|----------|----------|----------|
| "生成 API 文档" | Mode A | `docs/api-reference.md` | 中等 |
| "更新 CHANGELOG" | Mode B | `CHANGELOG.md` | 较短 |
| "检查 README 是否过时" | Mode C | stdout（报告） | 短 |
| "记一个架构决策" | Mode D | `docs/decisions/NNNN-title.md` | 取决于用户输入 |
| "全量文档刷新" | full = A+B+C | 多文件 | 较长 |

---

## 与增强层其他模块的协作关系

```
CODEBUDDY.md
  ├── skills/commit-auditor/SKILL.md
  │     └── Step 1 提交解析 + CC 正则 → 本 Skill Mode B CHANGELOG 生成
  ├── hooks/change-log.mdc
  │     └── 变更条目数据 → 本 Skill Mode B Unreleased 区块联动
  │     └── 变更条目 → 本 Skill Mode C README 同步触发信号
  ├── rules/engineering-baseline/RULE.mdc
  │     └── C6 文档规范 → 本 Skill README 章节完整性基准 + API 文档注释标准
  ├── agents/code-reviewer/agent.md
  │     └── 代码审查结果 → 本 Mode A 文档缺失发现的输入源
  └── rules/test-coverage/RULE.mdc
        └── 测试覆盖数据 → 本 Mode A API 文档测试示例补充
```

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.3.0 | 2026-04-27 | 升级版本号到 0.3.0，修复 whenToUse 格式为 `> ` 多行格式，清理标题多余#符号，修复 YAML 格式 |
| 0.2.0 | 2026-04-27 | 完整翻译 YAML 描述为中文，修复 YAML 格式（whenToUse 改为 multiline） |
| 0.1.0 | 2026-04-07 | Phase 4 初始实现（四种模式 + Evidence 方法论 + H3 联动） |

---

## 后续规划（Phase 5）

- [ ] 集成 TypeDoc / MkDocs Material / rustdoc 等原生文档工具链
- [ ] Mode C 增加 `--fix` 参数直接写入更新后的 README
- [ ] Mode B 支持多 monorepo 包独立 CHANGELOG + root 汇总
- [ ] ADR 支持决策影响分析（哪些代码受此 ADR 影响）
- [ ] 文档过期自动巡检（定期任务：每周检查文档 freshness）
- [ ] 多语言 i18n 文档生成支持
