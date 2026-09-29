# /unity-review — Unity C# 专项代码审查

触发 Unity 专项六维代码审查，使用 `unity-csharp-patterns` 和 `unity-performance` Rules 检查 C# 代码质量。

## 审查维度

1. **C# 编码规范**：`[SerializeField] private` vs `public`、命名约定、组件缓存
2. **Unity 反模式**：Find/FindObjectOfType/SendMessage 禁令、Unity 对象 null 检查
3. **GC 分配管理**：热路径零分配、NonAlloc API、ObjectPool 使用
4. **数据驱动**：ScriptableObject 配置、无硬编码数值
5. **帧率独立**：deltaTime 使用、Update vs FixedUpdate 正确选择
6. **现代特性**：C# 9+ record/init、DOTS/ECS ISystem、Addressables async

## 适用范围

- `Assets/Scripts/**/*.cs`
- 排除：Third-party 插件、Generated 代码

## 关联 Rules

- `unity-csharp-patterns` — C# 编码正反例专项
- `unity-performance` — 性能优化正反例专项
- `gameplay-code` — 游戏性代码规则
- `engine-code` — 引擎代码规则
- `ui-code` — UI 代码规则
- `network-code` — 网络代码规则

## 关联 Agents

- `unity-specialist` — Unity 引擎专家
- `gameplay-programmer` — 游戏性程序员
- `code-reviewer` — 通用代码审查
