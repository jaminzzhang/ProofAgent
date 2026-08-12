# Production Agent Lifecycle Scope、准入与 TDD 计划

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `TDD_INPUT_READY` |
| 最高风险等级 | P1 |
| 一句话依据 | 唯一 Agent、PostgreSQL 权威、浏览器 manifest 禁令、OIDC/CSRF、publication Gate 和原始 404 均有直接证据；本切片不改变发布权威 |
| 下一步建议 | 从 production `POST /api/config/agents` 的公开行为开始 RED，再依次实现 application、persistence、delivery 和 Dashboard 闭环 |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 用户确认 | 当前对话 | 是 | 按推荐实现 PostgreSQL、server-owned template、权限/审计和 capability 修复 | 无 |
| 原始复现 | production `TestClient` 与 development 差分 | 是 | production POST 连续返回 `404 {"detail":"Not Found"}`；development 同请求返回 `200` | 尚未修复 |
| 项目规则 | `AGENTS-COMMON.md`、`docs/rules/hicode-coding-rules.md` | 是 | production 不得使用本地权威；行为变化必须 TDD | 无 |
| 产品与技术设计 | `docs/prd.md`、`docs/technical-design.md` | 是 | Dashboard 配置唯一 Agent；浏览器不得提供 manifest path | 无 |
| Agent 决策 | ADR-0124、S5 唯一 Agent 计划 | 是 | 唯一 ID、V3-only、server-owned production bootstrap | 无 |
| 领域上下文 | `CONTEXT-MAP.md`、Agent Configuration 与 Application Surfaces context | 是 | Draft、Published Agent、Agent Configuration API 与 UI 权限边界 | 无 |
| 当前实现 | API factory、development configuration router、PostgreSQL Agent repository、production composition、Dashboard | 是 | production 路由缺失；PostgreSQL Draft/Version/UoW 已存在；前端硬编码 import path | 无 |
| 发布参数 | release candidate、Phase F evidence、生产依赖 | 否；本切片不读取生产材料 | publication 维持现有权威 | 不属于当前实现 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `NO_BLOCKING_GAPS` |
| 需求分析输入 | 用户确认、稳定复现、已接受产品边界、S5 计划、PostgreSQL repository/UoW 和现有 Dashboard 调用 |
| 证据缺口 | 无 P0/P1 缺口；正式部署与发布 Gate 明确排除 |
| 高风险评审 | 状态、幂等、并发、事务、权限、审计和 production fail-closed 已进入设计树与测试任务 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 让 production Dashboard 通过 capability 驱动的 PostgreSQL Agent Draft API 初始化和管理唯一 Agent 的基础元数据，不再调用 development-only manifest import 路由 |
| 范围内 | capability、唯一 Draft 初始化、列表、Draft/Contract/Version 读取、基础元数据 CAS 更新、审计、前端适配和回归测试 |
| 范围外 | validation、publication、rollback、active-pointer mutation、完整 Contract/module 编辑、任意 Agent、生产 SQL 或部署 |
| 非目标 | 挂载 development router；使用 filesystem fallback；自动发布 demo Agent；把本地测试描述为生产批准 |
| 验收标准 | 公开 API、安全分支、幂等/CAS/审计和 Dashboard 闭环测试通过；原始 production POST 复现转绿；未支持操作不显示 |
| `feature_context.md` 更新 | 已创建 |
| ADR 处理 | 不需要；ADR-0124 和现有 production 权威决策已覆盖难逆边界，当前 capability/API slice 可局部演进 |

## 5. 设计树方案

| 节点 | 类型 | 触发条件或输入 | 处理方案 | 输出或状态变化 | 范围边界 | 验证点 | 风险等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | production Agent owner 打开 Agents 页面 | 服务端列出 PostgreSQL Agent 与 capability | 页面只展示有效操作 | 不推断未声明能力 | cross-surface E2E | P1 |
| MAIN-1 | capability | `agent.view` | 返回唯一 template、创建/导入、模块和生命周期能力 | 稳定 capability projection | 不包含路径或凭证 | contract test | P1 |
| MAIN-2 | create | `agent.edit`、CSRF、idempotency、基础字段 | 服务端构造 canonical bundle，原子保存 Draft 与审计 | `201` 或幂等 `200` | 不发布、不激活 | service/API/PG | P1 |
| MAIN-3 | read | `agent.view` | 读取 summary、Draft revision、Contract、versions、active pointer | Dashboard General 可加载 | 只读 projection | API/UI | P1 |
| MAIN-4 | update | `agent.edit`、CSRF、expected revision | 更新基础字段并原子审计 | revision 递增 | 不修改 contract | CAS/API/UI | P1 |
| BRANCH-1 | replay | 同 key、同 fingerprint | 返回相同 Draft | 无重复资源或审计 | raw key 不持久化 | idempotency test | P1 |
| BRANCH-2 | mismatch | 同 key、不同 fingerprint | `409 idempotency_key_mismatch` | 无写入 | 不覆盖原请求 | conflict test | P1 |
| BRANCH-3 | singleton | 已存在 sole Agent，使用新 key 初始化 | `409 sole_agent_already_exists` | 保留既有 Draft | 不创建第二 identity | singleton test | P1 |
| BRANCH-4 | auth | 权限或 CSRF 缺失 | 中间件或 route dependency 拒绝 | 无 application call | 不信任 UI | security test | P1 |
| BRANCH-5 | stale update | revision 不匹配 | repository CAS 拒绝 | `409`，原状态不变 | 不做 last-write-wins | PG/API test | P1 |
| BRANCH-6 | dependency | template 或 PostgreSQL 不可用 | fail closed | 稳定失败且无 local fallback | 不读取 browser path | fault test | P1 |
| BOUND-1 | publication | Draft 已保存 | capability 隐藏 publish/rollback；现有 publication service 不变 | 无版本激活 | 不绕过 Phase F | negative test | P1 |

