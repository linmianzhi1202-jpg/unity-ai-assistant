# 知识库与检索

知识库按实际数据目录和 manifest 管理。`knowledge_modules` 列出模块信息，`knowledge_index(action="status")` 返回向量集合文档数；目录和清单状态不等于检索质量已验收。

| 数据 | 目录 | 入口 |
| --- | --- | --- |
| Unity API 向量 | `Server/data/base_kb/chroma_db_v3` | `knowledge_search`、默认 `knowledge_unified_search` |
| Unity API 图谱 | `Server/data/base_kb/lightrag_db_v3_structured` | `sources=["api_graph"]` |
| 游戏源码 RAG（当前项目） | `Server/data/game-rag-knowledge-base`（构建产物在 `data/`） | `search_game_code`、`search_game_code_graph`、`knowledge_graph_search_game_code`、`sources=["game_code_graph"]` |
| 可选跨项目 LightRAG 扩展 | `Server/data/base_kb/lightrag_db_game_code` | `knowledge_graph_search_external_game_code`、`sources=["external_game_graph"]` |
| 资产库 | `Server/data/asset_library` | [资产库工作流](asset-graphrag-workflow.md) |
| 扩展模块清单 | `Server/data/ext_kb` | `knowledge_modules`；发现目录不表示自动加入检索源 |

向量沿用 `BAAI/bge-m3`，不重建既有索引。图谱默认 `gemma3:4b`，运行配置、安装检查与诊断读取同一值。API 图谱与源码图谱隔离存储，同路径的普通检索和统一检索复用实例。

默认返回向量证据预览；需要选中文档全文时传 `include_full_content=True`。文档 ID、来源和 Unity 版本仅返回数据中已知的值。图谱上下文按 token 预算生成，不进行任意字符截断。`merged_answer` 来自同一份结果，不触发二次检索或生成。

游戏源码 RAG 使用 `Server/data/game-rag-knowledge-base/config/config_game.yaml`，构建后生成 `data/chromadb` 和 `data/game_code_graph.json`；配置中的相对路径均相对于该目录。`knowledge_unified_search(sources=["game_code_graph"])` 使用这套当前项目源码 RAG。`knowledge_graph_search_game_code` 也使用当前项目的 `game-rag-knowledge-base`。`base_kb/lightrag_db_game_code` 是另一个可选扩展目录，不属于当前项目源码 RAG 的默认路径。构建它使用 `Server/scripts/build_game_code_lightrag.py`；查询它使用 `knowledge_graph_search_external_game_code` 或 `knowledge_unified_search(sources=["external_game_graph"])`。

图谱按需启用，使用 `source_breakdown` 逐来源检查状态。资产检索测试不能代替 GraphRAG 评测。固定对照集及测量方法见 [验证记录](core-pipeline-validation.md)。

当前项目的 `knowledge_graph_search_game_code` 使用 `mode` 映射源码检索参数：`local` 为 `top_k=5, traverse_depth=1`，`hybrid` 为 `top_k=5, traverse_depth=2`，`global` 为 `top_k=8, traverse_depth=3`，`naive` 为 `top_k=5, traverse_depth=1`。返回值会包含 `mode_applied_as`，便于确认实际参数。
