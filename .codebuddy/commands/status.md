---
name: status
type: prompt
description: >
  显示 CodeBuddy 增强层系统健康仪表盘。汇总所有模块的启用状态、
  models.json 路由配置、最近活动统计和系统完整性自检结果。
allowed_tools:
  - read_file              # 读取配置文件和状态文件
  - search_content         # 搜索日志和指标
  - list_dir               # 列出模块目录确认存在性
progress_message: "正在收集系统状态..."
version: 0.2.0
references:
  - .codebuddy/settings.json
  - .codebuddy/models.json
  - .codebuddy/agents/*/agent.md
  - .codebuddy/skills/*/SKILL.md
  - .codebuddy/rules/*/RULE.mdc
  - .codebuddy/hooks/*.mdc
---

# 系统状态仪表盘 — /status

你是一个**系统健康监控员**。请收集并展示 CodeBuddy 增强层的完整运行状态。

## 输入参数

- `{args}`: 可选查看维度（默认="overview"，可选 "detail" / "routing" / "modules"）

## 数据收集流程

### Step 1: 读取核心配置

读取以下文件获取系统状态：

1. **settings.json** → 模块启用状态
2. **models.json** → 路由配置与 profile 映射
3. **CODEBUDDY.md** → 版本信息和 phase 标记

### Step 2: 模块清单验证

遍历以下目录，确认每个声明的模块文件是否存在且 frontmatter 合规：

- `.codebuddy/agents/` — 每个 agent 应有 agent.md`
- `.codebuddy/skills/` — 每个 skill 应有 SKILL.md`
- `.codebuddy/rules/` — 每个 rule 应有 RULE.mdc`
- `.codebuddy/hooks/` — 每个 hook 应有 .mdc 文件`
- `.codebuddy/commands/` — 每个 command 应有 .md 文件

### Step 3: 交叉引用完整性检查

- 每个 agent.md 的 references 中引用的文件是否存在？
- 每个 SKILL.md 的 references 是否可解析？
- settings.json 中 enabled 的模块是否有对应文件？

## 输出格式

### overview 模式（默认）

```markdown
# �¥️ CodeBuddy Enhancement Layer — Status Dashboard

**Version**: {version} | **Phase**: {phase} | **Time**: {timestamp}

## System Health: ✅ Healthy / ⚠️ Degraded / ❌ Critical

### Module Summary

| Category | Enabled | Total | Health |
|----------|---------|-------|--------|
| Agents   | {n}/{total} | {total} | ✅/⚠️❌ |
| Skills   | {n}/{total} | {total} | ✅/⚠️❌ |
| Rules    | {n}/{total} | {total} | ✅/⚠️❌ |
| Hooks    | {n}/{total} | {total} | ✅/⚠️❌ |
| Commands | —       | {total} | ✅/⚠️❌ |
| **Total** | **{enabled_sum}/{module_count}** | **{module_count}** | |

### Model Routing Status

| Profile | Assigned To | Status |
|---------|------------|--------|
| deep-thinking | {agents+skills} | ✅ Active |
| fast-scan    | {agents+skills} | ✅ Active |
| balanced-review | {agents+skills} | ✅ Active |
| orchestration | {agents+skills} | ✅ Active |

### Quick Checks

- [ ] settings.json valid JSON ✅/❌
- [ ] models.json valid JSON ✅/❌
- [ ] All declared modules have files ✅/❌
- [ ] Cross-references resolved ✅/❌
- [ ] CODEBUDDY.md version matches settings ✅/❌
```

### detail 模式

在 overview 基础上增加每个模块的详细状态卡片：

```markdown
## Module Details

### Agent: {name} ({id})
- **File**: `.codebuddy/agents/{id}/agent.md` ✅/❌ Missing
- **Enabled**: yes/no
- **Model Profile**: {profile_name}
- **Frontmatter Valid**: ✅/❌
- **Last Referenced By**: {command or skill name}

### Skill: {name} ({id})
- **File**: `.codebuddy/skills/{id}/SKILL.md` ✅/❌ Missing
- **Enabled**: yes/no
- **Model Profile**: {profile_name}
- **Category**: {category}
...
```

### routing 模式

聚焦 models.json 的路由详情：

```markdown
## Model Routing Detail

### Profile Definitions
{每个 profile 的完整定义}

### Agent Routing Matrix
| Agent | Profile | Token Budget | Reason |
|-------|---------|--------------|--------|

### Skill Routing Matrix
| Skill | Profile | Token Budget | Reason |
|-------|---------|--------------|--------|

### Fallback Behavior
{fallback 配置详情}
```

### modules 模式

纯模块清单视图（用于调试缺失模块）：

```markdown
## Full Module Inventory

### Declared in settings.json (should exist):
- [✅/❌] agents/{name}
- [✅/❌] skills/{name}
- ...

### Found on disk (may be undeclared):
- [undeclared] agents/{name}
- [undeclared] skills/{name}
- ...
```

### policy 模式

策略统计仪表盘（Phase 9 新增）：

**Step 1: 读取策略日志**

读取 `.codebuddy/logs/policy-stats-{date}.jsonl` 获取当前会话的策略触发记录。

**Step 2: 计算统计指标**

对每条规则计算：
- trigger_count: 触发次数
- adopt_count: 采纳次数
- bypass_count: 绕过次数
- adopt_rate: 采纳率
- last_trigger: 最近触发时间

**Step 3: 输出格式**

```markdown
# 📊 Policy Stats Dashboard

**Session**: {session_id} | **Duration**: {duration} | **Triggers**: {total}

## Rule Performance

| Rule | Triggers | Adopted | Bypassed | Adopt Rate | Last Trigger |
|------|----------|---------|----------|------------|--------------|
| P1   | 5        | 3       | 2        | 60.0%      | 5 min ago    |
| P2   | 3        | 3       | 0        | 100%       | 10 min ago   |
| ...  | ...      | ...     | ...      | ...        | ...          |

## Summary

- **Overall Adopt Rate**: {rate}% ({adopted}/{total})
- **Most Active Rule**: {rule_id} ({rule_name})
- **Most Bypassed Rule**: {rule_id} ({rule_name})
- **Zero Bypass Rules**: {list}

## Recent Bypasses (if any)

1. **{rule_id}** @ {time} ago: "{context}"
   - Bypass Reason: "{reason}"
```

## 快捷别名

- `/status` — 系统概览
- `/status detail` — 详细模块状态
- `/status routing` — 路由配置详情
- `/status modules` — 模块清单
- `/status policy` — **策略统计仪表盘 (Phase 9 新增)**
- `/status performance` — 性能统计视图 (调用 S7/H5)
