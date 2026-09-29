# 知识库与检索

知识库按实际数据目录和 manifest 管理。`knowledge_modules` 列出模块信息，`knowledge_index(action="status")` 返回向量集合文档数；目录和清单状态不等于检索质量已验收。

| 数据 | 目录 | 入口 |
| --- | --- | --- |
| Unity API 向量 | `Server/data/base_kb/chroma_db_v3` | `knowledge_search`、默认 `knowledge_unified_search` |
| Unity API 图谱 | `Server/data/base_kb/lightrag_db_v3_structured` | `sources=["api_graph"]` |
| 源码图谱 | `Server/data/base_kb/lightrag_db_game_code` | `sources=["game_code_graph"]` |
| 游戏源码检索与适配 | `Server/data/game-rag-knowledge-base` | [源码工作流](game-code-rag-workflow.md) |
| 资产库 | `Server/data/asset_library` | [资产库工作流](asset-graphrag-workflow.md) |
| 扩展模块清单 | `Server/data/ext_kb` | `knowledge_modules`；发现目录不表示自动加入检索源 |

向量沿用 `BAAI/bge-m3`，不重建既有索引。图谱默认 `gemma3:4b`，运行配置、安装检查与诊断读取同一值。API 图谱与源码图谱隔离存储，同路径的普通检索和统一检索复用实例。

默认返回向量证据预览；需要选中文档全文时传 `include_full_content=True`。文档 ID、来源和 Unity 版本仅返回数据中已知的值。图谱上下文按 token 预算生成，不进行任意字符截断。`merged_answer` 来自同一份结果，不触发二次检索或生成。

图谱按需启用，使用 `source_breakdown` 逐来源检查状态。资产检索测试不能代替 GraphRAG 评测。固定对照集及测量方法见 [验证记录](core-pipeline-validation.md)。
