---
name: unity-project-bootstrap
version: 0.1.0
category: unity
description: "Unity 项目引导技能 — 提供 4 种游戏模板和包配置清单，快速搭建 Unity 项目骨架"
triggers:
  - "创建 Unity 项目"
  - "Unity 项目模板"
  - "Unity 项目脚手架"
  - "初始化 Unity 项目"
  - "Unity 新项目"
---

# Unity 项目引导技能

## 概述

本技能提供 4 种 Unity 游戏项目模板和包配置清单，帮助快速搭建符合 `unity-project-structure` Rule 的项目骨架。

## 项目模板

### 模板 1：3D 动作游戏

**适用**：第三人称/第一人称动作游戏、RPG

**核心组件**：
- CharacterController + Input System + 状态机
- 摄像机跟随系统
- 战斗系统（近战/远程）
- 敌人 AI（行为树）

**目录结构**：
```
Assets/Scripts/
├── Core/
│   ├── Events/              # 全局事件定义
│   ├── Services/            # 服务定位器
│   └── Utils/               # 通用工具
├── Gameplay/
│   ├── Combat/              # 战斗系统
│   ├── Movement/            # 移动系统
│   └── AI/                  # 敌人 AI
├── UI/
│   ├── HUD/                 # 游戏内 UI
│   └── Menus/               # 菜单界面
├── Data/
│   └── Configs/             # ScriptableObject 配置
└── Engine/
    └── Camera/              # 摄像机系统
```

**关键脚本模板**：

```csharp
// Core/Services/ServiceLocator.cs
public class ServiceLocator : MonoBehaviour {
    public static ServiceLocator Instance { get; private set; }
    private Dictionary<Type, object> _services = new();

    void Awake() {
        if (Instance != null) { Destroy(gameObject); return; }
        Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    public void Register<T>(T service) => _services[typeof(T)] = service;
    public T Get<T>() => (T)_services[typeof(T)];
}

// Gameplay/Movement/PlayerController.cs
[RequireComponent(typeof(CharacterController))]
public class PlayerController : MonoBehaviour {
    [Header("Movement Config")]
    [SerializeField] private MovementConfig _config;
    [SerializeField] private PlayerInput _input;

    private CharacterController _cc;
    private Vector3 _velocity;
    private PlayerState _state = PlayerState.Idle;

    void Awake() => _cc = GetComponent<CharacterController>();
    void FixedUpdate() => ApplyMovement();

    void ApplyMovement() {
        Vector2 input = _input.actions["Move"].ReadValue<Vector2>();
        Vector3 move = transform.right * input.x + transform.forward * input.y;
        _cc.Move(move * _config.moveSpeed * Time.fixedDeltaTime);

        if (!_cc.isGrounded)
            _velocity.y += Physics.gravity.y * _config.gravity * Time.fixedDeltaTime;
        _cc.Move(_velocity * Time.fixedDeltaTime);
    }
}
```

### 模板 2：2D 平台游戏

**适用**：2D 平台跳跃、横版动作

**核心组件**：
- Rigidbody2D + Tilemap + 碰撞层
- 平台跳跃物理
- 动画状态机

**关键脚本模板**：

```csharp
[RequireComponent(typeof(Rigidbody2D))]
public class PlatformerController : MonoBehaviour {
    [Header("Physics")]
    [SerializeField] private float moveSpeed = 8f;
    [SerializeField] private float jumpForce = 12f;
    [SerializeField] private LayerMask groundLayer;

    private Rigidbody2D _rb;
    private bool _isGrounded;
    private float _horizontalInput;

    void Awake() => _rb = GetComponent<Rigidbody2D>();

    void Update() {
        _horizontalInput = Input.GetAxis("Horizontal");
        if (Input.GetButtonDown("Jump") && _isGrounded) {
            _rb.AddForce(Vector2.up * jumpForce, ForceMode2D.Impulse);
        }
    }

    void FixedUpdate() {
        _rb.velocity = new Vector2(_horizontalInput * moveSpeed, _rb.velocity.y);
    }

    void OnCollisionEnter2D(Collision2D col) {
        if (((1 << col.gameObject.layer) & groundLayer) != 0)
            _isGrounded = true;
    }

    void OnCollisionExit2D(Collision2D col) {
        if (((1 << col.gameObject.layer) & groundLayer) != 0)
            _isGrounded = false;
    }
}
```

### 模板 3：策略游戏

**适用**：回合制策略、即时策略、战棋

**核心组件**：
- Grid 系统 + A* 寻路 + 回合管理器
- 单位选择和移动
- 地形系统

**关键脚本模板**：

