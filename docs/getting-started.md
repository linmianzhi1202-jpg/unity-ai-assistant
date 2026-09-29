# 安装与客户端配置

需要 Python 3.10+ 和可安装本插件的 Unity Editor。本轮在 Unity 2022.3.62f2c1 验证。图谱额外需要 Ollama 与所选模型；纯向量检索和 Unity 操作不要求图谱模型就绪。

## 安装

运行产品目录的 `install.bat`。脚本先定位自身目录，再安装依赖和生成配置；已有配置请保留并检查。也可手动执行：

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

在 Unity Package Manager 使用 “Add package from disk”，选择 `UnityPlugin/package.json`，等待编译完成。插件默认从 TCP 6400 起尝试可用端口。

## MCP 客户端

在 Codex 或 CodeBuddy 的 MCP 服务设置中填入同一启动命令：

- 程序：产品目录下 `.venv/Scripts/python.exe` 的绝对路径。
- 参数：`server_launcher.py` 的绝对路径。
- 传输：stdio。
- 环境变量：参考下表。

CodeBuddy JSON 模板见 `mcp.json.template`，其中 `{{PRODUCT_ROOT}}` 替换为带结尾 `/` 的产品绝对路径。安装器生成本机配置；不要将别人的绝对路径原样复制。Codex 使用相同程序、参数和环境变量，在其 MCP 设置中添加即可。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `UNITY_MCP_TRANSPORT` | `stdio` |
| `UNITY_MCP_ENABLED_GROUPS` | `all`；仅检索可设 `rag`，多个组以逗号分隔 |
| `UNITY_MCP_PROJECT_PATH` | 未指定；多个 Unity 项目时应明确设置项目根目录 |
| `UNITY_MCP_RAG_MODEL` | `gemma3:4b` |
| `UNITY_MCP_RAG_TIMEOUT` | `60`，图谱排队、初始化和查询的总秒数 |
| `OLLAMA_HOST` | `http://localhost:11434` |
| `PYTHONIOENCODING` | 建议 `utf-8` |

图谱模型按配置单独准备，默认可执行 `ollama pull gemma3:4b`。若设置了 `UNITY_MCP_RAG_MODEL`，使用对应模型名。安装脚本只检查是否存在并报告缺项，不会把模型缺失显示为全部就绪。Embedding 固定 `BAAI/bge-m3`，使用已有缓存和索引。

## 验证和使用

连接客户端后读取 `mcpforunity://health`，确认服务；读取 `mcpforunity://editor/state`，确认 Unity 已连接且未编译，再操作场景。写入 C# 后调用 `refresh_unity` 并继续检查编辑器状态、编译错误。`submitted` 表示提交刷新，不表示已编译通过。

```python
knowledge_search(query="Rigidbody.AddForce", include_full_content=True)
knowledge_unified_search(query="中文描述的 Unity API 问题")
knowledge_unified_search(query="GameObject 和 Component 的关系", sources=["vector", "api_graph"])
knowledge_unified_search(query="项目中类和方法的调用关系", sources=["game_code_graph"])
```

默认检索只走向量。需要源码搜索和适配时参考 [源码工作流](game-code-rag-workflow.md)，资产操作参考 [资产库工作流](asset-graphrag-workflow.md)。

AI 素材生成需要对应服务密钥；具体环境变量、输出目录、支持参数和验证范围见 [工具实现与配置](tool-implementation-validation.md)。

项目测试可用 `run_tests(test_mode="EditMode")` 或 `run_tests(test_mode="PlayMode")`，运行前保存场景并等待编译成功。超时后可使用返回的 `run_id` 续查，见 [Unity 自动化测试](unity-test-runner.md)。
