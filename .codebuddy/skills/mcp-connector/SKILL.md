---
name: mcp-connector
description: >
  MCP 工具链集成技能 — 连接外部 MCP (Model Context Protocol) 服务器，
  发现远程工具，管理连接生命周期，代理工具调用。
  为 CodeBuddy 增强层扩展外部工具生态系统。
version: 0.2.0
category: integration
triggers:
  - 用户请求连接 MCP 服务器
  - 执行 /mcp 命令
  - 需要使用远程 MCP 工具
  - 检测到 .mcp.json 配置文件变更
references:
  - source: ref/claw-code-main/rust/crates/runtime/src/mcp_client.rs
    extracted: MCP 客户端连接管理 + 工具发现 + 消息序列化
  - source: https://modelcontextprotocol.io/spec
    extracted: MCP 协议规范 (initialize/tools/list/tools/call)
  - source: .codebuddy/models.json
    extracted: fast-scan profile 路由配置
---

# S5: MCP Connector — MCP 工具链集成

## 用途

**定位**：CodeBuddy 增强层的**外部工具生态连接器**。

MCP (Model Context Protocol) 是一个开放协议，允许 LLM 应用连接到外部工具和服务。S5 负责：

- **连接管理**：建立和维护与 MCP 服务器的连接
- **工具发现**：发现并注册远程 MCP 工具
- **生命周期**：管理连接的创建、健康检查和关闭
- **调用代理**：代理 CodeBuddy 对 MCP 工具的调用

```
数据流:
  CodeBuddy 主 Agent
        ↓
  S5 mcp-connector
        ↓
  MCP Server (external)
        ↓
  Remote Tools (filesystem, database, API, etc.)
```

## 触发条件

| 触发方式 | 场景 |
|----------|------|
| **用户显式请求** | "连接 MCP 服务器"、"查看 MCP 工具" |
| **命令触发** | `/mcp` 命令 |
| **配置检测** | `.mcp.json` 配置文件存在时自动初始化 |
| **工具调用** | 需要使用已注册的 MCP 工具时 |

## 核心能力

### 能力 1：MCP 服务器连接管理

**连接生命周期**：

```yaml
connection_lifecycle:
  1. discovery:
     - 扫描 .mcp.json 配置文件
     - 解析服务器配置（name, command, args, env）
  
  2. initialization:
     - 启动 MCP 服务器进程
     - 发送 initialize 请求
     - 协议握手确认
  
  3. registration:
     - 调用 tools/list 获取工具列表
     - 注册工具到本地工具表
     - 建立工具名→服务器映射
  
  4. health_check:
     - 定期 ping 检查连接活性
     - 自动重连断开的连接
  
  5. shutdown:
     - 发送 shutdown 请求
     - 清理资源
```

**配置文件格式** (`.mcp.json`):

```json
{
  "servers": {
    "filesystem": {
      "command": "mcp-filesystem-server",
      "args": ["--root", "/workspace"],
      "env": {}
    },
    "database": {
      "command": "mcp-postgres-server",
      "args": ["--connection-string", "${DB_URL}"],
      "env": {
        "DB_URL": "postgresql://..."
      }
    }
  }
}
```

### 能力 2：远程工具发现

**工具发现流程**：

```yaml
tool_discovery:
  step_1_list:
    - 发送 tools/list 请求到 MCP 服务器
    - 解析响应中的 tools 数组
  
  step_2_register:
    - 提取工具名、描述、参数 schema
    - 注册到 CodeBuddy 工具表
    - 记录工具来源服务器
  
  step_3_validate:
    - 验证参数 schema 合规性
    - 检查工具名冲突
    - 记录注册状态
```

**工具信息格式**：

```yaml
tool_info:
  name: "filesystem_read_file"
  description: "读取指定路径的文件内容"
  source_server: "filesystem"
  input_schema:
    type: object
    properties:
      path:
        type: string
        description: "文件路径"
    required: [path]
```

### 能力 3：工具调用代理

**调用流程**：