## 6. 澄清问题队列

| 问题 | 状态 | 推荐答案 | 推荐理由 | 影响 | 建议确认人 |
| --- | --- | --- | --- | --- | --- |
| Feature ID | 已关闭 | 使用 `production-agent-lifecycle` | 当前索引无匹配项；名称只描述实现切片 | Feature 文档路径 | 用户已确认推荐方向；ID 为实现追踪标签 |
| 是否直接挂载 development router | 已关闭 | 否 | 依赖 Local Store，并接受浏览器 manifest path | 安全与 production 权威 | ADR/技术设计已确认 |
| 是否在本切片发布 Agent | 已关闭 | 否 | publication 需要 Phase F 和真实在线候选验证 | 避免权威旁路 | S5/现有服务已确认 |
| 是否支持多个 Agent | 已关闭 | 否 | Initial private pilot 是 sole Agent | API 与 UI inventory | ADR-0124 已确认 |
| production 可编辑哪些模块 | 已关闭 | 仅 General；Contract/Versions/Monitor 只读 | 其他模块缺少独立 production application authority | capability projection | 当前缺陷范围与安全边界 |

## 7. 关键规则与影响范围

| 对象 | 影响说明 | 证据来源 | 确认状态 | 风险等级 |
| --- | --- | --- | --- | --- |
| `AgentLifecycleRepository` | 增加 revisioned Draft 列表，用于 singleton、summary 和 capability | persistence contracts | 已确认 | P1 |
| Production Agent application | 负责 canonical template、幂等、CAS 和 audit transaction | hicode rules、S5 | 已确认 | P1 |
| Production API | 注册 `/api/config/agents` 资源并保持 OIDC/CSRF | original bug、security middleware | 已确认 | P1 |
| Dashboard | 不再在 Create Agent 请求中发送 `manifest_path` | technical design | 已确认 | P1 |
| Publication | 不修改 `ProductionAgentPublicationService` 行为 | S5 release authority | 已确认 | P1 |

## 8. 风险与阻断建议

| 风险 | 等级 | 证据 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| UI capability 与路由再次漂移 | P1 | 当前 404 即由跨表面缺测造成 | 增加 production app + Dashboard capability 闭环测试 | 研发与测试负责人未指定 |
| 创建重试产生重复 Draft | P1 | mutation 可能遇到未知网络结果 | Idempotency-Key、持久化指纹、singleton 与并发测试 | 研发负责人未指定 |
| Draft 写入成功但审计丢失 | P1 | 两者属于同一配置事件 | 使用 Configuration UoW 原子提交 | 安全负责人未指定 |
| 普通编辑绕过 publication Gate | P1 | Dashboard 原有 publish 路径是 development store 行为 | production capability 隐藏并不注册相关 mutation | 发布负责人未指定 |
| 误称本地修复为生产就绪 | P1 | 当前 release 仍是 NO-GO | 结论仅允许 `LOCAL_VERIFIED` 或 `PARTIAL_VERIFICATION` | 发布负责人未指定 |

## 9. 推荐设计树方案与取舍

| 方案 | 是否推荐 | 主干逻辑 | 分支处理 | 范围边界 | 收益 | 代价或风险 | 不选原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Production-specific application + capability | 是 | server template → PostgreSQL Draft/UoW → capability UI | 幂等、CAS、权限、审计、fail closed | 不发布、不挂载 Local Store | 权威清晰、可审计、可逐步扩展 | 新增 API/application 与前后端 contract | 推荐 |
| 直接挂载 development configuration router | 否 | 复用 Local Store handler | 依赖 filesystem | 会暴露大量 development mutation | 改动少 | 违反生产权威与 manifest 禁令 | 安全边界不可接受 |
| 仅隐藏 Create/Import | 否 | production UI 不展示操作 | 无新增 API | 继续无法通过 Dashboard 初始化 Draft | 快速止血 | 不满足用户要求和 PRD | 只适合临时 containment |

