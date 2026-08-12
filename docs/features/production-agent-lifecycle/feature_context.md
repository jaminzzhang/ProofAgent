# Production Agent Lifecycle Feature Context

## 1. 需求基本信息

| 字段 | 内容 |
| --- | --- |
| 需求名称 | 修复 production Dashboard 创建唯一 Agent 时的 API 404 |
| Feature ID | `production-agent-lifecycle` |
| 需求来源 | 用户确认“按推荐进行修复”；2026-08-12 本地复现；`docs/prd.md`；ADR-0124；S5 唯一生产 Agent 计划 |
| 所属版本 | Initial private pilot；具体发布版本未指定 |
| 业务、研发、测试、发布负责人 | 未提供；不在本地实现中推定 |
| 当前状态 | `PARTIAL_VERIFICATION`；实现和默认本地回归已完成，真实 PostgreSQL 与部署验证待补，不代表已发布或生产批准 |

## 2. 需求目标与范围

| 目标 | 说明 | 验收口径 |
| --- | --- | --- |
| 消除无效创建入口 | production Dashboard 只展示后端明确声明可用的 Agent 操作 | 页面展示的创建、列表、读取和元数据更新操作均有 production API；不再落入通用 404 |
| 使用生产权威 | 唯一 Agent Draft 和配置审计写入 PostgreSQL | Draft 与审计在同一事务提交；依赖失败时不写入部分状态 |
| 固定服务器模板 | 创建操作由服务端解析唯一 `agent_management_insurance_specialist` 模板 | 请求不包含 `manifest_path`、Agent ID 或 Workflow Template 权威字段 |
| 保持安全边界 | OIDC 身份、命名权限、CSRF、幂等和 revision CAS 继续由服务端强制执行 | 缺少权限、CSRF、`Idempotency-Key` 或正确 revision 时返回稳定失败且不写状态 |

### 范围内

| 范围项 | 说明 | 依据 |
| --- | --- | --- |
| Agent capability projection | 列表和 Draft 响应声明当前模式可用的创建、导入、编辑模块和生命周期视图 | Dashboard 不得根据路由或 provider 名称推断能力 |
| 唯一 Agent 初始化 | `POST /api/config/agents` 从服务器自有模板创建唯一 Draft | ADR-0124；S5 Task 3、Task 9 |
| 列表与读取 | production 支持 Agent 列表、Draft、Contract Bundle 和版本只读投影 | 创建后的 Dashboard 主路径必须可继续读取 |
| 元数据更新 | production 支持对 `display_name`、`purpose` 执行 revision CAS 更新 | 当前创建向导允许设置这两个字段 |
| 审计与幂等 | 创建和更新写入 trace-safe 配置审计；创建重试按请求指纹判定 | `docs/rules/hicode-coding-rules.md` |
| Dashboard 适配 | 创建向导不再发送 manifest path；production 隐藏 manifest import 和未实现模块 | `docs/technical-design.md` 的浏览器权威边界 |

### 范围外与非目标

| 范围项 | 排除原因 | 影响 |
| --- | --- | --- |
| production Agent 发布、回滚或自动激活 | 已有 `ProductionAgentPublicationService` 绑定 Phase F、真实在线验证和 active-pointer CAS；普通 Dashboard 保存不得绕过 | capability 必须明确隐藏 `validate`、`publish` 和 `rollback` |
| 任意 Agent ID 或多 Agent catalog | Initial private pilot 只允许唯一 Agent | 创建第二个 Agent 返回稳定冲突 |
| 浏览器 manifest path 或任意包导入 | 浏览器不得提供可信 manifest path；production 镜像不得执行浏览器选择的文件 | development import 保留为显式开发能力 |
| Workflow、Skill、Knowledge、Tool、Policy、Model、Memory、Response 编辑 | 这些模块需要各自的 production 权威和发布验证；本缺陷切片不建立旁路 | production Agent Detail 仅展示 General、Versions、Contract 和 Monitor |
| 修改数据库 schema、生产配置或执行部署 | 当前表可保存 Draft、版本和审计；本地实现不构成部署批准 | 不运行生产 SQL、发布或回滚 |

