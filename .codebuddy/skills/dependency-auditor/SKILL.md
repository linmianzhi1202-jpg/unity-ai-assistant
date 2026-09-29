---
name: dependency-auditor
description: 依赖审计技能 — 当用户需要审计项目依赖安全性、检查漏洞包、验证版本一致性、检查许可证合规性时使用。提供结构化的依赖审计工作流，包含漏洞检测、版本分析和许可证合规检查。
version: 0.3.0
category: auditing
whenToUse: >
  当用户需要审计项目依赖安全性时使用。
  检查 package.json / requirements.txt / Cargo.toml 是否存在已知漏洞。
  验证依赖版本是否符合最佳实践（锁定版本、无通配符）。
  检查开源许可证合规性（GPL/AGPL/MIT/Apache 等）。
  发现废弃或维护不善的依赖包。
input:
  - 目标项目路径（默认当前工作区）
  - 审计类型：security（安全）/ version（版本）/ license（许可证）/ full（全面）
output: >
  结构化的 Dependency Audit Report，包含依赖清单、
  漏洞检测结果、版本风险分析、许可证矩阵和修复建议
references:
  - source: ref/claw-code-main/rust/crates/runtime/src/policy_engine.rs
    extracted: PolicyEngine 条件+动作规则引擎（可执行策略模式应用于依赖审计）
  - source: .codebuddy/rules/engineering-baseline/RULE.mdc
    extracted: C5 依赖管理检查清单（锁定版本、dev/prod 分离、无 * 通配符）
  - source: .codebuddy/skills/commit-auditor/SKILL.md
    extracted: Step 4 安全扫描正则模式（敏感信息检测可复用至依赖内容扫描）
context: inline
---

# S3: Dependency Auditor — 依赖安全与版本审计技能

## 用途

对项目依赖进行系统化审计，确保依赖的安全性、版本一致性和许可证合规性。

**核心能力**：
1. **依赖收集** — 解析 package.json / requirements.txt / Cargo.toml 等锁文件
2. **漏洞检测** — 对照已知 CVE 数据库检查高风险依赖
3. **版本审计** — 版本范围合理性、过期依赖、废弃包检测
4. **许可证合规** — 开源许可证兼容性分析与违规预警

---

## 审计工作流

### Step 1: 识别依赖管理器

根据项目中的配置文件确定依赖类型：

| 文件 | 语言 | 依赖管理器 | 锁文件 |
|------|------|------------|--------|
| `package.json` + `package-lock.json` | JS/TS | npm/pnpm/yarn | package-lock / yarn.lock / pnpm-lock |
| `requirements.txt` + `pip.lock` | Python | pip/pipenv/poetry | pipfile.lock / poetry.lock |
| `Cargo.toml` + `Cargo.lock` | Rust | cargo | Cargo.lock |
| `go.mod` + `go.sum` | Go | go modules | go.sum |
| `pom.xml` | Java | Maven | — |
| `build.gradle` | Java/Kotlin | Gradle | — |

```yaml
输入: 项目路径（默认当前工作区）

执行:
  execute_command: ls package.json requirements.txt Cargo.toml go.mod pom.xml build.gradle 2>/dev/null
  # 识别存在的依赖配置文件
```

**多语言项目**: 对每种检测到的依赖管理器分别执行后续步骤。

### Step 2: 依赖收集与分析

#### D2-1: 依赖清单提取

收集完整的依赖树信息：

```bash
# npm
npm list --depth=0          # 直接依赖
npm ls --json               # 完整依赖树（JSON 格式）

# Python
pip list --format=json       # 已安装依赖
pipdeptree                  # 依赖树可视化

# Cargo
cargo tree --depth 1        # 直接依赖
cargo audit                 # 安全审计（如果已安装）

# Go
go list -m all              # 所有模块
```

#### D2-2: 版本健康度评估

对每个直接依赖进行版本分析：

| 检查项 | 判定标准 | 风险等级 |
|--------|----------|----------|
| 版本锁定 | 存在 lock 文件且已提交 | 🟢 低风险 |
| 版本范围 | 使用精确版本或 `~` 范围 | 🟡 中风险 |
| 最新版本 | 与最新版差距 ≤ 10 个 minor | 🟡 中风险 |
| 维护状态 | 近 6 个月有 commit/release | 🟢 低风险 |
| 下载量 | npm weekly > 1000 / PyPI 月均 > 10000 | 🔵 低风险 |

