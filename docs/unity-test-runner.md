# Unity 自动化测试

`run_tests` 通过现有 FastMCP → ToolRouter → UnityBridge → Unity Test Runner 执行真实测试，属于 `testing` 分组。保留原参数 `test_filter`、`test_mode`、`timeout`，增加可选 `run_id` 用于续查，不增加独立代理或 Python 任务平台。

## 使用

安装或更新 Unity 插件后等待编译完成。本插件声明 Test Framework 1.3.9 依赖，由 Unity Package Manager 解析。当前实测环境为 Unity 2022.3.62f2c1；其他 Unity 版本需单独验证。

运行前保存修改过的场景，退出 Play Mode，确认项目编译通过。项目本身需要有可发现的测试程序集；本工具执行已有测试，不自动生成测试代码。

```python
run_tests(test_mode="EditMode")
run_tests(test_mode="EditMode", test_filter="InventoryTests.AddItem")
run_tests(test_mode="PlayMode", test_filter="PlayerMovementTests", timeout=300)
# 如果前一次等待超时，使用返回的 ID 续查，不重新执行：
run_tests(run_id="前一次返回的32位run_id", timeout=60)
```

`test_filter` 是按命名边界匹配的字面名称，可指定类、方法、命名空间限定名称；不是任意正则表达式。未提供过滤器则执行所选模式下的所有测试。PlayMode 在编辑器内运行，不包含打包到设备执行。

## 返回和失败语义

- `success=true` 仅表示收到最终结果、至少一个测试通过，且没有失败或无结论测试；仍需查看 `skipped` 数量。
- `state=failed`：包含断言失败、执行错误、无结论或全部跳过；不会包装成成功。
- `state=no_tests`：当前模式/过滤器没有匹配到测试，不等同于通过。
- `state=error`：编译未通过、编辑器状态不允许、已有测试在运行、未知 ID 或测试框架错误。
- `state=timeout`：仅停止 MCP 端等待，Unity 测试可能仍在运行。取消 MCP 请求同样不能保证停止已执行的 Unity 测试。
- `state=interrupted`：编辑器会话结束，未记录到测试完成结果。

返回包含 `run_id`、通过/失败/跳过/无结论数量、耗时、逐测试名称、结果、失败消息和堆栈。完整 JSON 和 NUnit XML 保存在当前 Unity 项目的 `Library/UnityMCP/TestRuns`，返回中给出绝对路径。该目录属于 Unity 临时项目数据，删除 Library 会移除这些报告。

提交命令不自动重发；响应丢失后仅按同一个运行 ID 查询。PlayMode 域重载后重新注册回调并继续记录。每个编辑器只允许一个工具发起的测试运行；不要同时从 Test Runner 窗口启动另一批测试。主线程上死循环的用户测试仍需人工处理。

## 验证

新增 6 项 Python 回归覆盖结果传播、提交响应丢失、域重载断线、超时续查、请求取消、参数校验和工具组过滤。全部 Python 回归为 **64 项通过**。

真实 MCP 工具 → TCP → Unity 2022.3 验证了 9 次调用：EditMode 通过、失败、全部跳过、无匹配，PlayMode 通过、失败，慢测试等待超时、并发运行拒绝、同 ID 续查成功。用例故意包含失败断言，以验证失败不会误报成功；这些测试在隔离项目执行，未改动用户游戏场景。

- [实测结果](../Server/tests/reports/unity_test_runner.json)
- [验证脚本](../Server/scripts/verify_unity_test_runner.py)
- [测试夹具](../Server/tests/unity/TestRunner)
- [Python 回归](../Server/tests/test_unity_test_runner.py)

复现时将测试夹具目录复制到隔离项目的 `Assets/McpTestFixtures`，安装当前插件、打开 Unity 并确认编译通过，然后运行：

```powershell
.venv/Scripts/python.exe -X utf8 Server/scripts/verify_unity_test_runner.py --project <隔离项目路径>
.venv/Scripts/python.exe -X utf8 -m unittest discover -s Server/tests -p test_*.py
```

接口依据：[Unity Test Runner API](https://docs.unity.cn/Packages/com.unity.test-framework@1.1/api/UnityEditor.TestTools.TestRunner.Api.TestRunnerApi.html)、[测试回调及域重载](https://docs.unity.cn/Packages/com.unity.test-framework@1.1/manual/extension-get-test-results.html)；实现同时核对了 Unity 官方 1.3.9 包源码。该版本取消接口非公开且不覆盖 PlayMode，因此不将本地取消伪装成 Unity 已停止。