## 3. 设计树

| 节点 | 类型 | 触发条件或输入 | 处理方案 | 输出或状态变化 | 验证点 | 风险等级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | 已认证 Agent owner 在 production Dashboard 创建唯一 Agent | Dashboard 按服务端 capability 调用 production Agent API | 创建操作成功或返回稳定受控错误，不再返回通用 404 | production API 与 Dashboard 闭环测试 | P1 | 已确认 |
| MAIN-1 | 能力发现 | `GET /api/config/agents` | 返回 Agent 列表及 capability projection | UI 只展示允许的创建、导入、模块和生命周期操作 | API contract 与页面测试 | P1 | 已确认 |
| MAIN-2 | 创建 | `agent.edit`、有效 CSRF、`Idempotency-Key`、显示名称和用途 | 服务端加载唯一模板，生成 Draft，原子保存 Draft 与审计 | 首次返回 `201`；同请求重放返回同一 Draft | 应用服务、API、PostgreSQL 测试 | P1 | 已确认 |
| MAIN-3 | 创建后读取 | `agent.view`、唯一 Agent ID 和 Draft ID | 从 PostgreSQL 读取 Draft、Contract、Published Versions 和 Active Version | Dashboard General 页面可加载 | API 与页面测试 | P1 | 已确认 |
| MAIN-4 | 元数据更新 | `agent.edit`、有效 CSRF、正确 `expected_revision` | 更新显示名称和用途，原子保存新 revision 与审计 | 返回更新后的 Draft 与 revision | CAS、事务和页面测试 | P1 | 已确认 |
| BRANCH-1 | 幂等冲突 | 相同 key、不同请求指纹 | 拒绝请求，不修改既有 Draft | `409 idempotency_key_mismatch` | 重放测试 | P1 | 已确认 |
| BRANCH-2 | 已存在 Agent | 不同 key 再次初始化，或已有生产 Draft | 拒绝创建并返回既有资源冲突 | `409 sole_agent_already_exists` | 单例与并发测试 | P1 | 已确认 |
| BRANCH-3 | 权限或 CSRF 拒绝 | 缺少 `agent.view`、`agent.edit` 或 CSRF | 在业务服务调用前拒绝 | `401`、`403`，无状态变化 | API 安全测试 | P1 | 已确认 |
| BRANCH-4 | revision 冲突 | PATCH 的 `expected_revision` 不是当前 revision | PostgreSQL CAS 失败 | `409 agent_draft_revision_conflict` | repository 与 API 测试 | P1 | 已确认 |
| BRANCH-5 | 模板或数据库不可用 | 服务器模板缺失、PostgreSQL 失败或返回不一致状态 | 失败关闭，不切换本地存储 | 稳定 `503` 或受控 `500`，无部分提交 | fault 测试 | P1 | 已确认 |
| BOUND-1 | 发布边界 | Draft 已创建或更新 | 不发布、不激活、不生成伪验证记录 | production publication 权威保持不变 | 负向路由与 capability 测试 | P1 | 已确认 |

## 4. 核心业务规则

| 规则编号 | 规则说明 | 边界或例外 | 状态 |
| --- | --- | --- | --- |
| PAL-R01 | production 只允许 `agent_management_insurance_specialist`，并由服务端选择 canonical template | development 可保留显式 manifest import，但不得把该能力投影为 production 能力 | 已确认 |
| PAL-R02 | `POST /api/config/agents` 不接受 `manifest_path`、`agent_id` 或 Workflow Template 字段 | 未知字段由 strict request contract 拒绝 | 已确认 |
| PAL-R03 | production Draft、revision 和配置审计以 PostgreSQL 为权威 | 不允许 filesystem 或 in-memory fallback | 已确认 |
| PAL-R04 | 创建必须携带 `Idempotency-Key`；同 key、同指纹返回同一 Draft，同 key、不同指纹返回 `409` | raw key 不进入响应、日志或审计；仅保存不可逆摘要 | 已确认 |
| PAL-R05 | Draft 创建或更新与对应审计事件在一个事务中提交 | 任一写入失败时全部回滚 | 已确认 |
| PAL-R06 | 读取需要 `agent.view`；创建和更新需要 `agent.edit`；production mutation 继续受 same-origin CSRF 保护 | Dashboard 不提供权限替代 | 已确认 |
| PAL-R07 | PATCH 必须提供 `expected_revision`，陈旧写入不得覆盖新状态 | development 可接受该字段并继续使用本地锁，但 production 必须 CAS | 已确认 |
| PAL-R08 | Dashboard 只渲染 capability 声明允许的操作 | capability 缺失时采取保守行为，不显示 production-only 创建假象 | 已确认 |
| PAL-R09 | Draft 创建或更新不等于 validation、publication 或 activation | 发布继续使用候选绑定的 production publication 服务 | 已确认 |