**版本范围最佳实践**：

```json
// ✅ 推荐: 精确或小范围
"react": "^18.2.0",        // 允许 patch 更新
"lodash": "~4.17.21",      // 仅允许 patch
"typescript": "5.3.3"      // 完全锁定（编译器）

// ❌ 避免: 过宽范围
"express": "*",            // 完全不可控
"axios": "^0.0.0",         // 等于 *
"webpack": ">4.0.0",       // 可能包含 breaking change
```

### Step 3: 安全漏洞扫描

#### D3-1: 已知漏洞检测

使用各语言生态的安全扫描工具：

```bash
# npm (npm audit)
npm audit --audit-level=moderate           # 输出 moderate 及以上漏洞
npm audit --json                           # 结构化输出

# Python (safety / pip-audit)
pip install safety && safety check         # Safety DB 漏洞检查
pip-audit                                  # PyPA 官方审计工具

# Cargo
cargo audit                                # RustSec 数据库
# 需要先安装: cargo install cargo-audit

# Go
govulncheck ./...                          # Go 官方漏洞扫描
```

#### D3-2: 漏洞严重分级

| 严重程度 | CVSS 范围 | 处理策略 |
|----------|-----------|----------|
| **Critical** | 9.0–10.0 | 🔴 立即修复，阻塞合并 |
| **High** | 7.0–8.9 | 🔴 48 小时内修复 |
| **Moderate** | 4.0–6.9 | 🟡 下一个 sprint 修复 |
| **Low** | 0.1–3.9 | 🔵 记录在案，排期更新 |

#### D3-3: 依赖投毒检测

检查以下供应链攻击特征：

| 特征 | 检测方法 |
|------|----------|
| Typosquatting（仿冒包名） | 包名与流行包仅 1-2 字符差异 |
| 依赖混淆 | 包含大量无用文件或异常大的 node_modules |
| 脚本注入 | install/postinstall 脚本包含可疑命令（curl \| bash, eval） |
| 维护者变更 | 最近 transfer ownership 或新增 maintainer |

### Step 4: 许可证合规检查

#### D4-1: 许可证分类

| 类别 | 许可证 | 商业使用 | 修改闭源 | 风险评估 |
|------|--------|---------|----------|----------|
| **宽松 (Permissive)** | MIT, Apache-2.0, BSD, ISC | ✅ | ✅ | 🟢 低 |
| **弱 copyleft** | LGPL-2.1, LGPL-3.0, MPL-2.0 | ✅ | ⚠️ 有条件 | 🟡 中 |
| **强 copyleft** | GPL-2.0, GPL-3.0, AGPL-3.0 | ✅ | ❌ | 🔴 高 |
| **Proprietary** | 自定义商业许可 | ❓ 查看 | ❓ 查看 | 🔴 需审查 |
| **无许可** | 未声明 | ❌ 高风险 | ❌ 高风险 | 🔴 危险 |

#### D4-2: 合规冲突检测

| 场景 | 冲突条件 |
|------|----------|
| MIT 项目引入 GPL 依赖 | GPL 的传染性可能影响整个项目 |
| 商业产品使用 AGPL | AGPL 要求 SaaS 场景公开源码 |
| Apache-2.0 与 GPL-v2 | 不兼容（Apache 专利条款 vs GPLv2 专利终止） |
| 多许可证组合 | 需要满足所有许可证的最严格条款 |

```bash
# 许可证检查命令

# npm
npx license-checker --summary --onlyAllow 'MIT;Apache-2.0;BSD;ISC'

# Python
pip-licenses --format=json --with-system

# Cargo
cargo about generate licenses.html   # 需要 cargo-about 插件
```

### Step 5: 输出报告

生成结构化 Dependency Audit Report：

