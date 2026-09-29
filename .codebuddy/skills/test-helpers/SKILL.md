---
name: test-helpers
description: 测试辅助 — 创建测试辅助函数，减少重复
version: 0.2.0
category: game-development
whenToUse: >
  当需要创建测试辅助函数、减少测试代码重复时使用此技能。
  适用于：为项目实际引擎、语言和系统定制 `tests/helpers/` 库，
  让每个开发者编写更少的样板代码和更多的断言。
  在 /test-setup 搭建框架后运行，或多个测试文件重复相同的设置样板时。
input:
  - 项目根目录路径（默认当前工作区）
  - 系统名称或模式参数（[system-name] / all / scaffold）
output:
  - tests/helpers/ 目录，包含引擎特定的辅助文件
  - 基础辅助库（断言、工厂、场景运行器）
  - 系统特定的辅助函数（每个系统一个工厂文件）
tools:
  - read_file
  - search_content
  - search_file
  - write_to_file
  - execute_command
context: inline
---

# 测试辅助技能

## 技能概述

创建测试辅助函数，减少重复。当常见的设置、拆卸和断言模式被抽象为辅助函数时，编写测试用例会更快且更一致。此技能生成适合项目实际引擎、语言和系统的 `tests/helpers/` 库 — 让每个开发者编写更少的样板代码和更多的断言。

**适用场景**：
- 在 `/test-setup` 搭建框架后（首次）
- 当多个测试文件重复相同的设置样板时
- 当开始为新系统编写测试时

**输出**：`tests/helpers/` 目录，包含引擎特定的辅助文件

## 使用方式

- 通过 Agent 触发：当用户说「测试辅助」或相关需求时，Agent 应自动加载此 Skill
- 手动触发：`/skill test-helpers [参数]`

**参数模式**：
- `/test-helpers [system-name]` — 为特定系统生成辅助函数（例如 `/test-helpers combat`）
- `/test-helpers all` — 为所有有测试文件的系统生成辅助函数
- `/test-helpers scaffold` — 仅生成基础辅助库（无系统特定的辅助函数）；首次运行时使用此选项
- 无参数 — 如果不存在辅助函数则运行 `scaffold`，否则运行 `all`

---

## 阶段 0: 解析参数

