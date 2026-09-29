# 故障排查

| 现象 | 含义与处理 |
| --- | --- |
| 客户端无法初始化 MCP | 检查程序、启动器绝对路径和依赖。普通日志在 stderr，stdout 只应出现协议消息。 |
| 工具不在列表 | 检查 `UNITY_MCP_ENABLED_GROUPS`。已删除的空入口不会重新出现，Unity 离线本身不会隐藏工具。 |
| 未知分组启动失败 | 使用已注册 `group:*` 标签的名称，或设为 `all`。 |
| 安全开关报不支持 | ACL、加密、审计未接通，不能将配置开启视为能力已实现。 |
| 无可用 Unity 实例 | 确认插件已编译、Unity 仍运行。检查用户目录 `.unity-mcp` 内该实例的心跳。 |
| 返回多个项目候选 | 设置 `UNITY_MCP_PROJECT_PATH`，或明确调用项目选择工具。不会随机选择。 |
| 重连时项目不匹配 | 当前端口属于其他项目。检查目标项目实例，连接不会自动切换。 |
| 修改返回 execution_uncertain | 命令可能已执行但响应丢失。先读取场景实际状态，再决定后续操作，勿直接重复修改。 |
| 刷新返回 submitted / compiling | 等待并读取编辑器状态、编译错误。断线不能推断成功。 |
| 检索 empty | 来源可用但没有命中；检查索引和查询，不能与模型错误混为一谈。 |
| 检索 unavailable | 图谱、依赖、服务或模型不可用；查看对应来源消息。 |
| 检索 timeout | 包含排队和模型冷启动的预算耗尽；其余请求仍可响应。检查本机模型加载与 Ollama 性能。 |
| 统一检索 partial | 某来源失败，返回的其他来源仍可使用。 |
| 统一检索 error | 所有来源失败，或参数无效，不是成功检索。 |

通过 `knowledge_modules` 查看目录和模型配置，通过 `knowledge_index(action="status")` 查看实际向量文档数。目录存在不代表模型能推理。图谱查询显式启用，默认向量策略不会因为图谱状态变化而自动改变。

安装依赖使用与 MCP 配置相同的 Python：`.venv/Scripts/python.exe -m pip install -r requirements.txt`。图谱检查 `ollama list` 和 `UNITY_MCP_RAG_MODEL`，默认 `gemma3:4b`。不要更换 Embedding 后继续混用原有向量索引。
