---
name: audit
type: prompt
description: >
  执行增强层全量审计流水线。依次调用 state-flow-auditor(S1)、
  commit-auditor(S2)、dependency-auditor(S3)、security-scanner(A2)，
  汇总为统一的 Audit Dashboard Report。支持范围选择。
allowed_tools:
  - use_skill           # 调用各审计技能
  - read_file           # 读取项目文件
  - search_content      # 搜索代码内容
  - search_file         # 文件搜索
  - list_dir            # 目录列表
  - execute_command     # 仅限 git/npm/ls/cat/grep/find 等只读命令
  - ask_followup_question # 确认审计范围或选择
progress_message: "正在执行全量审计流水线..."
version: 0.2.0
references:
  - .codebuddy/skills/state-flow-auditor/SKILL.md
  - .codebuddy/skills/commit-auditor/SKILL.md
  - .codebuddy/skills/dependency-auditor/SKILL.md
  - .codebuddy/agents/security-scanner/agent.md
---

# 全量审计 — /audit

你是一个**全量审计流水线协调员**。请按顺序执行四个维度的审计，最终汇总为一份统一的 Audit Dashboard Report。

## 输入参数

- `{args}`: 可选审计范围（默认="full"，可选 "quick"/"security-only"/"deps-only"/"state-only"）

### 范围映射表

| 参数 | 执行的审计维度 | 预计耗时 |
|------|---------------|---------|
| `full` (默认) | S1 + S2 + S3 + A2 (全部四维) | ~8min |
| `quick` | S2 + A2 (提交+安全，最常用) | ~3min |
| `security-only` | A2 + S3 (安全+依赖漏洞) | ~4min |
| `deps-only` | S3 (仅依赖审计) | ~2min |
| `state-only` | S1 (仅状态流审计) | ~3min |

## 审计流水线

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│ Step 1:      │    │ Step 2:      │    │ Step 3:      │    │ Step 4:      │
│ 状态流审计   │ →  │ 提交审计     │ →  │ 依赖审计     │ →  │ 安全扫描     │
│ S1           │    │ S2           │    │ S3           │    │ A2           │
│ (可跳过)     │    │ (quick保留)   │    │ (可跳过)     │    │ (security保留)│
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │                  │
       ▼                  ▼                  ▼                  ▼
  StateFlowReport   CommitReport      DepReport          SecurityReport
                                                            │
                                                            ▼
                                                    ┌─────────────┐
                                                    │ Step 5: 综合  │
                                                    │ Dashboard     │
                                                    └─────────────┘
```

### Step 1: 状态流审计 (S1)

> 跳过条件：args="security-only" 或 "deps-only"

调用 `state-flow-auditor` 技能：

**收集项**:
- [ ] 项目是否为前端应用？若非前端则标记 N/A
- [ ] 状态流拓扑图（状态源→派生→消费者）
- [ ] 反模式检测结果（单一数据源违反/直接 mutation/冗余依赖）
- [ ] 一致性问题列表
- [ ] 评分: ___/10

### Step 2: 提交审计 (S2)

> 始终执行（除非明确排除）

调用 `commit-auditor` 技能：

**收集项**:
- [ ] 最近 10 条提交信息合规性（Conventional Commits）
- [ ] 提交规模分析（是否原子提交、小步提交）
- [ ] 变更安全性评分
- [ ] 敏感信息泄露检测
- [ ] Commit Audit Report
- [ ] 评分: ___/10

### Step 3: 依赖审计 (S3)

> 跳过条件：args="quick" 或 "security-only" 或 "state-only"

调用 `dependency-auditor` 技能：

**收集项**:
- [ ] 依赖版本一致性（lock file vs 声明文件）
- [ ] 已知漏洞清单 (CVE)
- [ ] 过期依赖列表
- [ ] 许可证合规性（GPL/AGPL/MIT/Apache 分类）
- [ ] 评分: ___/10

### Step 4: 安全扫描 (A2)

> 始终执行（除非 args="deps-only" 或 "state-only"）

派发 `security-scanner` 代理：

**收集项**:
- [ ] OWASP Top 10 各维度评分
- [ ] 漏洞详情列表（含 CWE 编号）
- [ ] 敏感信息硬编码检测
- [ ] 加密实践审计
- [ ] 评分: ___/10

### Step 5: 综合仪表盘

合并以上所有结果为统一视图。

## 输出格式

```markdown
# 📊 Audit Dashboard Report

**项目**: {project_name}
**审计时间**: {timestamp}
**范围**: {scope}
**流水线版本**: 0.2.0

## 总体评分

| 维度 | 评分 | 状态 | 关键发现数 |
|------|------|------|-----------|
| 状态流 | X/10 | ✅⚠️❌N/A | {n} |
| 提交质量 | X/10 | ✅⚠️❌ | {n} |
| 依赖安全 | X/10 | ✅⚠️❌N/A | {n} |
| 安全扫描 | X/10 | ✅⚠️❌ | {n} |
| **综合** | **X/40** | **{grade}** | |

> 注: 综合评分仅计算已执行的维度；N/A 不计入总分基数。

## 🔴 Critical (需立即修复)

| 来源 | 问题 | 文件 | 严重度 |
|------|------|------|--------|
| {S1/S2/S3/A2} | {summary} | {path}:{line} | 🔴Critical |

## ⚠️ Warning (建议尽快修复)

| 来源 | 问题 | 建议 |
|------|------|------|
| {source} | {summary} | {fix} |

## ℹ️ Info (可选优化)

- [{source}] {tip}

## 下一步行动

1. **[P0]** {action} — 预计 {effort}
2. **[P1]** {action} — 预计 {effort}
3. **[P2]** {action} — 预计 {effort}
```

## 快捷别名

- `/audit` — 全量审计 (4 维)
- `/audit quick` — 快速审计 (提交+安全)
- `/audit security-only` — 仅安全和依赖
- `/audit full` — 显式全量

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| **v0.2.0** | 2026-04-27 | 升级版本号，修复 YAML 格式（去掉引号），清理 references 格式，更新流水线版本 |
| v0.1.0 | 2026-04-07 | 初始版本 |
