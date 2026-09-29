---
name: commit-auditor
description: "提交审计技能 — 当用户需要审计 Git 提交信息规范性、检查 Conventional Commits 合规性、检测敏感信息泄露时使用。提供结构化的提交审计工作流，包含格式验证、范围一致性检查和全扫描。"
version: "0.2.0"
category: auditing
whenToUse: |
  当需要审计 Git 提交信息的规范性时使用。
  检查 commit message 是否符合 Conventional Commits 规范。
  检测提交中是否包含敏感信息（API Key、密码等）。
  验证变更范围与提交描述是否一致。
input:
  - "目标 Git 仓库路径（默认当前工作区）"
  - "审计范围：latest（最近一次） / N（最近 N 次） / range（commit 范围）"
output: >
  结构化的 Commit Audit Report，包含格式合规性评分、问题清单、
  敏感信息检测结果和修复建议
references:
  - source: ref/claw-code-main/rust/crates/runtime/src/policy_engine.rs
    extracted: PolicyEngine 条件+动作规则引擎（可执行策略模式）
  - source: .codebuddy/rules/engineering-baseline/RULE.mdc
    extracted: C2 提交规范检查清单（Conventional Commits + 原子提交）
  - source: .codebuddy/rules/safe-refactor/RULE.mdc
    extracted: R3 小步提交规则（单一语义变更）
---

# S2: Commit Auditor — 提交审计技能

## 用途

对 Git 提交进行系统化审计，确保提交信息的规范性、一致性和安全性。

**核心能力**：
1. **格式合规性** — 检查是否符合 Conventional Commits 规范
2. **语义一致性** — 验证变更内容是否与提交描述匹配
3. **安全扫描** — 检测敏感信息泄露风险
4. **工程规范对照** — 对照 engineering-baseline 的 C2 检查清单

---

## 审计工作流

### Step 1: 收集提交数据

获取目标范围内的提交记录：

```
输入: 审计范围（默认 latest = 最近一次提交）

执行:
  execute_command: git log -{N} --format="%H|%s|%b|%an|%ae|%ai" --no-merges
  execute_command: git diff --stat {commit_hash}~1..{commit_hash}   # 变更文件列表
  execute_command: git diff {commit_hash}~1..{commit_hash}             # 完整 diff（用于安全扫描）
```

**只读操作优先**：不修改任何文件或执行写操作。

### Step 2: 格式合规性检查

#### C2-1: Conventional Commits 格式

校验提交信息结构：

```regex
# 标准格式模板
:^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\(.+\))?:\s.{1,50}

# subject 行要求：
# - type 必须是预定义值之一
# - scope 可选（括号包裹）
# - 冒号后空格 + subject（1-50 字符）
# - 不允许句号结尾（中文除外）
```

**违规示例**：
| 提交信息 | 问题 | 等级 |
|----------|------|------|
| `update code` | 缺少 type 前缀 | 🔴 error |
| `fix bug` | subject 过于笼统 | 🟡 warning |
| `feat(auth): Add login support.` | subject 末尾有多余句号 | 🔵 info |
| `WIP: working on it` | 包含 WIP 标记 | 🔴 error |

#### C2-2: Body 规范

如果提交包含 body（空行后的详细说明），检查：
- [ ] 每行不超过 72 字符
- [ ] 使用祈使语气（"Add" 而非 "Added"）
- [ ] 解释「为什么」而非仅描述「做了什么」

#### C2-3: 原子性

- [ ] 单次提交是否包含**单一语义变更**
- [ ] 是否混入了不相关改动（如 feat 中含 fix）

### Step 3: 语义一致性验证

对比**提交描述**与**实际变更**：

| 维度 | 校验方法 | 工具 |
|------|----------|------|
| type 与变更类型匹配 | feat 应新增功能，fix 应修复 bug | diff 统计 |
| scope 与变更模块匹配 | scope(auth) 时变更应集中在 auth/ 目录 | 文件路径分析 |
| subject 概括准确性 | subject 应反映主要变更内容 | diff 关键词提取 |
| 变更范围合理性 | 大量变更应有详细 body 说明 | diff --stat 行数 |

**不一致标记条件**：
- subject 说"优化性能"但实际只改了注释 → 🟡 描述不准确
- type 是 docs 但修改了 src/ 下的业务代码 → 🔴 类型错误
- scope(ui) 但变更全部在 api/ 下 → 🔴 范围错误

### Step 4: 安全扫描

扫描 diff 内容中的敏感信息：

**高危模式**（必须拦截）：