```csharp
// 网格管理器
public class GridManager : MonoBehaviour {
    [SerializeField] private int _width = 20;
    [SerializeField] private int _height = 20;
    [SerializeField] private float _cellSize = 1f;

    private GridCell[,] _grid;

    void Awake() => InitializeGrid();

    void InitializeGrid() {
        _grid = new GridCell[_width, _height];
        for (int x = 0; x < _width; x++)
            for (int y = 0; y < _height; y++)
                _grid[x, y] = new GridCell(new Vector2Int(x, y));
    }

    public GridCell GetCell(Vector2Int coord) {
        if (coord.x < 0 || coord.x >= _width || coord.y < 0 || coord.y >= _height)
            return null;
        return _grid[coord.x, coord.y];
    }

    public List<GridCell> GetNeighbors(Vector2Int coord) {
        var neighbors = new List<GridCell>();
        Vector2Int[] dirs = { Vector2Int.up, Vector2Int.down, Vector2Int.left, Vector2Int.right };
        foreach (var dir in dirs) {
            var cell = GetCell(coord + dir);
            if (cell != null && cell.IsWalkable) neighbors.Add(cell);
        }
        return neighbors;
    }
}

// 回合管理器
public class TurnManager : MonoBehaviour {
    public event Action<int> OnTurnStart;
    public event Action OnTurnEnd;

    private int _currentTurn = 0;
    private List<IUnit> _units = new();

    public void StartTurn() {
        _currentTurn++;
        OnTurnStart?.Invoke(_currentTurn);
    }

    public void EndTurn() {
        OnTurnEnd?.Invoke();
        StartTurn();
    }
}
```

### 模板 4：UI 框架

**适用**：UI 密集型应用、工具类 Unity 项目、设置面板

**核心组件**：
- UI Toolkit + MVVM + 事件总线
- 页面导航系统
- 设置管理器

**关键脚本模板**：

```csharp
// UI 导航系统
public class UINavigator : MonoBehaviour {
    [SerializeField] private UIDocument _document;
    private Stack<VisualElement> _history = new();

    public void NavigateTo(string screenId) {
        var root = _document.rootVisualElement;
        var current = root.Q(className: "screen-active");
        if (current != null) {
            _history.Push(current);
            current.RemoveFromClassList("screen-active");
            current.AddToClassList("screen-hidden");
        }
        var target = root.Q(screenId);
        target?.RemoveFromClassList("screen-hidden");
        target?.AddToClassList("screen-active");
    }

    public void GoBack() {
        if (_history.Count == 0) return;
        var root = _document.rootVisualElement;
        var current = root.Q(className: "screen-active");
        current?.RemoveFromClassList("screen-active");
        current?.AddToClassList("screen-hidden");

        var previous = _history.Pop();
        previous.RemoveFromClassList("screen-hidden");
        previous.AddToClassList("screen-active");
    }
}
```

## 包配置清单

### 必装包

| 包名 | 用途 | 安装方式 |
|------|------|----------|
| `com.unity.render-pipelines.universal` | URP 渲染管线 | Package Manager |
| `com.unity.inputsystem` | 新输入系统 | Package Manager |
| `com.unity.textmeshpro` | 文本渲染 | Package Manager（通常预装） |
| `com.unity.addressables` | 异步资源加载 | Package Manager |
| `com.unity.nuget.newtonsoft-json` | JSON 序列化 | Package Manager |

### 按需安装

| 包名 | 用途 | 适用模板 |
|------|------|----------|
| `com.unity.entities` | DOTS/ECS | 高性能 3D 动作 |
| `com.unity.netcode.gameobjects` | 多人游戏 | 网络游戏 |
| `com.unity.localization` | 本地化 | 所有（国际化项目） |
| `com.unity.visualscripting` | 可视化脚本 | 快速原型 |
| `com.unity.test-framework` | 测试框架 | 所有 |
| `com.unity.probuilder` | 快速建模 | 3D 原型 |
| `com.unity.timeline` | 时间轴动画 | 过场动画 |
| `com.unity.cinemachine` | 摄像机系统 | 3D 动作/RPG |
| `com.unity.ai.navigation` | NavMesh 寻路 | 3D 动作/策略 |

### manifest.json 模板

```json
{
  "dependencies": {
    "com.unity.render-pipelines.universal": "14.0.8",
    "com.unity.inputsystem": "1.7.0",
    "com.unity.textmeshpro": "3.0.6",
    "com.unity.addressables": "1.21.19",
    "com.unity.nuget.newtonsoft-json": "3.2.1",
    "com.unity.test-framework": "1.1.33",
    "com.unity.ugui": "2.0.0",
    "com.unity.modules.physics": "1.0.0",
    "com.unity.modules.physics2d": "1.0.0"
  }
}
```

## 引导流程

1. **选择模板** → 确定项目类型和核心系统
2. **创建目录结构** → 按 `unity-project-structure` Rule 创建
3. **安装包依赖** → 按清单配置 manifest.json
4. **生成 .asmdef** → 按模块分区创建 Assembly Definition
5. **写入模板代码** → 生成核心脚本
6. **创建初始场景** → 使用 `unity-editor-control` Skill
7. **编译验证** → 使用 `unity-live-dev` Skill 的 Step 2

## 与其他 Skill 的协作

- **unity-editor-control**：步骤 6 创建初始场景
- **unity-live-dev**：步骤 7 编译验证
- **unity-project-structure Rule**：步骤 2-4 目录和分区规范
