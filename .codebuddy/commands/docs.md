---
name: docs
type: prompt
description: >
  自动生成项目文档。调用 S4 documentation-generator 技能，
  支持 API 文档、CHANGELOG、README 更新和 ADR（架构决策记录）四种模式。
allowed_tools:
  - use_skill              # 调用 documentation-generator 技能
  - read_file              # 读取源码提取文档信息
  - search_content         # 搜索 JSDoc/docstring/type annotation
  - search_file            # 发现需要文档化的模块
  - list_dir               # 浏览项目结构
  - execute_command        # 仅限 git log（用于 CHANGELOG 生成）
  - web_search             # 查询 API 文档规范
progress_message: "正在生成文档..."
version: 0.2.0
references:
  - .codebuddy/skills/documentation-generator/SKILL.md
---

# 文档生成 — /docs

你是一个**文档生成协调员**。请调用 `documentation-generator` (S4) 技能为项目生成指定类型的文档。

## 输入参数

- `{args}`: 文档类型（默认="api"，可选 "changelog" / "readme" / "adr" / "all"）

### 模式映射

| 参数 | 生成内容 | 输出位置 |
|------|----------|----------|
| 无 / `api` | API 参考文档（从 JSDoc/docstring/注解提取） | stdout（用户自行保存） |
| `changelog` | 基于 git log 的结构化 CHANGELOG | stdout |
| `readme` | 项目 README 生成/更新建议 | stdout |
| `adr` | 架构决策记录模板 | stdout |
| `all` | 以上全部四种文档 | 分段输出 |

## 生成流程

### Step 1: 分析项目上下文

1. 识别项目语言和技术栈
2. 检查现有文档状态（README 是否存在？API 文档是否过时？）
3. 收集元信息：版本号、许可证、依赖列表、模块结构

### Step 2: 委派 S4 documentation-generator

根据参数选择对应的文档模式：

#### API 文档模式 (`api`)
```
目标: 从源码中提取公共 API 定义
输入: 项目源码目录
输出: 结构化 API 参考（按模块分组）
包含: 函数签名、参数说明、返回值、示例用法、异常情况
```

#### CHANGELOG 模式 (`changelog`)
```
目标: 从 git log 提取变更历史
输入: 最近 N 条 commit（默认 50 条，可指定 range）
输出: 遵循 Keep a Changelog 格式的 CHANGELOG
分类: Added / Changed / Deprecated / Removed / Fixed / Security
```

#### README 模式 (`readme`)
```
目标: 生成或更新项目 README
输入: 项目结构 + package.json/pyproject.toml/Cargo.toml + 已有 README
输出: 完整的 README（含安装、使用、API、贡献指南）
注意: 不覆盖已有 README，而是给出 diff 建议
```

#### ADR 模式 (`adr`)
```
目标: 为最近的架构变更生成 ADR 记录
输入: 最近的重大 commit + 代码变更分析
输出: ADR-NN: {title} 格式的架构决策记录
包含: 背景、决策、后果、替代方案
```

## 输出格式

```markdown
# 📚 Documentation Output — {mode}

## 生成时间: {timestamp}
## 项目: {project_name}
## 技术栈: {tech_stack}

--- 

{生成的文档内容}

---

> 💡 以上内容由 S4 documentation-generator 自动生成。
> 请 review 后保存到合适的位置。
```

## 快捷别名

- `/docs` 或 `/docs api` — API 参考文档
- `/docs changelog` — CHANGELOG 生成
- `/docs readme` — README 建议
- `/docs adr` — 架构决策记录
- `/docs all` — 全量生成

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| **v0.2.0** | 2026-04-27 | 升级版本号，修复 YAML 格式（去掉引号），清理 references 格式 |
| v0.1.0 | 2026-04-07 | 初始版本 |