```
# API Key / Token
(api[_-]?key|apikey|secret[_-]?key|token|auth[_-]?token)[=:]\s*["'][a-zA-Z0-9]{20,}['"]

# 密码
(password|passwd|pwd)[=:]\s*["'].+?['"]

# 私钥
(-----BEGIN\s+(RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----)

# 数据库连接串
(jdbc:mysql|mongodb://|postgres://|redis://)\S+:\S+@

# AWS 凭证
(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY)[=]\s*\S+
```

**中危模式**（警告提醒）：

```
# 内部 IP / 域名
(\d{1,3}\.){3}\d{1,3}(:\d+)?

([a-z0-9\-]+\.)+(internal|local|dev|staging)\.\w+

# 硬编码环境地址
(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?

# Debug 残留
(console\.log|console\.debug|debugger|print\(.*password)
```

### Step 5: 输出报告

生成结构化 Commit Audit Report：

```markdown
## Commit Audit Report

**审计时间**: {timestamp}
**审计范围**: {range}
**提交总数**: {N}

### 总体评分: {A/B/C/D/F}

| 维度 | 得分 | 状态 |
|------|------|------|
| 格式合规 | X/10 | ✅/⚠️/❌ |
| 语义一致 | X/10 | ✅/⚠️/❌ |
| 安全扫描 | X/10 | ✅/⚠️/❌ |

### 逐条审查结果

#### Commit #{n}: {short_hash}

- **Message**: `{subject}`
- **Author**: `{author}` | **Time**: `{date}`
- **Files**: {changed_files_count} files (+{additions} -{deletions})

| 检查项 | 结果 | 详情 |
|--------|------|------|
| 格式规范 | ✅/❌ | ... |
| 语义一致 | ✅/⚠️/❌ | ... |
| 安全扫描 | ✅/🔴 | 发现 N 个安全问题 |

**问题清单**:
1. {issue_1}
2. {issue_2}

**修复建议**:
- {suggestion}

---

### 安全摘要

| 严重程度 | 数量 | 涉及提交 |
|----------|------|----------|
| 🔴 高危 | {n} | {commits} |
| 🟡 中危 | {n} | {commits} |
| 🔵 低危 | {n} | {commits} |
| ✅ 通过 | {n} | {commits} |

### 统计趋势

- 平均 subject 长度: {avg_len} 字符
- type 分布: feat({n}) fix({n}) refactor({n}) chore({n}) ...
- 含 body 的提交占比: {pct}%
- 合规率: {compliance_rate}%
```

## 评分标准

### 格式合规分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| 缺少 type 前缀或使用非标准 type | -4 |
| subject 超过 50 字符 | -1 |
| subject 以大写开头（非专有名词） | -1 |
| subject 以句号结尾 | -0.5 |
| 使用 WIP / tmp / placeholder 等 | -3 |
| body 行超过 72 字符（每处） | -0.5 |

### 语义一致分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| type 与实际变更类型不符 | -4 |
| scope 与变更模块不一致 | -3 |
| subject 无法概括变更内容 | -2 |
| 多个独立变更混在一个 commit | -3 |
| 无 body 且变更超过 5 个文件 | -1 |

### 安全扫描分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| 高危模式命中（每个实例） | -10（直接 F） |
| 中危模式命中（每个实例） | -2 |
| debug 残留（每个实例） | -0.5 |

### 总评等级映射

| 总分 | 等级 | 含义 |
|------|------|------|
| 27-30 | A | 优秀，无需改进 |
| 21-26 | B | 良好，有轻微问题 |
| 11-20 | C | 及格，需改进多个维度 |
| 1-10 | D | 不合格，存在严重问题 |
| 0 或高危安全 | F | 危险，必须立即处理 |

## 与增强层其他模块的协作关系

```
CODEBUDDY.md
  ├── rules/engineering-baseline/RULE.mdc
  │     └── 本 Skill 的 C2 检查清单来源
  ├── rules/safe-refactor/RULE.mdc
  │     └── R3 小步提交规则交叉引用
  └── hooks/change-log.mdc
        └── 可联动：审计结果写入变更日志
```

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 修复 whenToUse 字段格式为 multiline 格式 |
| 0.1.0 | 2026-04-06 | Phase 2 初始实现 |

## 后续规划（Phase 3）

- [ ] 集成 `git-secrets` 或 `truffleHog` 作为 command 类型深度扫描
- [ ] 支持自定义团队提交规范（通过配置文件定义 type 列表）
- [ ] 与 CI/CD 流水线集成——PR 自动触发审计
- [ ] 历史趋势图表（提交质量随时间变化）
- [ ] 支持自动修正建议生成（amend commit message）