```markdown
## Dependency Audit Report

**审计时间**: {timestamp}
**项目路径**: {project_path}
**依赖管理器**: {managers_detected}
**审计类型**: {audit_type}

### 总体评分: {A/B/C/D/F}

| 维度 | 得分 | 状态 |
|------|------|------|
| 版本健康 | X/10 | ✅/⚠️/❌ |
| 安全漏洞 | X/10 | ✅/⚠️/❌ |
| 许可证合规 | X/10 | ✅/⚠️/❌ |
| 维护状态 | X/10 | ✅/⚠️/❌ |

---

### 1. 依赖概览

| 指标 | 数值 |
|------|------|
| 直接依赖 | {N} |
| 传递依赖 | {N} |
| 总依赖节点 | {N} |
| 锁定版本 | ✅/❌ |

### 2. 漏洞详情

| 严重程度 | CVE ID | 影响包 | 当前版本 | 修复版本 | 状态 |
|----------|--------|--------|----------|----------|------|
| 🔴 Critical | CVE-2024-xxxx | {pkg} | {ver} | {ver} | 待修复 |
| 🟡 Moderate | CVE-2024-xxxx | {pkg} | {ver} | {ver} | 可接受 |

### 3. 版本风险

| 包名 | 当前版本 | 最新版本 | 落后版本 | 风险 |
|------|----------|----------|----------|------|
| {pkg} | 1.0.0 | 3.5.0 | 2 major | 过期严重 |

### 4. 许可证矩阵

| 许可证 | 包数量 | 代表包 | 风险 |
|--------|--------|--------|------|
| MIT | {N} | ... | 🟢 |
| Apache-2.0 | {N} | ... | 🟢 |
| GPL-3.0 | {N} | ... | 🔴 |

### 5. 建议行动

**立即处理**:
1. {action_critical}

**短期计划** (1-2 周):
1. {action_short_term}

**长期优化** (1 个月):
1. {action_long_term}

---

### 附录: 扫描命令记录

```
$ npm audit --json
{raw_output}

$ npx license-checker --summary
{raw_output}
```
```

## 评分标准

### 版本健康分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| 缺少 lock 文件 | -4 |
| 使用 `*` 通配符（每个实例） | -2 |
| 依赖平均落后超过 1 年 | -3 |
| 检测到废弃包（每个实例） | -1 |
| devDependencies 与生产依赖混用 | -2 |

### 安全漏洞分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| Critical 漏洞（每个实例） | -10（直接 F） |
| High 漏洞（每个实例） | -5 |
| Moderate 漏洞（每个实例） | -2 |
| Low 漏洞（每个实例） | -0.5 |
| 无法执行安全扫描工具 | -3 |

### 许可证合规分（10 分制）

| 扣分项 | 分值 |
|--------|------|
| 强 copyleft (GPL/AGPL) 且目标为闭源产品 | -10 |
| 无许可证声明的包（每个实例） | -2 |
| 许可证冲突（每对冲突） | -3 |
| 自定义/非标准许可证（每个实例） | -1 |

### 总评等级映射

| 总分 | 等级 | 含义 | 建议 |
|------|------|------|------|
| 36-40 | A | 优秀 | 保持现状，定期巡检 |
| 29-35 | B | 良好 | 有少量待改进项 |
| 18-28 | C | 及格 | 需要计划性清理 |
| 9-17 | D | 不合格 | 需要专项整改 |
| 0 或高危安全 | F | 危险 | 立即暂停发布 |

## 与增强层其他模块的协作关系

```
CODEBUDDY.md
  ├── rules/engineering-baseline/RULE.mdc
  │     └── C5 依赖管理清单 ← 本 Skill 的版本审计基础
  ├── skills/commit-auditor/SKILL.md
  │     └── Step 4 安全扫描模式 ← 本 Skill D3 漏洞扫描的正则参考
  └── agents/security-scanner/agent.md
        └── 依赖层安全 ← 本 Skill 发现的问题可委托 A2 深度分析
```

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| **0.3.0** | 2026-04-27 | 修复 YAML 格式（description/whenToUse/input/output），清理标题多余#符号 |
| 0.2.0 | 2026-04-27 | 修复 YAML 字段格式（whenToUse 改为 multiline），更新版本 |
| 0.1.0 | 2026-04-06 | Phase 3 Direction A 初始实现 |
