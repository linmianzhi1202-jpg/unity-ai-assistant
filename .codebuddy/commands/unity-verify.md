---
name: unity-verify
description: "Unity 增强层验证命令 — 检查 Rules 格式、Skills 可用性、Agent 测试协议、MCP 桥接状态"
version: 0.1.0
---

# /unity-verify — Unity 增强层完整性验证

执行以下检查，输出验证报告：

## 1. Rules 格式检查

检查所有 Unity 相关 Rules：
- [ ] `unity-csharp-patterns` — 无 `#` 残留，含 §7 版本迁移感知
- [ ] `unity-performance` — 无 `#` 残留，含 §6 废弃 API 替代清单
- [ ] `unity-project-structure` — 存在且格式正确
- [ ] `gameplay-code` — 含 C# 示例，无 GDScript 残留
- [ ] `engine-code` — 含 C# 示例 + Unity 适用路径
- [ ] `ui-code` — 含 C# 示例 + Unity 适用路径
- [ ] `network-code` — 含 C# 示例 + Unity 适用路径
- [ ] `ai-code` — 含 Unity C# 路径 + 示例
- [ ] `test-standards` — 含 NUnit C# 示例，无 GDScript 残留
- [ ] `narrative` — description 非空
- [ ] `data-files` — 含 Unity 适用路径
- [ ] `design-docs` — 含 Unity 适用路径
- [ ] `prototype-code` — 含 Unity 适用路径

## 2. Skills 可用性检查

检查 Unity 专用 Skills：
- [ ] `unity-editor-control` — 存在且含 4 个工作流编排
- [ ] `unity-debug` — 存在且含 3 个诊断工作流
- [ ] `unity-live-dev` — 存在且含 5 步闭环流程
- [ ] `unity-project-bootstrap` — 存在且含 4 种项目模板

## 3. Agent 测试协议检查

检查 5 个核心 Unity Agent 是否有测试协议：
- [ ] `gameplay-programmer` — 含域内/域外/边界/ADR/上下文 5 类测试用例
- [ ] `engine-programmer` — 含 5 类测试用例
- [ ] `unity-specialist` — 含 5 类测试用例
- [ ] `ui-programmer` — 含 5 类测试用例
- [ ] `network-programmer` — 含 5 类测试用例

## 4. MCP 桥接状态检查

检查 MCP 工具引用：
- [ ] 5 个核心 Agent 均声明了 MCP 工具集成段落
- [ ] `knowledge_search` / `check_compile_errors` 至少在 3 个 Agent 中引用
- [ ] `unity-editor-control` Skill 列出了 MCP 工具速查表

## 5. settings.json 一致性检查

- [ ] `unity-project-structure` Rule 已在 settings.json 中注册
- [ ] 4 个新 Skills 已在 settings.json 中注册
- [ ] version 字段为 "2.2.0"

## 输出格式

```
Unity 增强层验证报告 v1.4.0
===========================
Rules:     ✅ X/Y | ❌ Z 个问题
Skills:    ✅ X/Y | ❌ Z 个缺失
Agents:    ✅ X/Y | ❌ Z 个缺少测试协议
MCP 桥接:  ✅ X/Y | ❌ Z 个未集成
Settings:  ✅/❌  | 版本号: X.X.X

总体评分:   X.X/10
```
