---
name: rag-knowledge
description: Unity API RAG knowledge retrieval skill. Use when users ask about Unity API usage, class methods, properties, code examples, or need to search Unity Script Reference documentation. Covers 29,746 PDF documents (2,209 classes + 27,537 methods) from Unity 2022.3 Script Reference.
trigger:
  - Unity API query (class, method, property names)
  - Unity documentation search
  - Unity code example requests
  - "How to use" Unity API questions
  - Unity Script Reference lookup
---

# Unity API RAG Knowledge Skill

## Purpose

Search and retrieve Unity 2022.3 Script Reference documentation using semantic vector search powered by bge-m3 embeddings and ChromaDB.

## Knowledge Base Coverage

- **2,209 class-level documents**: Full class descriptions, properties, methods, constructors, operators, messages
- **27,537 method-level documents**: Method declarations (with overloads), parameters, return values, descriptions, code examples
- **Total: 29,746 API documents** indexed with bge-m3 1024-dimensional embeddings

## Usage

### Search API Documentation

When user asks about Unity API:

1. Extract the key API terms from the user's question
2. Use `knowledge_search` MCP tool to search the knowledge base
3. Format the results in a clear, actionable response

Example queries:
- "How to add a component to a GameObject?" → search "GameObject AddComponent"
- "What properties does Transform have?" → search "Transform properties"
- "How to use Raycast?" → search "Physics Raycast"
- "Camera render method" → search "Camera Render"

### Search Parameters

- `query`: Natural language or API name search
- `n_results`: Number of results (1-20, default 5)
- `search_type`: "all" | "class" | "method"

### Response Format

Structure your response as:

1. **Direct Answer**: Answer the question using the search results
2. **API Details**: Show relevant declarations, parameters, descriptions
3. **Code Example**: Include code examples from the documentation
4. **Related APIs**: Mention related classes/methods found in the results

## MCP Tools

### knowledge_search
Search the Unity API documentation knowledge base.

```
knowledge_search(query="GameObject AddComponent", n_results=5, search_type="all")
```

### knowledge_index
Check index status or add new documents.

```
knowledge_index(action="status")
knowledge_index(action="index", json_dir="/path/to/json")
```

## Architecture

```
Unity Script Reference PDF (29,746)
  → pdfplumber extraction (pdf_parser.py)
  → Structured JSON (unity_api_json_v3/)
  → Text conversion (api_data_to_text)
  → bge-m3 Embedding (1024-dim)
  → ChromaDB Vector Store (chroma_db_v3/)
  → knowledge_search MCP tool
```

## C# 代码检索扩展

除了 Unity API 文档检索外，以下路径包含高质量的 C# 代码可供参考：

### CCGS 引擎参考（含 ✅/❌ 正反例）

| 模块 | 路径 | 内容 |
|------|------|------|
| 最佳实践 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/current-best-practices.md` | C# 9+、DOTS/ECS、Input System、Addressables |
| 物理 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/physics.md` | AddForce vs velocity、NonAlloc API |
| 渲染 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/rendering.md` | RenderGraph、GPU Instancing、SRP Batcher |
| 动画 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/animation.md` | Animator、BlendTree、Animation Rigging |
| 输入 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/input.md` | Input System Package、Rebinding |
| 网络 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/networking.md` | Netcode for GameObjects、ServerRpc/ClientRpc |
| UI | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/ui.md` | UI Toolkit vs UGUI |
| 导航 | `reference2/Claude-Code-Game-Studios-main/docs/engine-reference/unity/modules/navigation.md` | NavMesh、AI 导航 |

### Template 开源项目（生产级 C# 代码）

| 领域 | 项目 | .cs 数 | 路径 |
|------|------|--------|------|
| 设计模式 | Unity-Design-Pattern | 120 | `referrence/Template/Unity-Design-Pattern-master/` |
| 网络框架 | Mirror | 924 | `referrence/Template/Mirror-master/` |
| 完整 RPG | RPGCore | 425 | `referrence/Template/RPGCore-main/` |
| MOBA 游戏 | UnityMoba | 914 | `referrence/Template/UnityMoba-master/` |
| 游戏框架 | UnityGameFramework | 288 | `referrence/Template/UnityGameFramework-master/` |

**检索方式**：使用 `search_content` 或 `read_file` 工具直接读取上述路径中的 .cs 或 .md 文件。

## Limitations

- Currently only covers Unity Script Reference (API docs)
- Code examples are extracted from PDF and may have minor formatting issues
- Search is semantic (not exact match); for precise API names, use `search_type` filter
- Knowledge base must be built before search works (run `batch_rag_v3.py`)
- CCGS 引擎参考和 Template 项目需通过 `read_file` 直接读取，不经过 RAG 索引
