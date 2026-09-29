---
name: state-flow-auditor
description: 状态流审计技能 — 系统化审计前端应用中的状态流向，检测不一致、循环依赖、冗余重渲染等问题
version: 0.2.0
category: auditing
whenToUse: >
  当用户需要审计前端应用的状态管理架构、排查状态更新但视图不响应的问题、
  检测组件间的循环依赖或冗余重渲染、评估重构前后的状态流影响面时，使用此技能。
input:
  - "项目根目录路径（默认当前工作区）"
  - "目标框架（react/vue/svelte/auto）"
  - "审计范围（full / module / component）"
output:
  - "结构化状态流审计报告（Markdown 格式）"
  - "问题清单按严重程度排序"
  - "修复建议与优先级"
tools:
  - search_content
  - read_file
  - search_file
  - code-explorer
context: inline
---

# State Flow Auditor

> **参考来源**:
> - `ref/claw-code-main` → **Lane Event Schema**：17 种结构化事件类型 + Worker Boot 状态机的显式生命周期建模思路
> - `ref/claude-code-main` → **BundledSkillDefinition** 接口：name/whenToUse/getPromptForCommand 结构化定义
> - 转化为 CodeBuddy Skill 原生格式

## 技能概述

State Flow Auditor 是一个 **只读审计技能**，用于系统化分析前端应用的状态管理架构。它不会修改任何代码，仅产出诊断报告。

## 适用场景

| 场景 | 审计模式 | 预计耗时 |
|------|----------|----------|
| 新项目接入评估 | full — 全量扫描所有状态相关文件 | 3-5 min |
| 特定模块排查 | module — 指定目录深度扫描 | 1-2 min |
| 单组件问题定位 | component — 单文件 + 直接依赖 | <1 min |
| 重构前后对比 | full × 2 + diff | 5-8 min |

## 审计方法论

### Phase 1: 发现（Discovery）

```
目标：建立完整的状态资产清单

步骤:
1. 扫描项目，识别状态管理方案
   ├── Redux (search: createStore / configureStore / useSelector)
   ├── Zustand (search: create / useStore)
   ├── Pinia (search: definePinia / defineStore)
   ├── Vuex (search: new Vuex.Store)
   ├── Context API (search: createContext / useContext)
   ├── useState 散落 (search: useState / useRef)
   └── 其他 (MobX / Recoil / Jotai 等)

2. 对每个状态单元记录:
   {
     name: string           // 状态名
     location: string       // 文件路径:行号
     type: 'global' | 'module' | 'local'
     framework: string      // React/Vue/Svelte
     consumers: string[]    // 消费此状态的组件列表
     mutators: string[]     // 可修改此状态的函数/action 列表
     dependencies: string[] // 依赖的其他状态
   }
```

### Phase 2: 建模（Modeling）

```
目标：构建状态依赖图（State Dependency Graph）

输出格式（Mermaid）:

graph TD
    A[AuthStore.user] --> B[HeaderAvatar]
    A --> C[ProfilePage]
    D[CartStore.items] --> E[CartBadge]
    D --> F[CartSummary]
    G[ThemeContext] --> H[ThemeProvider]
    G --> I[All Components]

标注规则:
    ──→ 正向数据流（读）
    - -→ 写入关系（dispatch/mutate）
    ==> 循环依赖（警告！红色高亮）
```

### Phase 3: 分析（Analysis）

对每个发现的问题，应用以下检测器：

#### A1: 孤儿状态（Orphan State）
```javascript
// 检测条件: 有定义但无消费者
// 严重度: 🟡 低（死代码，但不影响功能）
// 建议: 如果确实不需要，清理以减少认知负担
```

#### A2: 单点瓶颈（Single Point of Bottleneck）
```javascript
// 检测条件: 一个全局 store 被 >10 个组件直接消费
// 严重度: 🟠 中（任何变更导致大面积重渲染）
// 建议: 拆分 store 或使用 selector 细粒度订阅
```

#### A3: 状态镜像（State Mirroring）
```javascript
// 检测条件: 相同语义的数据在多个 store/localState 中重复存储
// 严重度: 🔴 高（同步困难，容易不一致）
// 合并为单一 Source of Truth
```

#### A4: 深层 prop drilling（Prop Drilling Depth > 3）
```javascript
// 检测条件: 数据通过 props 穿越超过 3 层未消费的中间组件
// 严重度: 🟠 中（耦合度高，变更成本大）
// 建议: 使用 Context / store / DI 在合适层级注入
```

#### A5: 副作用分散（Scattered Side Effects）
```javascript
// 检测条件: 同一个业务逻辑的副作用分布在多个 useEffect/watch 中
// 严重度: 🟠 中（难以追踪完整生命周期）
// 建议: 收聚为自定义 Hook / composable / observer
```

#### A6: 循环依赖（Circular State Dependency）
```javascript
// 检测条件: StateA 的更新触发依赖 StateB 的 effect，而 StateB 又反向影响 StateA
// 严重度: 🔴 高（无限重渲染 / 栈溢出风险）
// 必须: 打破闭环，引入中间层或提升状态到共同祖先
```

### Phase 4: 报告（Reporting）

## 输出模板

```markdown
# 状态流审计报告

**项目**: `<project-name>`
**框架**: `<detected-framework(s)>`
**审计时间**: `<timestamp>`
**审计范围**: `<full/module/component>`

## 一、状态资产概览

| 类别 | 数量 | 文件数 |
|------|------|--------|
| 全局 Store | N | M |
| Context | N | M |
| 本地 State（估计） | N* | M* |

> *本地 state 为估算值，基于 useState/useRef 出现次数

## 二、状态依赖图

<Mermaid graph>

## 三、发现问题（按严重程度排序）

### 🔴 P0 - 必须修复

| # | 问题类型 | 位置 | 说明 |
|---|----------|------|------|
| 1 | A6 循环依赖 | file:line | ... |

### 🟠 P1 - 建议修复

| # | 问题类型 | 位置 | 说明 |
|---|----------|------|------|
| 2 | A3 状态镜像 | file:line vs file:line | ... |

### 🟡 P2 - 可以优化

| # | 问题类型 | 位置 | 说明 |
|---|----------|------|------|
| 3 | A1 孤儿状态 | file:line | ... |

## 四、架构建议

<基于整体分析的架构改进方向>

## 五、下一步行动

- [ ] 优先修复 P0 问题
- [ ] 处理 P1 问题
- [ ] Phase 2 可选优化项
```

## 使用方式

### 通过 Agent 触发
当用户说「审计一下这个项目的状态管理」或「帮我看看状态流有没有问题时」，Agent 应自动加载此 Skill 并执行。

### 手动触发
```
/skill state-flow-auditor --scope=module --path=src/features/dashboard
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| scope | enum{full,module,component} | auto | 审计范围 |
| path | string | 工作区根 | 目标目录/文件 |
| framework | enum{react,vue,svelte,auto} | auto | 目标框架 |
| output-format | enum{markdown,json,mermaid} | markdown | 输出格式 |

## 限制与边界

- ✅ 支持 React / Vue / Svelte 主流方案
- ⚠️ Next.js / Nuxt SSR 场景需要额外关注服务端状态
- ❌ 不支持后端状态审计（数据库/缓存）
- ℹ️ 大型项目（>500 文件）full audit 可能需要较长时间

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 0.2.0 | 2026-04-27 | 修复 YAML 格式（whenToUse 改为 > 格式），更新版本号 |
| 0.1.0 | 2026-04-06 | 初始版本，MVP 第一阶段 |
