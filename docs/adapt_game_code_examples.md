# adapt_game_code 可直接复制调用的示例

> 前置条件：Unity 已连接、Ollama 已启动（默认 http://localhost:11434，模型 gemma4:26b）、
> 知识库已构建（`Server/data/game-rag-knowledge-base/build_game_rag.py`）。

## 两步流程

`adapt_game_code` 不独立运行——它需要先通过搜索工具获取参考代码。
完整流程是：**搜索 → 适配（预览）→ 适配（写入）**。

---

## 示例 1：给 Tower.cs 添加攻击伤害系统

### 步骤 1：搜索参考代码

```
search_game_code("tower defense tower attack damage projectile target", top_k=5)
```

返回 JSON 类似：

```json
{
  "status": "success",
  "results": [
    {
      "id": "abc123",
      "game_name": "TowerDefense",
      "file_path": "Assets/Scripts/Tower/Tower.cs",
      "class_name": "Tower",
      "method_name": "Attack",
      "code_type": "method_detail",
      "score": 0.92,
      "summary": "Tower Attack method with projectile instantiation, sound effects, and target tracking coroutine",
      "reuse_hint": "Adapt Attack() and MoveProjectile() to current project. Match projectile types, sound manager references, and GameManager.Instance patterns.",
      "text": "public void Attack() { ... }"
    }
  ]
}
```

### 步骤 2：预览适配结果（不写入）

把搜索结果 JSON 完整粘贴为 `reference_results_json` 参数：

```
adapt_game_code(
  goal="给 Tower.cs 的攻击方法添加伤害值字段、暴击概率和伤害计算逻辑",
  target_script_path="Assets/Scripts/Tower/Tower.cs",
  reference_results_json="<此处粘贴步骤1的完整JSON字符串>",
  apply=false
)
```

**预期返回字段：**
- `status`: "preview"
- `generated_code`: 生成的完整 C# 代码（带有 damange/ critChance/dmgDealt 等字段）
- `adaptation_notes`: 改动说明清单
- `planned_edits`: 逐个编辑点
- `project_style_summary`: 检测到的项目风格（uses_singleton_pattern, private_field_style 等）
- `apply_ready`: true（代码非空，可以写入）
- `warnings`: 任何需要注意的问题

### 步骤 3：确认无误后写入

```
adapt_game_code(
  goal="给 Tower.cs 的攻击方法添加伤害值字段、暴击概率和伤害计算逻辑",
  target_script_path="Assets/Scripts/Tower/Tower.cs",
  reference_results_json="<同上JSON>",
  apply=true
)
```

**写入后的额外字段：**
- `status`: "applied" / "applied_with_compile_errors"
- `write_result`: Unity manage_script(update) 的返回值
- `compile_result`: 编译检查结果
- `logs_excerpt`: 相关 Unity 日志

---

## 示例 2：给 GameManager.cs 添加波次难度递增

### 步骤 1：搜索参考代码

```
search_game_code_graph("wave spawn difficulty scaling enemy count multiplier", top_k=5, traverse_depth=2)
```

> 用 `search_game_code_graph` 而非 `search_game_code`，因为波次系统通常跨 GameManager → wave 配置 → enemy spawn 多个类。

### 步骤 2：预览

```
adapt_game_code(
  goal="在 GameManager 的 spawn() 协程中添加波次难度递增：根据 waveNumber 提升敌人血量、速度和数量",
  target_script_path="Assets/Scripts/GameManager.cs",
  reference_results_json="<粘贴 search_game_code_graph 的返回 JSON>",
  apply=false,
  context_depth=5
)
```

**注意 `context_depth=5`**：GameManager 是大型中心脚本，更多上下文样本帮助 Ollama 理解项目风格
（单例模式、SerializeField 命名习惯、UI 更新方式等）。

### 步骤 3：写入

```
adapt_game_code(
  goal="在 GameManager 的 spawn() 协程中添加波次难度递增：根据 waveNumber 提升敌人血量、速度和数量",
  target_script_path="Assets/Scripts/GameManager.cs",
  reference_results_json="<同上JSON>",
  apply=true,
  context_depth=5
)
```

---

## 示例 3：给 Tower.cs 添加升级系统（最复杂）

### 步骤 1：搜索多轮

```
search_game_code("tower upgrade level cost money", top_k=5, class_name="Tower")
```

```
search_game_code("tower manager upgrade button UI", top_k=3)
```

将两轮搜索结果合并为一个 JSON 数组传给 `adapt_game_code`：

```json
[
  {<第一轮结果>},
  {<第二轮结果>}
]
```

### 步骤 2：预览

```
adapt_game_code(
  goal="给 Tower 添加升级系统：level 字段、升级花费递增、攻击范围/攻速随等级提升、与 GameManager.TotalMoney 交互",
  target_script_path="Assets/Scripts/Tower/Tower.cs",
  reference_results_json="[<合并的搜索结果>]",
  apply=false,
  context_depth=5
)
```

---

## 更多 realistic goal 参考

| 目标脚本 | 实用 goal |
|----------|----------|
| `Assets/Scripts/Tower/Tower.cs` | "添加 SellTower 方法返回 50% 金币" |
| `Assets/Scripts/Tower/Tower.cs` | "让攻击支持 Debuff（减速/毒），用 List<IDebuff> 管理" |
| `Assets/Scripts/Tower/Tower.cs` | "修复 getTargetDistance 的空引用风险" |
| `Assets/Scripts/GameManager.cs` | "添加暂停菜单和 Time.timeScale 控制" |
| `Assets/Scripts/GameManager.cs` | "波次间隔显示倒计时文字" |
| `Assets/Scripts/GameManager.cs` | "添加 GetTowerCount 方法统计场上塔数量" |
| `Assets/Scripts/Enemy/Enemy.cs` | "添加血条 UI 跟随" |
| `Assets/Scripts/Enemy/Enemy.cs` | "添加掉落金币动画" |

---

## reference_results_json 快速指南

`adapt_game_code` 接受以下任一格式：

1. **search_game_code 的完整返回**（JSON 字符串）：
   ```json
   {"status":"success","results":[...]}
   ```

2. **search_game_code_graph 的完整返回**（JSON 字符串）：
   ```json
   {"status":"success","vector_results":[...],"graph_results":[...],"call_chain":[...]}
   ```

3. **手动构造的引用数组**（至少要有 `text` 或 `content` 字段）：
   ```json
   [{"text":"public void Attack() {...}", "class_name":"Tower", "game_name":"TowerDefense"}]
   ```

`parse_reference_results` 会自动从 `results`、`vector_results`、`matched_references` 字段提取引用。

---

## 错误码速查

| error_code | 原因 | 修复方式 |
|-----------|------|---------|
| `invalid_reference_json` | reference_results_json 不是合法 JSON | 检查粘贴是否完整，不要有省略号 |
| `unity_unavailable` | Unity 未连接 | 确认 Unity Editor 打开、MCP 连接正常 |
| `target_not_found` | target_script_path 对应的文件不存在 | 先用 create 创建空 .cs |
| `invalid_target_path` | 路径不以 Assets/ 开头或不以 .cs 结尾 | 修正为 Assets/.../*.cs 格式 |
| `ollama_unavailable` | Ollama 未启动或模型未拉取 | `ollama pull gemma4:26b` |
| `generation_failed` | Ollama 返回了不完整的响应 | 重试或简化 goal |
| `empty_generated_code` | 生成代码为空 | 检查 goal 是否太模糊 |
| `write_failed` | Unity write 失败 | 检查 manage_script update 权限 |
