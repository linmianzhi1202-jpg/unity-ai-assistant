# Game Source Code RAG Knowledge Base

为你的 Unity C# 游戏源码构建语义检索知识库。

## 架构概览

```
game_source/（你的游戏源码）
  └── 游戏项目/Assets/Scripts/*.cs
      │
      ▼ build_game_rag.py
  ┌─────────────────────────────┐
  │ CodeProcessor               │  扫描 .cs，按类/方法智能分块
  │ EmbeddingProvider           │  使用配置中的本地嵌入模型
  │ ChromaDB (game_source_code) │  向量存储
  └──────────┬──────────────────┘
             │
    ┌────────▼─────────┐
    │ Unity MCP Platform │  search_game_code(query) 工具
    │ CodeBuddy          │  game_code_stats()       工具
    └────────────────────┘
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 放入游戏源码

把你的 Unity 游戏项目（含 `Assets/Scripts/`）放入 `game_source/` 目录：

```
game_source/
  ├── MyGame1/
  │   └── Assets/Scripts/...
  ├── MyGame2/
  │   └── Assets/Scripts/...
  └── ...
```

### 3. 构建知识库

双击项目根目录下的 `build_game_rag.bat`（即 `Server/` 的上一级目录）完成构建；也可带参数运行：`build_game_rag.bat --stats` 查看统计、`build_game_rag.bat --clear` 全量重建。

首次构建会：
1. 扫描 `game_source/` 下的 Unity 项目和 `.cs` 文件
2. 提取类、字段和方法并生成代码块
3. 使用 `config/config_game.yaml` 中配置的嵌入模型生成向量（默认 `BAAI/bge-small-zh-v1.5`）
4. 写入 ChromaDB（集合名 `game_source_code`）
5. 同时生成 `data/game_code_graph.json`，供跨类检索和调用关系查询

### 4. 通过 CodeBuddy 使用

重启 MCP 服务后，CodeBuddy 可使用以下工具：

- `search_game_code(query, top_k, game_name, class_name, code_type)` — 搜索相似代码
- `game_code_stats()` — 查看知识库统计信息

**使用示例**（在 CodeBuddy 对话中）：

```
用户: 帮我查看塔防游戏中有哪些关于建筑攻击的代码
→ CodeBuddy 调用: search_game_code("建筑攻击 防御塔 塔攻击", top_k=5)
→ 返回 Tower.cs 中的 Attack(), MoveProjectile() 等方法代码片段
```

## 目录结构

```
game-rag-knowledge-base/
├── config/
│   └── config_game.yaml          # 配置文件
├── game_source/                  # 放你的游戏源码（约定目录）
├── data/
│   ├── chromadb/                 # ChromaDB 数据（构建后生成）
│   └── game_code_graph.json      # 代码关系图（构建后生成）
├── logs/
│   └── game_rag.log              # 日志
├── src/
│   ├── __init__.py
│   ├── code_processor.py         # C# 代码处理器（扫描+分块）
│   └── game_code_search.py       # 检索接口
├── build_game_rag.py             # 一键构建脚本
├── requirements.txt
└── README.md
```

## 配置说明

编辑 `config/config_game.yaml`：

```yaml
source:
  root_directory: "game_source"   # 游戏源码根目录（相对本目录）
  max_file_size_kb: 200

embedding:
  provider: "local"
  local:
    model_name: "BAAI/bge-small-zh-v1.5"

vector_store:
  persist_directory: "data/chromadb"
  collection_name: "game_source_code"

retrieval:
  top_k: 5
  score_threshold: 0.6
```

## 分块策略

每个 `.cs` 文件被分成两种块：

| 类型 | 内容 | 用途 |
|------|------|------|
| `class_overview` | using + class声明 + 字段/属性 | 了解类整体结构 |
| `method_detail` | 类名 + 完整方法代码 + 注释 | 查询具体实现逻辑 |

每个块携带的元数据：
- `game_name`：所属游戏
- `class_name`：类名
- `method_name`：方法名
- `code_type`：类概览/方法详情
- `file_path`：文件路径
- `line_start`/`line_end`：行号范围

## CLI 命令

在项目根目录双击 `build_game_rag.bat`，或带参数运行：

```powershell
build_game_rag.bat              # 构建知识库
build_game_rag.bat --clear      # 重建（清空后重新导入）
build_game_rag.bat --stats      # 查看统计信息
build_game_rag.bat --verbose    # 详细日志
```

## 当前检索能力

本模块已经同时生成向量索引和代码关系图：

- `search_game_code`：按语义检索类、方法和文件代码块。
- `search_game_code_graph`：在语义结果上扩展相关类、继承关系和调用链。
- `knowledge_graph_search_game_code`：通过统一 MCP 图谱入口查询当前项目源码；`mode` 会映射为 `top_k` 和 `traverse_depth`。
- `knowledge_unified_search(..., sources=["game_code_graph"])`：在统一检索中加入当前项目源码关系。

它仍然是代码结构图 + 向量检索的混合实现，不等同于用大模型重新生成一套通用知识图谱。当前项目源码索引与 `Server/data/base_kb/` 的 Unity API 知识库完全分开。


跨项目模式库位于 `Server/data/base_kb/lightrag_db_game_code`，由 `Server/scripts/build_game_code_lightrag.py` 构建，查询入口是 `knowledge_graph_search_external_game_code`；它与本目录的当前项目源码 RAG 分开维护。
