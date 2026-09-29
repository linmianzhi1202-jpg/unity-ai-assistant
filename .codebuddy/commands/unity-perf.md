# /unity-perf — Unity 性能分析

触发 Unity 专项性能分析，使用 `unity-performance` Rule 检查性能瓶颈和反模式。

## 分析维度

1. **GC 分配热点**：Update/FixedUpdate 中的分配、字符串拼接、LINQ 在热路径
2. **物理查询优化**：NonAlloc API 使用率、Compound vs Mesh Collider
3. **渲染管线效率**：SRP Batcher、GPU Instancing、Draw Call 数量
4. **对象池使用**：Instantiate/Destroy 频率、ObjectPool 覆盖率
5. **Burst + Jobs**：可并行计算的 CPU 密集逻辑识别
6. **内存管理**：NativeArray 使用、Profiler.BeginSample 覆盖

## 输出格式

```
## Unity 性能分析报告

### 🔴 严重问题（必须修复）
- [文件:行号] 问题描述 + ✅ 正确做法

### 🟡 优化建议（推荐改进）
- [文件:行号] 问题描述 + ✅ 推荐做法

### 🟢 良好实践（值得保留）
- [文件:行号] 已正确使用的模式

### 📊 性能指标
- 热路径 GC 分配：X 处
- NonAlloc API 覆盖率：X%
- ObjectPool 覆盖率：X%
- Burst+Jobs 覆盖率：X%
```

## 关联 Rules

- `unity-performance` — 性能优化正反例专项
- `engine-code` — 引擎代码规则（热路径零分配）

## 关联 Agents

- `performance-analyst` — 性能分析师
- `engine-programmer` — 引擎程序员