**参数**: `$ARGUMENTS[0]` (空白 = 智能默认）

从参数确定模式：

| 参数 | 模式 | 输出 |
|----------|------|----------|
| `[system-name]` | 系统特定的辅助函数 | `tests/helpers/[system]_factory.[ext]` |
| `all` | 所有系统的辅助函数 | 每个系统一个文件 |
| `scaffold` | 仅基础辅助库 | 基础断言、工厂、场景辅助函数 |
| 无参数 | 智能默认 | 如果 helpers/ 不存在则 `scaffold`，否则 `all` |

---

## 阶段 1: 检测引擎和语言

读取 `.claude/docs/technical-preferences.md` 并提取：
- `Engine:` 值
- `Language:` 值
- 测试部分中的 `Framework:`

如果引擎未配置：
> "引擎未配置。首先运行 `/setup-engine`。"

**报告发现**：
- "引擎：[引擎]。语言：[语言]。框架：[框架]。"
- "现有辅助函数：[找到 / 未找到]。将 [创建 / 跳过] 基础库。"

---

## 阶段 2: 加载现有测试模式

扫描测试目录以查找已使用的模式：

```
全局搜索模式="tests/**/*_test.*"（所有测试文件）
```

对于代表性样本（最多 5 个文件），读取测试文件并提取：
- 设置模式（`before_each` / `setUp` / fixtures 的编写方式）
- 常见断言模式（最常断言什么）
- 对象创建模式（测试中如何实例化游戏对象或场景）
- 模拟/存根模式（如何替换依赖项）

这确保生成的辅助函数与项目现有样式匹配，而不是通用模板。

**还要读取**：
- `design/gdd/systems-index.md` — 了解存在哪些系统
- 范围内的 GDD — 了解需要测试哪些数据类型和值
- `docs/architecture/tr-registry.yaml` — 将需求映射到测试系统

---

## 阶段 3: 生成引擎特定的辅助函数

根据检测到的引擎，生成基础辅助文件：

### Godot 4（GDUnit4 / GDScript）

**基础辅助函数** (`tests/helpers/game_assertions.gd`)：

```gdscript
## [项目名称] 测试的游戏特定断言实用程序。
## 使用 GdUnitAssertions 扩展领域特定的辅助函数。
##
## 用法：
##   var assert = GameAssertions.new()
##   assert.health_in_range(entity, 0, entity.max_health)

class_name GameAssertions
extends RefCounted

## 断言一个值在包含性范围 [min_val, max_val] 内。
## 用于 GDD 中定义了边界的任何公式输出。
static func assert_in_range(
    value: float,
    min_val: float,
    max_val: float,
    label: String = "value"
) -> void:
    assert(
        value >= min_val and value <= max_val,
        "%s %.2f is outside expected range [%.2f, %.2f]" % [label, value, min_val, max_val]
    )

## 断言在可调用块期间发出了信号。
## 用法：assert_signal_emitted(entity, "health_changed", func(): entity.take_damage(10))
static func assert_signal_emitted(
    obj: Object,
    signal_name: String,
    action: Callable
) -> void:
    var emitted := false
    obj.connect(signal_name, func(_args): emitted = true)
    action.call()
    assert(emitted, "Expected signal '%s' to be emitted, but it was not." % signal_name)

## 断言可调用对象未发出信号。
static func assert_signal_not_emitted(
    obj: Object,
    signal_name: String,
    action: Callable
) -> void:
    var emitted := false
    obj.connect(signal_name, func(_args): emitted = true)
    action.call()
    assert(not emitted, "Expected signal '%s' NOT to be emitted, but it was." % signal_name)

## 断言父级中在路径处存在节点。
static func assert_node_exists(parent: Node, path: NodePath) -> void:
    assert(
        parent.has_node(path),
        "Expected node at path '%s' to exist." % str(path)
    )
```

**工厂辅助函数** (`tests/helpers/game_factory.gd`)：

```gdscript
## 用于创建测试游戏对象的工厂函数。
## 返回为单元测试配置的最小对象（不需要场景树）。
##
## 用法：var player = GameFactory.make_player(health: 100)

class_name GameFactory
extends RefCounted

## 创建用于测试的最小类玩家对象。
## 根据需要覆盖字段。
static func make_player(health: int = 100) -> Node:
    var player = Node.new()
    player.set_meta("health", health)
    player.set_meta("max_health", health)
    return player
```

**场景辅助函数** (`tests/helpers/scene_runner_helper.gd`)：

```gdscript
## 基于场景的集成测试实用程序。
## 为常见模式包装 GdUnitSceneRunner。

class_name SceneRunnerHelper
extends GdUnitTestSuite

## 加载场景并等待一帧以完成 _ready()。
func load_scene_and_wait(scene_path: String) -> Node:
    var scene = load(scene_path).instantiate()
    add_child(scene)
    await get_tree().process_frame
    return scene
```

### Unity（NUnit / C#）

**基础辅助函数** (`tests/helpers/GameAssertions.cs`)：

```csharp
using NUnit.Framework;
using UnityEngine;

/// <summary>
/// [项目名称] 测试的游戏特定断言实用程序。
/// 使用领域特定的辅助函数扩展 NUnit 的 Assert。
/// </summary>
public static class GameAssertions
{
    /// <summary>
    /// 断言一个值在包含性范围 [min, max] 内。
    /// 用于 GDD 公式部分中定义的任何公式输出。
    /// </summary>
    public static void AssertInRange(float value, float min, float max, string label = "value")
    {
        Assert.That(value, Is.InRange(min, max),
            $"{label} ({value:F2}) is outside expected range [{min:F2}, {max:F2}]");
    }

    /// <summary>
    /// 断言在操作期间引发了 UnityEvent 或 C# 事件。
    /// </summary>
    public static void AssertEventRaised(ref bool wasCalled, System.Action action, string eventName)
    {
        wasCalled = false;
        action();
        Assert.IsTrue(wasCalled, $"Expected event '{eventName}' to be raised, but it was not.");
    }

    /// <summary>
    /// 断言 GameObject 上存在组件。
    /// </summary>
    public static void AssertHasComponent<T>(GameObject obj) where T : Component
    {
        var component = obj.GetComponent<T>();
        Assert.IsNotNull(component,
            $"Expected GameObject '{obj.name}' to have component {typeof(T).Name}.");
    }
}
```

**工厂辅助函数** (`tests/helpers/GameFactory.cs`)：

```csharp
using UnityEngine;

/// <summary>
/// 用于在不加载场景的情况下创建最小测试对象的工厂方法。
/// </summary>
public static class GameFactory
{
    /// <summary>
    /// 创建具有指定名称的 GameObject 用于测试。
    /// </summary>
    public static GameObject MakeGameObject(string name = "TestObject")
    {
        var go = new GameObject(name);
        return go;
    }

    /// <summary>
    /// 创建类型 T 的 ScriptableObject 用于数据驱动的测试。
    /// 测试后在 teardown 中使用 Object.DestroyImmediate 销毁。
    /// </summary>
    public static T MakeScriptableObject<T>() where T : ScriptableObject
    {
        return ScriptableObject.CreateInstance<T>();
    }
}
```

### Unreal Engine（C++）

**基础辅助函数** (`tests/helpers/GameTestHelpers.h`)：

```cpp
#pragma once

#include "CoreMinimal.h"
#include "Misc/AutomationTest.h"

/**
 * [项目名称] 自动化测试的游戏特定断言宏和辅助函数。
 * 在任何需要领域特定断言的测试文件中包含。
 *
 * 用法：
 *   GAME_TEST_ASSERT_IN_RANGE(TestName, DamageValue, 10.0f, 50.0f, TEXT("Damage"));
 */
 
// 断言浮点值在包含性范围 [Min, Max] 内
#define GAME_TEST_ASSERT_IN_RANGE(TestName, Value, Min, Max, Label) \
    TestTrue( \
        FString::Printf(TEXT("%s (%.2f) in range [%.2f, %.2f]"), Label, Value, Min, Max), \
        (Value) >= (Min) && (Value) <= (Max) \
    )

// 断言 UObject 指针有效（非 null，未垃圾回收）
#define GAME_TEST_ASSERT_VALID(TestName, Ptr, Label) \
    TestTrue( \
        FString::Printf(TEXT("%s is valid"), Label), \
        IsValid(Ptr) \
    )

// 断言 Actor 在世界中（成功生成）
#define GAME_TEST_ASSERT_SPAWNED(TestName, ActorPtr, ClassName) \
    TestNotNull( \
        FString::Printf(TEXT("Spawned actor of class %s"), TEXT(#ClassName)), \
        ActorPtr \
    )

/**
 * 用于创建最小测试世界的辅助函数。
 * 记得在 teardown 中调用 World->DestroyWorld(false)。
 */
namespace GameTestHelpers
{
    inline UWorld* CreateTestWorld(const FString& WorldName = TEXT("TestWorld"))
    {
        UWorld* World = UWorld::CreateWorld(EWorldType::Game, false);
        FWorldContext& WorldContext = GEngine->CreateNewWorldContext(EWorldType::Game);
        WorldContext.SetCurrentWorld(World);
        return World;
    }
}
```

---

## 阶段 4: 生成系统特定的辅助函数

对于 `[system-name]` 或 `all` 模式，为每个系统生成一个辅助函数文件：

读取系统的 GDD 以提取：
- 数据类型（实体类型、组件名称）
- 公式变量及其边界
- 边缘情况部分中提到的常见测试场景

生成 `tests/helpers/[system]_factory.[ext]`，包含特定于该系统对象的工厂函数。

**战斗系统示例**（Godot/GDScript）：

```gdscript
## 战斗系统测试的工厂和断言辅助函数。
## 由 /test-helpers combat 于 [日期] 生成。
## 基于：design/gdd/combat.md

class_name CombatTestFactory
extends RefCounted

const DAMAGE_MIN := 0
const DAMAGE_MAX := 999  # 来自 GDD：伤害公式上限

## 创建用于伤害公式测试的最小攻击者对象。
static func make_attacker(attack: float = 10.0, crit_chance: float = 0.0) -> Node:
    var attacker = Node.new()
    attacker.set_meta("attack", attack)
    attacker.set_meta("crit_chance", crit_chance)
    return attacker

## 创建用于伤害接收测试的最小目标对象。
static func make_target(defense: float = 0.0, health: float = 100.0) -> Node:
    var target = Node.new()
    target.set_meta("defense", defense)
    target.set_meta("health", health)
    target.set_meta("max_health", health)
    return target

## 断言伤害输出在 GDD 指定的边界内。
static func assert_damage_in_bounds(damage: float) -> void:
    GameAssertions.assert_in_range(damage, DAMAGE_MIN, DAMAGE_MAX, "damage")
```

---

## 阶段 5: 写入输出

展示将创建的内容的摘要：

```
## 要创建的测试辅助函数

基础辅助函数（引擎：[引擎]）：
- tests/helpers/game_assertions.[ext]
- tests/helpers/game_factory.[ext]
- [引擎特定的额外内容]

系统辅助函数（[模式]）：
- tests/helpers/[system]_factory.[ext]  ← 来自 [system] GDD
```

询问："我可以将这些辅助函数文件写入 `tests/helpers/` 吗？"

**永远不要覆盖现有文件。** 如果文件已存在，报告：
> "跳过 `[path]` — 已存在。如果要重新生成，请手动删除该文件。"

写入后：判定：**完成** — 辅助函数文件已创建。

**在测试中使用它们**：
- Godot：自动导入 `class_name` — 不需要显式导入
- Unity：添加 `using` 指令或引用测试程序集
- Unreal：`#include "tests/helpers/GameTestHelpers.h"`

---

## 阶段 6: 协作协议

- **永远不要覆盖现有辅助函数** — 它们可能包含手写自定义。仅生成尚不存在的新文件
- **生成的代码是起点** — 生成的工厂函数使用元数据模式以保持简单；一旦代码存在，就使其适应实际类结构
- **辅助函数应反映 GDD** — 辅助函数中的边界和常量应追溯到 GDD 公式部分，而不是发明值
- **在写入之前询问** — 始终在 `tests/` 中创建文件之前确认

---

## 下一步

- 如果尚未搭建测试框架，运行 `/test-setup`
- 使用 `/dev-story` 实施故事 — 辅助函数减少了新测试文件中的样板代码
- 运行 `/skill-test` 以验证可能需要辅助函数覆盖的其他技能

---

## CodeBuddy 增强集成

此技能与 CodeBuddy 增强层集成：
- 使用 `parity-audit` Skill 进行质量审计
- 使用 `cost-tracker` Skill 估算成本影响
- 使用 `context-compactor` Skill 优化上下文

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 删除"原始英文提示词"部分，完整翻译正文为中文，修复 YAML frontmatter 格式 |
| 0.1.0 | 2026-04-26 | 从 Claude Code Game Studios 迁移并中文化 |
