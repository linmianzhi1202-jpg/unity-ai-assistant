---
name: cost
type: prompt
description: >
  显示当前会话成本报告 — 汇总 Token 使用量、估算成本（GLM-4 定价）、
  操作分布和优化建议。调用 S7 cost-tracker 技能生成结构化成本报告。
allowed_tools:
  - read_file              # 读取配置和日志文件
  - search_content         # 搜索 JSONL 日志
  - list_dir               # 列出日志目录
progress_message: "正在生成成本报告..."
version: 0.2.0
references:
  - .codebuddy/skills/cost-tracker/SKILL.md
  - .codebuddy/hooks/performance-monitor.mdc
  - .codebuddy/rules/policy-executable/RULE.mdc
---

# 成本报告 — /cost

你是一个**成本分析协调员**。请调用 `cost-tracker` (S7) 技能生成当前会话的成本报告。

## 输入参数

- `{args}`: 报告详细程度（默认="brief"，可选 "detail" | "full"）

## 报告级别说明

| 级别 | 说明 | 包含内容 |
|------|------|---------|
| **brief** | 简要快照 | 总成本、Token 数、调用次数 |
| **detail** | 标准报告 | brief + 类别分布 + TOP 5 操作 |
| **full** | 完整分析 | detail + Agent 分账 + 历史对比 + 优化建议 |

## 执行流程

### Step 1: 读取 H5 性能数据

从 `.codebuddy/logs/performance-{date}.jsonl` 读取当前会话的性能条目。

### Step 2: 计算聚合指标

```yaml
聚合计算:
  - total_calls: 调用次数累计
  - total_tokens: input + output tokens 累计
  - total_cost_usd: 成本累计（GLM-4 Plus $0.69/M）
  - category_breakdown: 按工具类别分账
  - tool_breakdown: 按具体工具分账
```

### Step 3: 生成报告

调用 S7 的报告生成能力。

## 输出格式

### brief 模式（默认）

```markdown
💰 **Session Cost**: ${total_cost_usd:.4f} USD
- Token: {total_tokens:,} ({input:,}/{output:,})
- Calls: {total_calls}
- Duration: {duration}
```

### detail 模式

```markdown
## 💰 Session Cost Report

**定价模型**: GLM-4 Plus ($0.69/M tokens)
**时间段**: {start} → {now} ({duration})
**会话 ID**: {session_id}

### 总览指标
| 指标 | 值 |
|------|-----|
| 工具调用次数 | {total_calls} |
| 纯工具耗时 | {total_duration_s}s |
| Token 估算 | {total_tokens:,} ({input:,}/{output:,}) |
| **总成本** | **${total_cost_usd:.4f}** |
| 均/次调用 | ${avg_cost:.4f} |
| 均/千 token | ${cost_per_1k_tokens:.4f} |

### 类别分布
| 类型 | 调用 | Token | 成本 | 占比 |
|------|------|-------|------|------|
| 读操作 | {n} | {t} | ${c} | {p}% |
| 搜索 | {n} | {t} | ${c} | {p}% |
| 编辑 | {n} | {t} | ${c} | {p}% |
| 写入 | {n} | {t} | ${c} | {p}% |
| 命令 | {n} | {t} | ${c} | {p}% |

### TOP 5 操作
| # | 工具 | 次数 | 总成本 | 均耗时 |
|---|------|-----|--------|-------|
| 1 | {tool} | {n} | ${c} | {d}ms |
| 2 | ... | ... | ... | ... |
```

### full 模式

在 detail 模式基础上增加：

```markdown
### Agent/Skill 分账（估算）

| 模块类型 | 关联操作 | 估算成本 ($) | 占比 |
|---------|---------|------------|------|
| **A1 根因调查** | read_file x N | $X.XX | X% |
| **A2 安全扫描** | search_content x M | $X.XX | X% |
| **A3 代码审查** | read_file + list_dir | $X.XX | X% |
| **A4 编排** | search + list | $X.XX | X% |
| **S1-S4 Skills** | 混合操作 | $X.XX | X% |
| **直接操作** | write/edit/command | $X.XX | X% |

### 历史趋势
| 维度 | 本次 | 上次 | 变化 |
|------|------|------|------|
| 成本 | ${cur} | ${prev} | {d}% |
| 调用 | {nc} | {np} | {dn} |

### 💡 优化建议
{基于使用模式自动生成}

1. {suggestion_1}
2. {suggestion_2}
```

### 预算预警（如果超过阈值）

```markdown
## [S7 Cost Budget Warning] — {level}

当前会话成本已超过 **${threshold}** 预警线。

### 成本仪表盘
┌──────────────────────────────────────┐
│  累计成本:   **${total} USD**       │
│  累计 Token: {tokens}K              │
│  调用次数:   {calls}                 │
└──────────────────────────────────────┘

建议: {warning_suggestion}
```

## 快捷别名

- `/cost` — 简要快照
- `/cost detail` — 标准报告
- `/cost full` — 完整分析

## 与 R5-P6 的关系

- `/cost` 是 S7 的**主动查询入口**
- R5-P6 `cost-budget-warning` 是**被动触发规则**
- 当累计成本超过阈值时，R5-P6 自动调用 S7 输出预警

## 定价参考

GLM-4 系列定价（换算为 USD）：

| 模型 | 价格 ($/M tokens) |
|------|-------------------|
| glm-4-flash | $0.00 (免费) |
| glm-4-air | $0.14 |
| **glm-4-plus (默认)** | **$0.69** |
| glm-4-long | $0.56 |
| glm-4 | $1.39 |

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| **v0.2.0** | 2026-04-27 | 升级版本号，修复 YAML 格式（去掉引号），清理 references 格式 |
| v0.1.0 | 2026-04-07 | 初始版本 |
