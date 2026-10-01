# Unity MCP + GraphRAG

为 Codex、CodeBuddy 等 MCP 客户端提供 Unity 编辑器操作、API 检索、源码参考和资产库能力。

```text
Codex / CodeBuddy → FastMCP → ChromaDB / LightRAG
                          → UnityBridge → Unity 编辑器插件
```

默认使用 BAAI/bge-m3 向量检索；需要图谱关系时显式指定 `sources`。图谱使用 Ollama，默认模型 `gemma3:4b`，可通过 `UNITY_MCP_RAG_MODEL` 覆盖。缺少图谱或模型不影响 Unity 操作工具启动。

## 快速开始

1. 安装环境：在 Windows 运行 `install.bat`，自动创建虚拟环境、安装依赖并生成 MCP 配置。
2. 导入 Unity 插件：Package Manager → “Add package from disk” → 选择 `UnityPlugin/package.json`，等待编译完成。
3. 接入 MCP 客户端：将生成的 `mcp.json` 合并到 CodeBuddy（`%USERPROFILE%\.codebuddy\mcp.json`）或 Codex。
4. 验证连接：读取 `mcpforunity://health` 确认服务，读取 `mcpforunity://editor/state` 确认 Unity 已连接，再执行编辑器操作。

```python
knowledge_search(query="Rigidbody.AddForce", include_full_content=True)
knowledge_unified_search(query="GameObject 和 Component 的关系", sources=["vector", "api_graph"])
```

> Unity API 知识库（22702 条 API，约 738MB）不随仓库分发，需从 GitHub Release 下载，详见 [使用说明](使用说明.md)。当前项目源码需要另行放入 `Server/data/game-rag-knowledge-base/game_source/` 并构建，不能放进 `base_kb/`。

详细安装、环境变量、换电脑部署与故障排查见 [使用说明](使用说明.md)。已实现工具列表以客户端 `tools/list` 为准；`run_tests` 已接入 Unity Test Runner，支持 EditMode / PlayMode。

## 文档与验证

- [使用说明](使用说明.md)
- [Unity 自动化测试](docs/unity-test-runner.md)
- [架构与边界](docs/architecture.md)
- [知识库与检索](docs/kb-modules.md)
- [故障排查](docs/troubleshooting.md)
- [验证记录与评测方法](docs/core-pipeline-validation.md)
- [资产库工作流](docs/asset-graphrag-workflow.md)
- [源码工作流](docs/game-code-rag-workflow.md)

`.codebuddy/` 提供可选的客户端工作流。备份、会话管理和 IDE 本身的项目管理不属于 MCP 核心服务职责。
