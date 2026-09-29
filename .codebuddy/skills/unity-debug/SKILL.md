---
name: unity-debug
version: 0.1.0
category: unity
description: "Unity 调试诊断技能 — 封装 MCP 日志/编译/Profiler 工具为系统化诊断工作流，支持错误解析和 API 查询"
triggers:
  - "调试 Unity"
  - "Unity 编译错误"
  - "Unity 运行时错误"
  - "Unity 性能问题"
  - "NullReferenceException"
---

# Unity 调试诊断技能

## 概述

本技能封装 MCP Server 的日志读取、编译检查和 Profiler 工具为系统化诊断工作流，自动解析 Unity 常见错误码并通过 RAG 查找正确 API 用法。

## 诊断工作流

### 流程 1：编译错误诊断

**触发**：用户报告编译错误、CS 错误码

**步骤**：
1. `check_compile_errors` — 获取编译错误列表
2. 解析错误码和位置
3. `knowledge_search` — 查询正确 API 用法（如 MCP RAG 可用）
4. 生成修复建议

**常见编译错误速查**：

| 错误码 | 含义 | 典型修复 |
|--------|------|----------|
| CS0103 | 名称不存在 | 添加 `using` 引用或检查拼写 |
| CS0246 | 找不到类型 | 安装包或添加 Assembly Definition 引用 |
| CS1061 | 成员不存在 | 检查 API 版本，查询废弃 API 替代 |
| CS0117 | 静态成员不存在 | 检查是否使用了实例成员语法 |
| CS0029 | 类型不兼容 | 添加显式类型转换 |
| CS0161 | 缺少返回值 | 确保所有路径有 return |

**示例编排**：
```
用户: "Unity 报了 CS0103 错误"
→ check_compile_errors()
→ 解析: "CS0103: The name 'Input' does not exist in the current context"
→ 诊断: Legacy Input 未导入，或应使用 Input System
→ 建议: using UnityEngine; 或迁移到 UnityEngine.InputSystem
```

### 流程 2：运行时错误诊断

**触发**：NullReferenceException、MissingReferenceException 等

**步骤**：
1. `get_unity_logs` — 读取 Console 日志
2. 解析调用栈
3. `get_game_object_info` — 检查相关对象状态
4. 定位空引用来源

**常见运行时错误**：

| 异常类型 | 根因模式 | 诊断方法 |
|----------|----------|----------|
| NullReferenceException | 未赋值引用/对象已销毁 | 检查 SerializeField 赋值、生命周期 |
| MissingReferenceException | 对象被销毁但引用残留 | 检查 Destroy 后访问 |
| MissingComponentException | 缺少必需组件 | 检查 AddComponent / RequireComponent |
| ArgumentOutOfRangeException | 集合越界 | 检查 List/Array 边界 |
| StackOverflowException | 无限递归 | 检查属性 getter 自引用 |

**NullReference 诊断模板**：
```
1. 读取日志: get_unity_logs(search_term="NullReference")
2. 提取调用栈中的脚本名和行号
3. 检查常见原因:
   - [SerializeField] 字段未在 Inspector 中赋值
   - GetComponent<>() 返回 null（组件未添加）
   - Find()/FindObjectOfType() 返回 null（对象不存在）
   - 对象已 Destroy 但仍有引用（用 == null 检查而非 is null）
4. 建议: 添加空检查 + Debug.LogError 定位
```

### 流程 3：性能诊断

**触发**：用户报告卡顿、GC Spike、帧率低

**步骤**：
1. `get_profiler_data` — 获取性能数据
2. `list_high_poly_objects` — 检查高面数对象
3. 分析瓶颈（CPU/GPU/GC）
4. 对应 `unity-performance` Rule 生成优化建议

**性能诊断清单**：
- [ ] CPU 热路径：`get_profiler_data(action="worst_cpu_frames", count=5)`
- [ ] GC 分配：`get_profiler_data(action="worst_gc_frames", count=5)`
- [ ] 高面数对象：`list_high_poly_objects(threshold=100000)`
- [ ] 检查 Update 中的 `GetComponent`/`Find`/`new` 分配
- [ ] 检查 Debug.Log 是否在生产代码中
- [ ] 检查字符串 `+` 拼接是否在热路径中

## MCP 工具映射

| 诊断步骤 | MCP 工具 | 关键参数 |
|----------|----------|----------|
| 读取日志 | `get_unity_logs` | search_term, show_errors, limit |
| 编译检查 | `check_compile_errors` | — |
| CPU 分析 | `get_profiler_data` | action="worst_cpu_frames", count |
| GC 分析 | `get_profiler_data` | action="worst_gc_frames", count |
| 高面数检测 | `list_high_poly_objects` | threshold |
| 对象状态 | `get_game_object_info` | gameobject_path, include_components |

## 错误码 → Rule 交叉引用

| 错误码 | 相关 Rule | 检查项 |
|--------|-----------|--------|
| CS0103/CS0246 | `unity-csharp-patterns` §2 | 查找/引用模式 |
| CS1061 | `unity-csharp-patterns` §7 | 废弃 API 替代 |
| NullReference | `unity-csharp-patterns` §1.1 | 组件引用缓存 |
| GC Spike | `unity-performance` §1 | 热路径零分配 |
| 性能低 | `unity-performance` §2-3 | NonAlloc/SRP Batcher |

## 使用约束

1. 日志查询限制最近 100 条，避免上下文过大
2. 编译错误修复后需 `refresh_unity` 刷新
3. 性能诊断需在 Play Mode 下进行
4. 诊断建议应附上对应的 Rule 章节引用