## 10. 设计树到 TDD 任务计划

| 项 | 内容 |
| --- | --- |
| 任务计划结论 | `TDD_INPUT_READY` |
| 下一步路由 | `hicode:tdd` |
| 未覆盖设计树节点 | 正式 deployment、release Gate 和完整 Contract/module 编辑已明确排除 |

### Task PAL-1：固定 production API 与 capability contract

- 目标：让 production application 注册 Agent list/create/read/update/contract/version 路由，并以公开响应声明可用能力。
- TDD 起点：将原始 404 转为受 OIDC/CSRF 保护的已注册路由；断言请求 schema 不含 manifest path。
- 停止条件：需要修改 production publication 或数据库 schema。

### Task PAL-2：实现 PostgreSQL Draft application

- 目标：实现 canonical template、singleton、幂等、revision CAS 与原子审计。
- TDD 起点：application service 首次创建、同请求重放、不同请求冲突、事务回滚。
- 停止条件：现有 UoW 无法在不改 schema 的情况下保证所需一致性。

### Task PAL-3：接入 production composition

- 目标：将 application 注入 production API，依赖缺失时启动失败关闭。
- TDD 起点：production composition route inventory 和 required dependency 测试。
- 停止条件：需要读取生产配置、凭证或执行部署。

### Task PAL-4：改造 Dashboard

- 目标：Create Agent 使用 server-owned endpoint，页面按 capability 隐藏 manifest import 和未实现模块。
- TDD 起点：AgentsPage/CreateAgentWizard/API client 的请求与可见操作测试。
- 停止条件：前端需要推断后端未声明能力。

### Task PAL-5：回归和证据

- 目标：原始复现转绿，并完成相关 backend/frontend/type/lint 验证。
- TDD 起点：production route regression、targeted suites、`git diff --check`。
- 停止条件：验证需要生产连接、生产数据或发布操作。

## 11. TDD 输入与测试重点

| 设计树节点 | 场景 | 类型 | 优先级 | 数据要求 | 对应任务 |
| --- | --- | --- | --- | --- | --- |
| MAIN-1 | capability 精确匹配已注册 production 操作 | contract | P1 | 虚构 operator | PAL-1、PAL-4 |
| MAIN-2 | 首次创建保存 canonical Draft 与 audit | integration | P1 | canonical example、虚构身份 | PAL-2、PAL-3 |
| MAIN-3 | 创建后 list/get/contract/versions 可读 | API | P1 | fake UoW 与可选 PostgreSQL fixture | PAL-1、PAL-2 |
| MAIN-4 | 正确 revision 更新基础字段 | API/persistence | P1 | 虚构显示名称和用途 | PAL-2、PAL-4 |
| BRANCH-1/2 | 幂等 replay 与 mismatch | consistency | P1 | 非敏感 key | PAL-2 |
| BRANCH-3 | singleton Agent | consistency | P1 | sole ID | PAL-2 |
| BRANCH-4 | permission 与 CSRF | security | P1 | fake OIDC session | PAL-1、PAL-3 |
| BRANCH-5 | stale revision | concurrency | P1 | revision 1/2 | PAL-2 |
| BRANCH-6 | dependency fail closed | fault | P1 | fake failing UoW/template | PAL-2、PAL-3 |
| BOUND-1 | publish/rollback 不在 capability 与 production router | negative/security | P1 | route inventory | PAL-1、PAL-4 |

## 12. ADR 判断

| 项 | 内容 |
| --- | --- |
| 是否需要 ADR | 否 |
| 判断理由 | 唯一 Agent、PostgreSQL 权威、server-owned manifest 和 candidate-bound publication 已由 ADR-0124、技术设计与 S5 计划确定；本切片不引入新的难逆权威选择 |
| 涉及决策点 | capability response 和 API DTO 可在既有 Agent Configuration API 边界内迭代 |

## 13. 知识沉淀与上下文更新

| 目标文档 | 更新类型 | 内容摘要 | 处理方式 | 确认状态 |
| --- | --- | --- | --- | --- |
| `docs/PROJ_CONTEXT.md` | Feature 索引 | 增加 `production-agent-lifecycle`，状态 `TDD_INPUT_READY` | 本次更新 | 已确认实现追踪 |
| `docs/domain/agent-configuration/CONTEXT.md` | 术语 | 当前术语已覆盖 Draft、Configuration API、Local Store 和 Publication | 不更新 | 无新术语 |
| `docs/domain/agent-configuration/decisions.md` | 决策 | 现有 server-owned/production publication 决策足够 | 不更新 | 无新难逆决策 |
| `docs/development-progress.md` | 状态 | 仅在完成本地验证后记录，避免提前声明 | TDD 完成时更新 | 待真实证据 |