## 5. 高严谨业务系统风险基线

| 维度 | 是否涉及 | 已知规则或证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑严谨性 | 是 | 唯一 Agent、V3-only 和 production publication 边界 | 无 P0/P1 阻断项 | P1 |
| 金额与关键数值精度 | 否 | 本功能不处理金额或保险计算 | 无 | NONE |
| 交易与数据一致性 | 是 | Draft 与审计同事务；PostgreSQL 权威 | 无 P0/P1 阻断项 | P1 |
| 状态流转 | 是 | Draft 创建、revision 更新与 Published Version 分离 | 无 P0/P1 阻断项 | P1 |
| 幂等与并发 | 是 | 创建指纹、单例初始化、revision CAS | 无 P0/P1 阻断项 | P1 |
| 权限与审计 | 是 | OIDC、命名权限、CSRF、trace-safe audit | 无 P0/P1 阻断项 | P1 |
| 隐私与适用监管或合规 | 是 | 不记录 raw idempotency key、manifest path、凭证或包内容 | 具体生产保留策略沿用 Audit Repository | P2 |
| 生产变更与回滚 | 是 | 不改 schema、不发布 Agent、不执行部署 | 部署与 Gate 证据不属于本地实现 | P1 |

## 6. 影响范围

| 类型 | 对象 | 影响说明 | 风险等级 |
| --- | --- | --- | --- |
| 应用服务 | `proof_agent/control/` | 新增 production Agent Draft application boundary | P1 |
| 持久化 | `AgentLifecycleRepository`、PostgreSQL adapter、Configuration UoW | 增加 Draft 列表和 revisioned save 的调用路径，不改 schema | P1 |
| Delivery | production Agent configuration router、application factory、production composition | 新增受 OIDC/CSRF 保护的 API | P1 |
| Dashboard | Agents 页面、创建向导、Agent Detail、API types/client/hooks | 改为 capability 驱动并移除创建请求中的 manifest path | P1 |
| 测试 | application、API、PostgreSQL、Dashboard 闭环 | 增加生产路由与跨表面回归 | P1 |
| 文档 | Feature 证据与项目 Feature 索引 | 记录 Scope、TDD 和本地验证结果 | P2 |

## 7. 测试与发布关注点

| 关注项 | 类型 | 优先级 | 证据或说明 |
| --- | --- | --- | --- |
| production POST 不再返回通用 404 | regression | P1 | 2026-08-12 原始复现 |
| 请求不含 manifest path 或 Agent/Workflow 权威 | security/contract | P1 | `docs/technical-design.md` |
| 创建幂等、单例和并发 | consistency | P1 | hicode coding rules |
| Draft 与审计原子提交 | transaction/audit | P1 | PostgreSQL Configuration UoW |
| permission 与 CSRF | security | P1 | production session middleware |
| revision CAS | concurrency | P1 | `AgentDraftRecord.revision` |
| capability 与 UI 行为一致 | cross-surface | P1 | 不允许可见按钮指向缺失路由 |
| publication 权威未削弱 | negative/security | P1 | `ProductionAgentPublicationService` |

## 8. 待确认问题

无未关闭 P0/P1 问题。正式部署、发布 Gate 和未来 production Contract 编辑模块由对应负责人另行确认，不阻断本缺陷切片。