```yaml
invocation_flow:
  1. route:
     - 从工具名获取目标服务器
     - 检查服务器连接状态
  
  2. serialize:
     - 将工具参数序列化为 JSON
     - 构造 tools/call 请求
  
  3. dispatch:
     - 发送请求到 MCP 服务器
     - 等待响应（支持超时）
  
  4. deserialize:
     - 解析响应内容
     - 转换为 CodeBuddy 可用格式
  
  5. error_handle:
     - 处理连接错误
     - 处理工具执行错误
     - 提供用户友好的错误信息
```

### 能力 4：连接健康监控

**健康检查策略**：

```yaml
health_check:
  interval: 60s                    # 检查间隔
  timeout: 5s                      # 单次检查超时
  
  actions:
    - 检查进程是否存活
    - 发送 ping 请求（如果支持）
    - 记录响应时间
  
  on_failure:
    - 标记连接为 degraded
    - 尝试自动重连（最多 3 次）
    - 记录错误日志
    - 通知用户（可选）
```

## 输出规范

### 连接状态报告

```markdown
## 🔌 MCP Connection Status

| Server | Status | Tools | Last Check |
|--------|--------|-------|------------|
| filesystem | ✅ Connected | 5 | 2s ago |
| database | ⚠️ Degraded | 0 | 5s ago |
| api-server | ❌ Disconnected | 0 | - |

### Registered Tools: 5
- filesystem_read_file (filesystem)
- filesystem_write_file (filesystem)
- filesystem_list_dir (filesystem)
- database_query (database) — ⚠️ Server degraded
- api_request (api-server) — ❌ Server offline
```

### 工具发现报告

```markdown
## 📡 MCP Tools Discovered from `filesystem`

| Tool | Description | Parameters |
|------|-------------|------------|
| read_file | 读取文件内容 | path (string) |
| write_file | 写入文件内容 | path, content |
| list_dir | 列出目录内容 | path |

**Registration Status**: 3/3 tools registered successfully
```

### 错误报告

```markdown
## ❌ MCP Connection Error

**Server**: database
**Error**: Connection refused (localhost:5432)

**Possible Causes**:
1. Database server not running
2. Incorrect connection string
3. Network firewall blocking

**Suggested Actions**:
1. Check if database service is running
2. Verify connection string in .mcp.json
3. Test connection manually
```

## /mcp 命令接口

当用户执行 `/mcp` 命令时：

```yaml
/mcp:                    # 显示所有服务器状态
/mcp list:               # 列出已注册工具
/mcp connect <server>:   # 连接指定服务器
/mcp disconnect <server>: # 断开指定服务器
/mcp refresh:            # 刷新工具列表
/mcp logs:               # 显示连接日志
```

## 与其他模块关系

```
S5 mcp-connector
  ├── 配置源: .mcp.json (项目根目录)
  ├── 路由配置: models.json (fast-scan profile)
  ├── 工具注册: CodeBuddy 工具表
  └── 日志输出: H5 performance-monitor (调用统计)
```

## 模型路由

```yaml
# models.json 中的配置
skill_routing:
  mcp-connector:
    profile: fast-scan
    reason: MCP 连接以协议握手和工具发现为主，速度优先
```

**路由特征**：
- 快速连接建立
- 模式匹配为主
- 低延迟响应

## 实现注意事项

### 安全考虑

```yaml
security:
  - 仅信任项目目录下的 .mcp.json
  - 验证工具名无路径遍历
  - 限制可执行的命令范围
  - 环境变量不暴露敏感信息
```

### 错误处理

```yaml
error_handling:
  connection_timeout:
    action: "重试或降级"
    message: "连接超时，请检查服务器状态"
  
  tool_not_found:
    action: "返回错误"
    message: "工具 {name} 未注册"
  
  server_crash:
    action: "自动重启"
    message: "服务器崩溃，正在尝试重启..."
```

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|----------|
| **v0.2.0** | 2026-04-27 | 升级版本号，修复 YAML 格式（去掉引号），完善工具调用流程 |
| v0.1.0 | 2026-04-07 | Phase 11 初始实现（连接管理 + 工具发现 + 调用代理 + 健康监控）|

## 后续规划

- [ ] SSE (Server-Sent Events) 传输支持
- [ ] WebSocket 传输支持
- [ ] 工具缓存与预加载
- [ ] 多服务器负载均衡
- [ ] 工具调用链追踪
- [ ] 自定义 MCP 服务器开发模板
