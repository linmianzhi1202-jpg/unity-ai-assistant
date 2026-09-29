# 核心链路优化验证记录

日期：2026-09-26。保留 Codex / CodeBuddy → FastMCP → 检索或 UnityBridge → Unity 插件结构。本轮以原位替换和删除失效路径为主，未重建知识索引，未提交 Git commit。

## 已实现

- 单一运行配置入口，命令行不被生命周期覆盖；图谱模型、安装检查和诊断一致。stdio 普通输出走 stderr。未接通安全开关显式报错。
- 分组从 MCP 标签生成，在提供服务前同时过滤列表与调用；未知分组报错。固定 Unity 路由使用现有注册表。
- 删除检查点、Input System、包管理修改、Profiler、Coplay、ProBuilder 和无处理器的测试运行入口。Unity 包解析、资产库、源码适配保留。AI 生成保留 Python 服务，删除不会生成资产的 Unity 占位映射和处理器。
- 按规范化路径复用检索存储；图谱的磁盘和内存命名空间均隔离。复用后台查询循环，超时和取消清理查询及已启动的模型协程。
- 默认向量，显式指定图谱；逐来源状态、部分失败保留、完整选中文档与可用来源元数据。图谱上下文使用 token 预算，合并结果不重复检索。
- Unity 单例连接与命令锁保持一致；修改响应丢失不重发，只读操作可重试。实例心跳与项目核验避免重连串项目。主线程执行 Unity API，刷新和验证反映实际状态。

## 回归验证

原有 **31 项资产库测试通过**；新增 **17 项核心链路测试通过**。测试代码位于 `Server/tests/test_core_pipeline.py`，接口基线保存在 `Server/tests/fixtures/tool_interfaces_before.json`。

覆盖：保留工具名称及参数、分组列表与调用拒绝、真实 MCP stdio 初始化与查询、普通输出隔离、离线刷新不报成功、默认向量、显式图谱、部分失败、空结果、模型缺失、图谱超时及外部取消、后台模型调用取消、真实 LightRAG 存储隔离、路径别名复用。

TCP 测试使用本地模拟服务：修改请求收到后丢弃响应，仅接收一次；只读请求允许重试；超时和取消关闭连接；多实例及项目不匹配在修改发送前失败。多项目验证为模拟测试，不宣称运行了两个真实 Unity 项目。

真实 Unity **2022.3.62f2c1** 在隔离项目 `.validation/unity-core` 编译并运行冒烟用例，验证插件健康、编辑器状态、属性发现、参数默认值、重复注册拒绝、创建对象、修改 Rigidbody.mass、刷新、编译错误读取和脚本验证。结果见 [Unity 验证结果](../Server/tests/reports/unity_core_smoke.json)，可复用用例见 `Server/tests/unity/CorePipelineSmoke.cs`。未改动用户游戏场景。

## 固定 30 题检索对照

数据集：`Server/tests/fixtures/retrieval_cases.json`，包含精确 API、中文意图、API 类与方法关系各 10 题。本次对比 Unity API 图谱；不代表游戏源码图谱或资产库的质量成绩。

模型 `gemma3:4b`，Embedding `BAAI/bge-m3`，两组相同查询，向量 top 3，图谱 local，总预算 60 秒；上下文预算 6000 token，实体与关系各 1500，未启用 rerank。报告保存数据集及索引 SHA-256。保留已有 Ollama 模型状态和 LightRAG 关键词缓存，不清理或重建用户数据。

| 指标 | 仅向量 | 向量 + API 图谱 |
| --- | ---: | ---: |
| 正常返回 | 30/30 | 30/30 |
| 预期关键词全部出现 | 46.7% | 83.3% |
| 成功查询耗时中位数 | 0.65 秒 | 3.97 秒 |
| P95 耗时 | 0.86 秒 | 5.20 秒 |
| 向量文档 ID 可核对率 | 100% | 100% |
| 图谱引用路径可核对率 | 不适用 | 100% |

Embedding 冷启动单独记录为 **36.67 秒**。首轮评测出现 2 次图谱冷启动超时，原始结果保留在 `knowledge_benchmark_initial.json`；最终对照使用已存在的模型状态与缓存，不能用最终耗时替代完全冷启动耗时。

关键词命中是自动证据覆盖指标，**不是答案正确率**。ID 与引用路径在现有索引中可核对，也不代表外部文档真实性或完整性已逐项人工验证。返回证据和每题状态完整保存在 [逐题报告](../Server/tests/reports/knowledge_benchmark.json)，语义正确性人工评审尚未完成。图谱继续按需启用。

复现：

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s Server/tests -p test_*.py
.venv/Scripts/python.exe -X utf8 Server/scripts/benchmark_knowledge.py --timeout 60
```

验证环境：Python 3.13.5、FastMCP 3.4.2、LightRAG 1.5.0、ChromaDB 1.5.9、sentence-transformers 5.5.1。不同硬件、版本、缓存和模型状态的耗时不能直接对比。

## 保留的限制

本地模型加载与已进入本地计算的线程无法强行终止；超时会停止等待并取消可取消的协程，初始化任务被复用以避免重复加载。断线时已开始执行的 Unity 修改无法撤销，必须先检查实际状态。刷新提交后需要继续检查编译状态。本轮不实现已移除的功能。

## 后续工具实现补齐（2026-09-27）

前一轮保留 Python AI 入口并不代表适配器已经可用。本轮补齐真实提供商调用及注册，修复 Unity 参数、Animator、脚本执行、批次与跨 MCP 失败传播。全量回归现为 58 项通过，实测范围和外部服务限制见 [工具实现验证](tool-implementation-validation.md)。

## Unity Test Runner 接入（2026-09-27）

恢复并实现 `run_tests`，保留原参数，增加运行 ID 续查；原先“移除测试运行入口”的记录描述的是当时状态。新增 6 项测试，全部回归现为 64 项。真实 Unity EditMode/PlayMode、失败断言、空结果、超时与续查记录见 [Unity 自动化测试](unity-test-runner.md)。
