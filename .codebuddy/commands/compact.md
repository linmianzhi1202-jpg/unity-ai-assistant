---
name: compact
type: prompt
description: >
  手动触发上下文压缩 — 当对话上下文接近模型窗口上限时，智能压缩历史对话内容，
  保留关键信息，释放 Token 空间。支持自动检测和强制压缩两种模式。
  调用 S8 context-compactor 技能执行 9-lane 行优先级压缩。
allowed_tools:
  - read_file              # 读取会话相关文件
  - search_content         # 搜索关键信息
  - list_dir               # 确认文件存在性
progress_message: "正在分析上下文并执行压缩..."
version: 0.2.0
references:
  - .codebuddy/skills/context-compactor/SKILL.md
  - .codebuddy/rules/policy-executable/RULE.mdc
---

# 上下文压缩 — /compact

你是一个**上下文压缩协调员**。请调用 `context-compactor` (S8) 技能执行智能压缩。

## 输入参数

- `{args}`: 压缩模式（默认="auto"，可选 "force" | "L1" | "L2" | "L3"）

## 压缩模式说明

| 模式 | 说明 | 触发条件 |
|------|------|---------|
| **auto** | 自动检测并选择压缩级别 | 当前 Token 使用 >= 70% 窗口 |
| **force** | 强制执行压缩（跳过检测） | 用户明确要求压缩 |
| **L1** | 轻度压缩（保留 70% 历史） | 70-80% 窗口使用 |
| **L2** | 中度压缩（保留 50% 历史） | 80-90% 窗口使用 |
| **L3** | 重度压缩（仅保留摘要） | > 90% 窗口使用 |

## 执行流程

### Step 1: Token 预算估算

使用 S8 的 `estimateTokens()` 算法：

- `estimated_tokens = ceil(text_length / 4)`
- `context_window = 128000` (GLM-4 系列)
- `usage_rate = estimated_tokens / context_window`

### Step 2: 压缩级别决策

```
if args == "force": level = "L2" (默认中度)
elif args in ["L1", "L2", "L3"]: level = args
elif usage_rate >= 0.9: level = "L3"
elif usage_rate >= 0.8: level = "L2"
elif usage_rate >= 0.7: level = "L1"
else: 跳过压缩，提示"当前上下文无需压缩"
```

### Step 3: 执行压缩

调用 S8 的 9-lane 行优先级压缩算法：

1. **行分类**（Priority 0-3）:
   - Priority 0 (Core): 任务目标、决策点、里程碑
   - Priority 1 (Section): 章节标题、分隔符
   - Priority 2 (ListItem): 列表项
   - Priority 3 (Other): 普通文本

2. **保留策略**:
   - L1: 保留 Priority 0-2，丢弃部分 Priority 3
   - L2: 保留 Priority 0-1，选择性保留 Priority 2
   - L3: 仅保留 Priority 0 和关键 Priority 1

3. **生成压缩摘要**

### Step 4: 压缩后恢复

确保恢复以下关键上下文：
- 当前任务目标和状态
- 最近编辑的文件引用
- 激活的技能和计划
- 未完成的待办事项

## 输出格式

### 压缩前确认

```markdown
🗜️ [S8 Context Compactor] 检测到上下文接近上限

当前状态:
  - 估算 Token: {estimated:,} / {window:,} ({usage_pct}%)
  - 对话轮次: {turn_count}
  - 触发原因: {trigger_reason}

压缩方案:
  - 级别: {level} ({level_desc})
  - 预计释放: ~{freed_tokens:,} tokens
  - 保留内容: {preserved_elements}

是否执行压缩？[Y/n]
```

### 压缩完成

```markdown
## 📦 上下文压缩摘要

**压缩时间**: {timestamp}
**原始 Token**: {original_tokens:,} → **压缩后**: {compressed_tokens:,} (-{reduction_pct}%)
**压缩级别**: {level}

### 已完成任务
- [x] {completed_task_1}
- [x] {completed_task_2}

### 当前任务上下文
- **目标**: {current_goal}
- **状态**: {current_status}
- **待办**: {pending_tasks}

### 关键文件引用
- `{file_path_1}`: {brief_description}

### 重要决策
1. {decision_1}

### 恢复点
- 技能: {active_skills}
- 计划: {active_plan}
```

### 跳过压缩

```markdown
✅ [S8 Context Compactor] 当前上下文状态良好

- 估算 Token: {estimated:,} / {window:,} ({usage_pct}%)
- 结论: 无需压缩（使用率 < 70%）

建议: 继续当前对话，当使用率超过 70% 时会自动提示。
```

## 快捷别名

- `/compact` — 自动检测并压缩
- `/compact force` — 强制执行压缩
- `/compact L2` — 指定压缩级别

## 与 R5-P5 的关系

- `/compact` 是 S8 的**手动触发入口**
- R5-P5 `compact-on-context-bloat` 是**自动触发规则**
- 两者最终都调用 S8 执行压缩逻辑

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| **v0.2.0** | 2026-04-27 | 升级版本号，修复 YAML 格式（去掉引号），清理 references 格式 |
| v0.1.0 | 2026-04-07 | 初始版本 |
