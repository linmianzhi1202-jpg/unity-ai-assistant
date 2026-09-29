# 工具实现与返回结果验证

日期：2026-09-27。沿用 FastMCP → ToolRouter / 本地服务 → UnityBridge → ToolDispatcher，不增加代理框架或第二套工具实现。

## 本轮修复

| 能力 | 原来的实际问题 | 现在的行为 |
| --- | --- | --- |
| 相机、贴图、Shader、VFX | properties JSON 没展开，Unity 收不到字段；无效参数也可能成功 | 参数展开后交给现有处理器；真实写入，有效字段缺失、对象不存在或未知动作返回错误 |
| Animator | 只实现参数增删，其他声明的动作没有执行 | 实现参数、层、状态、转换共八种增删；Blend Tree 接收并保存 motions；动画片段采用实际生成路径及循环设置 |
| 脚本读取 | MCP 声明 read，Unity 无对应分支 | 返回实际文件内容，创建脚本时建立目录 |
| 脚本执行 | 主线程等自身回调；正则执行部分语句；异常可能包装成成功 | 完整代码走 Unity 编译，等待后执行菜单，以跨域重载保存的执行结果判定成功；缺少执行 ID、编译/运行失败均返回错误；最后清理临时源码 |
| 批量执行 | 子命令失败计为成功；绕过 MCP 参数转换 | 调用已注册工具自身，保留参数转换与过滤；分别记录执行数、成功数、失败数，可在首个错误后停止；C# 原始批次也正确传播错误 |
| AI 图片、音效、3D | 适配器未注册、占位输出文件路径 | 注册真实服务适配器；请求、轮询、下载与文件检查；缺密钥、HTTP 错误、超时、取消均不报告完成 |
| 项目文件 | 相对路径指向服务器目录；PDF/DOCX 未实现 | 相对 Unity 项目解析路径，读取文本并提取 PDF/DOCX 内容；PDF 不含 OCR |
| 跨 MCP 调用 | 无配置连接入口，远端失败可能包装为成功 | 读取指定的 MCP 配置建立连接；检查协议错误、结构化结果和 JSON 文本中的业务错误 |

VFX 操作范围是资产的序列化属性；不声称实现 VFX Graph 节点编辑。图片接口是文生图，不宣称支持缺少输入参数的图像编辑。脚本执行使用临时 Editor 源码，需要等待编译；源码清理引起的再次编译仍应通过编辑器状态确认。主线程上已开始的用户代码无法强制撤销。

## 外部服务配置

在启动 MCP 进程的环境中设置所需项；未使用的服务无需配置。

| 环境变量 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | OpenAI 图片生成，默认 `gpt-image-1` |
| `ELEVENLABS_API_KEY` | ElevenLabs 音效生成，WAV 或 MP3 |
| `MESHY_API_KEY` | Meshy 文生/图生 3D、贴图、绑定、动画应用及动画检索 |
| `UNITY_MCP_AI_GENERATION_TIMEOUT` | 生成总等待时间，默认 600 秒 |
| `UNITY_MCP_GENERATED_DIR` | 生成文件保存目录，默认 `Server/data/generated` |
| `UNITY_MCP_BRIDGE_CONFIG` | 含 `mcpServers` 字典的 JSON 配置文件路径，供 `invoke_mcp_tool` 连接目标服务 |

图片支持 1024x1024、1536x1024、1024x1536，比例 1:1、3:2、2:3 或 auto；格式 png/jpeg/webp。不支持的尺寸明确报错。

3D 输入可用 HTTPS URL 或本地路径；动画可用动作 ID 或唯一匹配名称，`model_path="rig:<任务 ID>"` 可复用已完成的绑定任务。生成结果给出磁盘文件及可获得的贴图路径，不自动导入用户场景。超时或取消仅停止本地等待，已提交的云端任务可能继续运行，不自动重提请求。

接口依据：[OpenAI Images](https://developers.openai.com/api/docs/guides/image-generation)、[ElevenLabs 音效](https://elevenlabs.io/docs/api-reference/text-to-sound-effects/convert)、[Meshy 图生 3D](https://docs.meshy.ai/en/api/image-to-3d)、[贴图](https://docs.meshy.ai/en/api/retexture)、[绑定](https://docs.meshy.ai/en/api/rigging)、[动画](https://docs.meshy.ai/en/api/animation)。

## 验证结果与边界

- 全部 Python 回归 **58 项通过**：原有资产库 31 项、核心链路 17 项、本轮工具实现 10 项。
- 通过真实 FastMCP 工具调用验证：参数转换、失败传播、批次停止、脚本结果等待、跨 MCP 结果序列化、项目相对路径及 PDF/DOCX 提取。
- 外部服务采用 HTTP 模拟响应验证实际请求、轮询、下载和落盘；测试缺密钥、HTTP 失败、损坏图片、缺文件、取消与超时。**没有使用真实付费账号生成素材，因此尚未验证服务账号权限、实际生成质量和云端耗时。**
- Unity 2022.3.62f2c1 隔离项目验证插件编译；相机 FOV、贴图导入设置、材质属性、序列化属性实际变化；Animator 八种操作及 Blend Tree 子动画；脚本读取、失败批次停止、多语句代码的实际场景修改、运行异常失败。
- VFX 用通用 ScriptableObject 验证序列化写入，未安装 VFX Graph 包，未对具体 `.vfx` 资产实测。
- 本轮测试覆盖列出的修复场景，不等于所有工具的每个参数组合、Unity 版本及渲染管线均经过实机验证。前一轮按计划移除的检查点、Input System、Profiler 等入口未恢复。

用例：[Python 回归](../Server/tests/test_tool_implementations.py)、[Unity 用例](../Server/tests/unity/ToolImplementationSmoke.cs)、[Unity 结果](../Server/tests/reports/tool_implementation_smoke.json)。

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s Server/tests -p test_*.py
```
