# KSS Configuration And Agent Publication Loop Scope、准入与 TDD 计划

本文件记录 2026-08-25 至 2026-08-30 的设计评审和已确认编码范围。设计准入为 `READY_FOR_TDD`；执行证据见 `tdd-report.md`，不代表生产批准。

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `READY_FOR_TDD` |
| 最高风险等级 | P1 |
| 一句话依据 | 闭环内所有 P1 架构决策已经用户确认并写入 ADR/领域模型；当前差距属于需要测试先行交付的实现与生产证据，而非未决设计 |
| 下一步建议 | 按 TDD-01 至 TDD-07 逐个交付 tracer bullet；任何本地 green 都不等于 Production GO |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| 共享仓库规则 | `AGENTS-COMMON.md`、`docs/rules/hicode-coding-rules.md` | 是 | Control Plane、fail-closed、secret 与生产证据边界 | 无 |
| 领域路由与状态 | `CONTEXT-MAP.md`、`docs/DOMAIN_KNOWLEDGE.md`、`docs/PROJ_CONTEXT.md` | 是 | KSS-only、Draft candidate、formal publisher 分离 | 无 |
| KSS 管理实现 | `knowledge_source_service/delivery/management_http.py` | 是 | KSS 已有 ingest、sync、Release API；当前 Release state 仅 `queryable/retired` | preparation/CAS、deprecate/revoke、引用保护和 operator auth 未完整产品化 |
| ProofAgent KSS BFF | `proof_agent/delivery/knowledge_service_management_api.py` | 是 | 只读 workspace 与 Space/Source/Base 创建 | 缺 ingest、sync、Release、任务和恢复命令 |
| Agent authoring | `proof_agent/control/agent_configuration_workspace.py` | 是 | Draft 保存 exact Release candidate | Draft 还未进入 formal publisher |
| 正式发布 | `proof_agent/control/production_agent_publication.py`、`proof_agent/bootstrap/production_roles.py` | 是 | manifest 与环境 KSS Release 构造独立候选 | 需要切换为 exact Draft revision authority |
| Dashboard | `KnowledgeServicePanel.tsx`、`KnowledgeModuleEditor.tsx`、`PublicationConfigurationModule.tsx` | 是 | 资源创建、Draft 选择和只读发布投影 | 无完整数据与正式发布操作流程 |
| 聚焦测试 | `uv run --extra dev pytest ...` | 是 | 10 passed，锁定现有边界 | 未运行真实生产依赖与发布 Gate |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `READY_FOR_TDD` |
| 需求分析输入 | 用户要求检查并规划 KSS 数据、配置及 ProofAgent 使用的完整流程；已确认终点包括正式生产发布和原子激活，并保持分权 |
| 执行证据缺口 | Connection Profile 已有本地 PostgreSQL/HTTP/同步 Worker 证据；TDD-02A 至 02G 已有 Preparation 持久化准入、租约协调、候选构建、fenced `ready/failed` 结果、`ready → expired/consumed` 核心单事务发布、显式 one-shot 主动过期和 queued/running 协作取消；TDD-04E/04F/04H 已公开 controlled publish/cancel/exact-expire KSS/BFF，TDD-04G 已公开有界、secret-free audit read BFF，但仍无常驻 Worker、自动过期调度或终端操作者委托身份，既有直接 Release 发布路径也尚未收敛。异常 ready quarantine、真实策略/Secret/egress/TLS、生产进程切换、Reference/lifecycle command 闭环、正式 publisher cutover、三角色端到端与 Phase F 尚未完成；正式验收人员仍需在发布前指派 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 形成 KSS 数据接入到 ProofAgent 正式使用、观察和回滚的完整权威流程 |
| 范围内 | KSS 数据与 Release；ProofAgent BFF；Agent Draft exact binding；Phase F 正式发布；运行与回滚投影 |
| 范围外 | Query-time live federation、浏览器凭据、Knowledge 动作直接激活 Agent、KSS Admission/answer authority |
| 非目标 | 不把本地验证当作 Production GO；部署、生产配置和 SQL 变更另行确认 |
| 验收标准 | 每个状态和权威交接有 exact identity、权限、审计、失败结果、并发规则和可复核证据 |
| feature_context 更新 | 已新建 |
| ADR 处理 | 已新增 ADR-0212 至 ADR-0217 |

## 5. 设计树方案

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 范围边界 | 验证点 | 风险等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | 一组知识需要供生产 Agent 使用 | 贯通 KSS 与 ProofAgent 两个权威域 | 可执行、可回放的 Published Agent Version | 不合并两服务数据权威 | exact identity E2E | P1 |
| MAIN-1 | KSS 数据 | 文件或外部连接 | 摄取/同步为 immutable Source Version | Version 可组合 | 不在 query 时访问 upstream | intake、sync、lineage | P1 |
| MAIN-2 | KSS Release | exact Base Draft revision | 启动时解析 selection policy 并冻结 Base Version；持久化状态机异步准备后一次性 CAS 发布 | queryable exact Release、consumed Preparation | 仅在 Preparation 启动时解析 latest；Query 不解析 | state、fencing、atomicity、replay、resolution race | P1 |
| MAIN-3 | Draft authoring | Agent Editor 选择 Release | revision CAS 保存 secret-free candidate | Draft 前进 | 不改变 Active Version | conflict、catalog revalidation | P1 |
| MAIN-4 | 正式发布 | Release Operator 提交 exact Draft revision | 重验后组合部署级 Profile 和候选证据 | Formal Production Agent Candidate | 不接受独立 manifest 候选 | identity、permission、freshness | P1 |
| MAIN-5 | 激活与运行 | Phase F 和 smoke 通过 | 冻结版本并 CAS 激活；运行 exact KSS binding | 引用回答或治理失败 | no fallback | failure atomicity、citation | P1 |
| BRANCH-1 | 失败关闭 | dependency/Release/Grant/Secret/Scorer 异常 | 停止当前命令 | 稳定 blocker/problem | 不替换 authority | negative matrix | P1 |
| BRANCH-2 | 并发 | Draft 或 Release 在提交后变化 | 拒绝并要求重载 | 无发布副作用 | 不接受 stale facts | race tests | P1 |
| BRANCH-3 | 回滚 | Active Version 需回退 | 选择仍有效的 KSS-bound version | pointer CAS | 不恢复旧 Hybrid | recovery drill | P1 |

## 6. 澄清问题队列

| 问题 | 状态 | 推荐答案 | 推荐理由 | 影响 | 建议确认人 |
| --- | --- | --- | --- | --- | --- |
| 完整流程是否覆盖正式生产发布与原子激活？ | 已关闭 | 是，但 Knowledge、Agent authoring、Release 权威分离 | 否则只能称为 authoring 流程，不能形成正式使用流程 | feature 边界、ADR、publisher authority | 用户已确认 |
| 外部 Source Connection Profile 的权威放在哪里？ | 已关闭 | KSS 管理 Connection Profile Draft/Published Revision；Secret 值由 Vault 持有；Dashboard 只通过 BFF 管理非敏感字段；部署拥有 connector、egress、trust root 和硬限制策略 | 在不泄漏 secret 的前提下获得 revision、审计、权限和无重启变更，并保留部署安全边界 | KSS contract、DB、Vault、egress、Dashboard、Worker | 用户已确认，技术与安全负责人实施前复核 |
| Knowledge Base 应如何维护 Source 组合并选择 Source Version？ | 已关闭 | KSS 维护长期可编辑的 Base Draft；成员默认在 Preparation 开始时解析 `latest_ready_at_preparation`，受监管材料可固定 exact Version；Preparation 冻结并展示完整 exact plan 后再发布 | 兼顾日常运维与可重放性，运行时仍只看到 exact Release | Base contract、Preparation、Dashboard、审计、并发 | 用户已确认，KSS 数据负责人实施前复核 |
| 生产是否强制不同自然人执行 Knowledge Prepare/Publish 与 Agent Edit/Release？ | 已关闭 | 首期按 Knowledge Operator、Agent Editor、Release Operator 三个粗粒度角色包管理；角色可叠加、权限取并集，不做强制四眼、per-Space ACL 或 negative grant | 降低初期管理复杂度，同时保留服务端 named permission 和审计边界供后续细分 | OIDC mapping、BFF、KSS management client、audit、Dashboard | 用户已确认，安全负责人实施前复核 |
| 被 Agent Version 引用的 KSS Release 如何退役或紧急撤销？ | 已关闭 | 普通退役先进入 deprecated，阻止新绑定但保留既有运行；零可执行引用且满足 retention 后才 retired；安全事件允许 emergency revoke 并使既有运行失败关闭；物理删除另行授权 | 同时保护稳定运行、可回滚性和紧急止损能力 | KSS catalog、Agent reference facts、query、rollback、retention | 用户已确认，KSS/发布/安全负责人实施前复核 |
| KSS 如何证明一个 Release 已无跨客户端可执行引用？ | 已关闭 | KSS 持有 client-registered Release Reference Ledger；Agent 发布前先注册 exact reference，失去执行/保留资格后注销；retire 只读该账本并失败关闭；孤儿引用由认证对账任务保守清理 | 独立 KSS 不能信任单个 retirement caller 自报零引用，也不能只查询 ProofAgent | KSS reference API、Agent publication、idempotency、reconciler、retention | 用户已确认，KSS/ProofAgent/平台负责人实施前复核 |
| Release Preparation 的最小公开状态和重试语义是什么？ | 已关闭 | `queued → running → ready / failed / cancelled`，ready 超时变 `expired`，成功发布后为 `consumed`；相同 Idempotency-Key 返回同一 Preparation，失败重试创建新 identity；publish 仅消费一次 ready candidate | 状态足够支撑 Dashboard 与恢复，同时避免复用 stale/failed preparation | management API、Worker、Dashboard、fencing、CAS | 用户已确认，KSS 数据/平台负责人实施前复核 |

## 7. 关键规则与影响范围

| 对象 | 影响说明 | 证据来源 | 确认状态 | 风险等级 |
| --- | --- | --- | --- | --- |
| KSS logical authority | KSS 独占 Source/Version/Base/Release | ADR-0193、ADR-0210 | 已确认 | P1 |
| Draft candidate | 只存 exact secret-free authoring intent | ADR-0211 | 已确认 | P1 |
| Formal Production Agent Candidate | exact Draft revision 是正式候选根 | 2026-08-25 用户确认、ADR-0212 | 已确认 | P1 |
| Connection Profile authority | KSS 拥有非敏感 Profile revision；Vault 与部署策略保留各自权威 | 2026-08-25 用户确认、ADR-0213 | 已确认 | P1 |
| Base composition | Base Draft 只用于管理；Preparation 将 selection policy 冻结为 exact Base Version | 2026-08-25 用户确认、ADR-0214 | 已确认 | P1 |
| Initial role bundles | Knowledge Operator、Agent Editor、Release Operator 可叠加，映射到全局 named permissions | 2026-08-25 用户确认、ADR-0103、ADR-0126、ADR-0174 | 已确认 | P1 |
| Release lifecycle | deprecated 保护既有引用；retired 需零引用与 retention；emergency revoke 立即失败关闭 | 2026-08-25 用户确认、ADR-0215 | 已确认 | P1 |
| Release Reference Ledger | KSS 持有跨客户端可执行/回滚引用；注册先于外部激活，失败保守留引用 | 2026-08-25 用户确认、ADR-0216 | 已确认 | P1 |
| Release Preparation | durable minimal state machine、one-use ready candidate、new-identity retry、lease/fencing | 2026-08-26 用户确认、ADR-0217 | 已确认 | P1 |
| Dashboard | 配置与观察，不凭渲染获得命令权限 | AGENTS-COMMON、ADR-0154 | 已确认 | P1 |
| Release evidence | Phase F、online smoke 与激活保持独立权威 | 当前 formal publisher | 已确认 | P1 |

## 8. 风险与阻断建议

| 风险 | 等级 | 证据 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| UI 配置与正式发布使用不同候选 | P1 | 当前 publisher 使用 manifest 和环境 Release | 以 exact Draft revision 替代独立候选输入 | 架构与发布负责人 |
| Dashboard 扩展后获得 secret 或过宽权限 | P1 | 当前 BFF 是 secret-free projection；ADR-0213 已确定分权 | 写 API 只接受 trace-safe 字段和 Secret Handle 引用，并由服务端复核部署策略 | 安全负责人 |
| 粗粒度角色被实现为一个 admin 布尔值 | P1 | 已确认角色可叠加但动作边界仍使用 named permissions | 角色只作为部署映射包；每个 BFF/Control 命令检查自己的 permission 并记录拒绝审计 | 安全负责人 |
| Release 发布存在双入口 | P1 | Preparation 核心已具备短事务 one-use CAS，但既有直接 `KnowledgeReleaseApplication.publish()` 仍可发布 Release | 后续受控切换管理/BFF 入口并明确兼容路径退场，不在本地切片中静默替换生产调用 | KSS 数据负责人 |
| 跨服务事务被误设计为一个分布式事务 | P1 | KSS 与 ProofAgent 分属独立权威 | 使用 immutable reference、live revalidation 和各自本地事务 | 架构负责人 |
| 回滚目标的 KSS Release 已退役 | P1 | ADR-0215 已定义 retired/revoked 不可用 | 普通退役依赖权威引用保护；回滚预检 exact Release；紧急撤销后明确失败关闭 | 发布与 KSS 负责人 |
| 跨服务发布中间失败产生孤儿 reference | P1 | ADR-0216 选择保守 ordering | 保留引用并通过 authenticated reconciler 清理；禁止 TTL 自动失效或补偿性盲删 | KSS/ProofAgent 负责人 |

## 9. 推荐设计树方案与取舍

| 方案 | 是否推荐 | 主干逻辑 | 分支处理 | 范围边界 | 收益 | 代价或风险 | 不选原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 双权威、完整流程 | 是 | KSS 发布 Release；ProofAgent 从 exact Draft 正式发布 Agent | 每次交接重验并失败关闭 | 数据动作不激活 Agent | 可审计、可回放、可安全回滚 | API 和状态资源较多 | — |
| 仅补 Dashboard authoring | 否 | 数据和 Draft 配置止于只读发布投影 | 正式 CLI 继续独立 | 不改 publisher | 实施较小 | 保留双候选断点 | 不满足已确认的完整流程 |
| 单一 Dashboard 超级发布动作 | 否 | 数据发布顺带 Agent 激活 | 由前端串联命令 | 权威边界模糊 | 表面步骤少 | 易绕过 Phase F、权限和失败原子性 | 违反分权决定 |

## 10. 设计树到 TDD 任务计划

| 项 | 内容 |
| --- | --- |
| 任务计划结论 | `READY_FOR_TDD` |
| 交付策略 | 从 KSS authority 向 ProofAgent formal publication 纵向推进，每个切片先写失败的 contract/negative/concurrency 测试，再做最小实现 |
| 生产边界 | TDD 完成只提供候选实现证据；真实 PostgreSQL、MinIO、OpenSearch、Secret、egress、Phase F 和在线 smoke 全部通过后才可单独评估 Production GO |

| 切片 | 可独立验收的纵向结果 | RED：先建立的失败证据 | GREEN：最小实现范围 | 验证与退出条件 | 依赖 |
| --- | --- | --- | --- | --- | --- |
| TDD-01 | Knowledge Operator 可创建、验证并发布非敏感 Connection Profile revision，再触发一次 exact-profile 同步 | inline secret 被接受、未发布 profile 被 Worker 使用、部署策略缺失时仍放行 | KSS domain/PostgreSQL/management API；Secret Handle 与 deployment-policy ports；静态 JSON 仅保留显式迁移边界 | contract + PostgreSQL + secret-free projection + missing dependency fail-closed | 无 |
| TDD-02 | Knowledge Operator 可维护 Base Draft，并把 exact revision 异步准备为一次性 exact Release | runtime latest、重复 member、跨 Space、stale fence、重复 publish、failed preparation 复用 | Base Draft/Version、Preparation state、queue/lease/fencing、Prepared Release、one-use CAS | memory + PostgreSQL race tests；多 Source 文档/结构化 fixture；无部分 query visibility | TDD-01 |
| TDD-03 | KSS 可注册 client reference，并安全执行 deprecate、retire、revoke 与删除资格判断 | 有引用仍 retire、deprecated 新注册、revoked fallback、TTL 误删 orphan reference | Reference Ledger API/repository、Release lifecycle、query/catalog gates、authenticated reconciler | registration/retirement serialization、retention、emergency negative matrix | TDD-02 |
| TDD-04 | ProofAgent Dashboard 经 BFF 完成 Profile → Sync → Base Draft → Preparation → Release 的 secret-free 管理闭环 | 浏览器收到 secret/endpoint/raw problem、单角色越权、UI 推断状态 | management client/contracts/BFF、三角色 bundle mapping、KnowledgeServicePanel 状态与 blocker 投影 | API/client/UI tests；单角色 deny 与多角色 union；浏览器 projection snapshot | TDD-01 至 03 |
| TDD-05 | Release Operator 从 exact Agent Draft revision 正式发布，并在激活前注册 KSS reference | publisher 接受独立 manifest/latest Draft/env Release、reference 失败仍激活、Phase F/smoke 失败改变 Active | formal publisher 读取 Draft、live catalog revalidation、deployment Binding Profile、reference-first ordering、PostgreSQL activation CAS | publisher authority/race/failure-atomicity tests；删除独立候选入口 | TDD-03、TDD-04 |
| TDD-06 | 已发布 Agent 可运行、回滚和对账；deprecated 继续服务，retired/revoked 稳定失败关闭 | rollback 到不可用 Release、孤儿 reference 盲删、运行时 local/latest fallback | runtime readiness、rollback preflight、reference deregistration/reconciler、Dashboard affected-reference projection | end-to-end exact identity、recovery drill、negative dependency matrix | TDD-05 |
| TDD-07 | 候选在真实依赖环境完成发布证据闭环 | 任一依赖缺失仍报告通过、focused green 被当成正式 GO | isolated PostgreSQL/MinIO/OpenSearch/Secret/egress suite，Phase F candidate binding，online smoke 与 rollback drill | fail-if-missing；记录 commit/image/config/evidence identities；独立发布负责人判定 | TDD-01 至 06 |

## 11. TDD 输入与测试重点

[FRAME | HIGH] 2026-08-28 用户确认进入 TDD-03 Reference Ledger。首个纵向切片 TDD-03A 只实现可信 application-only 注册核心：认证客户端以 client-scoped Idempotency-Key 为一个 immutable `published_agent_version` 注册 exact Space/Base/Release 的 `execution_or_rollback` reference。仅 `queryable` Release 可注册；exact request 重放返回同一 reference，同一外部资源不得改绑另一 Release；reference、command receipt 与成功审计使用数据库时间在一个 KSS PostgreSQL 事务提交。暂不增加 deprecate/retire/revoke、删除资格、deregister/reconciler、HTTP/BFF、ProofAgent publication/activation、角色接线、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-03A 本地核心已完成。新增 `0014_release_references.sql`、secret-free reference contracts、可信 application Interface、内存与 PostgreSQL adapter；八路同 client/key 并发收敛到同一 active reference 和一条成功审计，retired/missing/scope mismatch 失败关闭，immutable external resource 不可改绑，command audit 故障回滚 reference 与 receipt，`0013 → 0014` 升级及迁移重放通过。完整 KSS 加 ProofAgent KSS/BFF 受影响回归为 375 passed、0 skipped；全仓后端为主套件 2356 passed 加显式 hybrid 2 passed。OpenAPI 未变，Reference registration 尚未接 HTTP、ProofAgent publisher 或 Release lifecycle；详见报告第 19 节。

[FRAME | HIGH] 2026-08-28 用户确认进入 TDD-03B Release deprecation。本片只增加可信 application-only `deprecate(exact Release, operator_id, idempotency_key)`：仅 `queryable → deprecated`；Release 状态、永久 command receipt 与成功审计使用数据库时间并在同一个 KSS PostgreSQL 事务提交。`deprecated` Release 保留既有 active references、既有 query 和 rollback 可用性，但从提交点起拒绝任何新 Reference registration；相同 operator/key/fingerprint 精确重放原结果，key 改绑或非 `queryable` 目标失败关闭。暂不实现 retire、emergency revoke、物理删除资格、deregister/reconciler、HTTP/BFF/Dashboard、ProofAgent publication/activation 接线、角色映射、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-03B 本地核心已完成。Migration `0015` 增加 `deprecated` 与 lifecycle command receipt/success audit；Release 行锁将 registration/deprecation 竞争串行化，八路同 operator/key 并发只生成一个结果和一条审计，审计故障会回滚状态与 receipt。既有 Reference、Catalog query、完整性扫描和已授予 Query authorization 继续可用，新 Reference registration 与新 Query Grant 失败关闭；`0014 → 0015` 升级及 migration 重放通过。完整 KSS 加 ProofAgent KSS/BFF 受影响回归为 388 passed、0 skipped；全仓主套件 2363 passed，另有显式 hybrid integration 2 passed。没有 deprecate HTTP/BFF、普通 retire、emergency revoke、对账、ProofAgent 激活接线、部署或 Production GO；详见报告第 20 节。

[FRAME | HIGH] 2026-08-28 用户确认继续 TDD-03C ordinary retirement admission。本片在现有 `KnowledgeBaseReleaseLifecycleApplication` 增加 `retire(exact Release, operator_id, idempotency_key)`；retention authority 是构造 Application 时由可信服务端注入的 immutable `ReleaseRetentionPolicy(policy_id, minimum_age)`，调用者不得自报引用数、retention 结论、截止时间或时钟。只有 `deprecated`、KSS Reference Ledger 中零 active references，且数据库时间达到 `deprecated_at + minimum_age` 的 Release 才能原子进入 `retired`；结果、永久 receipt 与成功审计记录 policy ID、`retention_eligible_at` 和数据库 `retired_at`。相同 operator/key/fingerprint 精确重放；registration/retirement 使用同一 Release 行锁，retired 后 Catalog query、完整性扫描和既有 Query authorization 失败关闭。暂不实现 deregister/reconciler、emergency revoke、物理删除、HTTP/BFF/Dashboard、ProofAgent publication/activation、生产配置接线、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-03C 普通退役本地核心已完成。Migration `0016` 保留 `deprecated_at` 并新增 `retired_at`、retirement receipt/success audit；可信服务端 retention policy、数据库时间、Release 行锁和 KSS active Reference 检查共同控制 `deprecated → retired`。活动引用或未到保留期时状态与审计不变；八路同键并发只产生一个结果；审计故障回滚状态与 receipt；`0015 → 0016` 升级重放通过。Retired Release 从 Catalog query、完整性扫描和既有 Query authorization 中移除。完整 KSS 加 ProofAgent KSS/BFF 受影响回归为 399 passed、0 skipped；全仓主套件 2374 passed，另有显式 hybrid integration 2 passed。没有 deregister/reconciler、emergency revoke、物理删除、lifecycle HTTP/BFF、ProofAgent 激活接线、生产 retention 配置、部署或 Production GO；详见报告第 21 节。

[FRAME | HIGH] 2026-08-28 用户确认继续 TDD-03D Reference deregistration admission。本片只增加可信 application-only `deregister(release_reference_id, authenticated_client_id, idempotency_key)`：调用方只提交精确 Reference identity，不能自报“不可执行”、回滚资格、验证时间或 Reference 数量。KSS 在事务外调用服务端注入的 `ReleaseReferenceDeregistrationVerifier`，仅接受证明 immutable external resource 已永久失去执行资格且不再保留为回滚目标的 trace-safe verification identity；随后在 KSS 事务内再次检查幂等收据、锁定精确 active Reference、复核 owner 与 verification identity，并以数据库时间原子写入 `deregistered` current state、永久 receipt 和成功审计。精确重放不再次验证；并发 deregistration 与 ordinary retirement 通过 Reference/Release 锁及事务后检查收敛，只有零 active Reference 才解除 retirement 阻塞。暂不实现 ProofAgent verifier/证明签发、后台 orphan scanner、HTTP/BFF/Dashboard、emergency revoke、物理删除、生产配置接线、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-03D application-only 注销准入核心已完成。Migration `0017` 把 Reference current state 扩展为 `active | deregistered`，注册与注销共享 client-scoped 幂等命名空间和有序 command ledger；历史注册 receipt 保持 immutable，注销 state、可信 verifier/verification identity、数据库时间、永久 receipt 与成功审计原子提交。无 verifier、错误 owner、空或错配 verification、重复注销均失败关闭；同键八路并发收敛为一个结果，不同键竞争仅一个成功；注销/普通退役竞态保持保守，审计插入故障回滚 current state 与 receipt；`0016 → 0017` 升级重放通过。三项隔离真实依赖下受影响回归 395 passed、0 skipped；全仓主套件 2384 passed、24 个既有声明 skip、2 deselected，显式 hybrid integration 另有 2 passed。没有 ProofAgent verifier、后台 reconciler、Reference/lifecycle HTTP/BFF、emergency revocation、物理删除、生产配置、部署或 Production GO；详见报告第 22 节。

[FRAME | HIGH] 2026-08-29 用户确认继续 TDD-03E emergency Release revocation。本片在可信 application-only `KnowledgeBaseReleaseLifecycleApplication` 增加 `revoke(exact Release, bounded reason_code, explicit confirmation, operator_id, idempotency_key)`：仅安全事件 `security_incident` 或严重数据完整性故障 `severe_data_integrity_failure` 可把 `queryable` 或 `deprecated` Release 立即转为 `revoked`；固定确认语义为 `fail_closed_without_fallback`，delivery 必须在调用前授权 exact operator。KSS 在 Release 锁内锁定并统计 active Reference，以数据库时间把 `revoked` state、受影响引用数量、永久 receipt 与成功审计原子提交；Reference current/history 不变，既有 Catalog query、完整性扫描、Query authorization 和新 Reference registration 从提交点起失败关闭且不 fallback。相同 operator/key/fingerprint 精确重放；普通 `retired` 与已 `revoked` 不可再次撤销，availability、cleanup 或自由文本不是合法 reason。暂不实现 lifecycle HTTP/BFF/Dashboard、角色映射、affected-reference 明细投影或通知、ProofAgent runtime/rollback 接线、自动替换、物理删除、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-03E application-only 紧急撤销核心已完成。Migration `0018` 增加 `revoked` lifecycle state、受控 reason、数据库 `revoked_at` 和共享有序 revocation receipt/audit；固定 confirmation 与 KSS 事务内锁定/统计的 active Reference 数进入成功结果和审计，Reference current/history 不变。Registration/revocation、deregistration/revocation 和 retirement/revocation 竞态均收敛；同键八路并发只有一个 receipt/audit，审计故障整体回滚；`0017 → 0018` 升级重放通过。Revoked Release 从 Catalog query、完整性扫描和既有 Query authorization 中移除。三项隔离真实依赖下受影响回归 415 passed、0 skipped；全仓主套件 2396 passed、24 个既有声明 skip、2 deselected，显式 hybrid integration 另有 2 passed。没有 lifecycle HTTP/BFF、角色接线、affected-reference 明细/通知、ProofAgent runtime/rollback 接线、物理删除、部署或 Production GO；详见报告第 23 节。

[FRAME | HIGH] 2026-08-29 用户要求提交既有切片并进入下一切片。本片 TDD-03F 只增加可信 application-only `assess_deletion_eligibility(exact Release)` 只读评估：调用方不能提交 Reference 数、artifact retention 结论、生命周期时间、删除原因、operator 或 idempotency key。只有通过普通命令进入且保留完整 `retired_at` 的 `retired` Release、零 active Reference，以及服务端注入的 artifact-retention authority 明确返回 clear 时才返回 `eligible=true`。Deregistered Reference 只作为历史计数，不阻断；`queryable/deprecated` 返回普通生命周期阻断；`revoked` 无论引用或 artifact 状态如何都返回 emergency incident-retention 阻断。缺少或未明确放行的 artifact authority 必须失败关闭。本片不写状态、receipt 或 audit，因此没有 command idempotency；未来物理删除命令不得信任旧评估，必须在执行事务中重验并单独持久化审计。暂不实现物理删除、incident clearance、artifact 删除 adapter、HTTP/BFF/Dashboard、部署、生产配置或生产 SQL。

[FRAME | HIGH] 2026-08-29 用户确认继续下一切片，进入 TDD-04A 只读管理 tracer。本片新增 KSS `GET /v1/knowledge-spaces/{knowledge_space_id}/knowledge-bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility` 和同源 ProofAgent BFF `GET /api/config/knowledge-service/spaces/{knowledge_space_id}/bases/{knowledge_base_id}/releases/{knowledge_base_release_id}/deletion-eligibility`。公开行为只读取 exact Release 生命周期、active/deregistered Reference 汇总和 TDD-03F 删除资格；KSS 需要 `knowledge_source.view`，BFF 需要同名全局 named permission。BFF 返回独立的 secret-free `knowledge-service-release-deletion-eligibility.v1` 投影，不返回 KSS operator token、Secret Handle、endpoint、外部资源 ID、artifact authority/assessment ID 或 raw problem。生产组合只接 PostgreSQL 生命周期事实；在没有生产 artifact-retention authority 时，ordinary retired Release 必须返回 `artifact_retention_unverified`，不得推断可删除。本片同时扩展既有 Release 列表投影以读取 `deprecated/revoked`，但不增加 lifecycle command、Reference 明细、通知、Dashboard 命令或页面、物理删除、角色管理页面、SQL/migration、部署、生产配置或 Git 操作。

[FRAME | HIGH] 2026-08-29 用户确认继续 TDD-04B 核心管理 tracer。本片在既有 KSS Profile/同步权威之上增加 ProofAgent guarded management client 与同源 BFF：Profile 创建、current/exact revision 读取、revision CAS 编辑、校验、发布，以及 exact Published Profile synchronization 的提交和状态读取。读取检查 `knowledge_source.view`，变更检查 `knowledge_source.edit`；所有变更精确转发 `Idempotency-Key`，同步首次创建保留 `202`，相同命令重放保留 `200`。请求只允许结构化 HTTPS 配置和 versioned Secret Handle 引用；浏览器响应移除 endpoint、Secret Handle、egress/trust 引用、KSS token 与 raw problem/detail/trace，非法请求统一返回不回显输入的安全 `422`。本片不增加 Dashboard 页面、真实 Vault/egress/TLS reader、生产进程切换、终端操作者到 KSS audit 的委托身份链、Base Draft/Preparation BFF、lifecycle/Reference command、SQL/migration、部署、生产配置或 Git 操作。

[KNOWN | HIGH] TDD-04B 本地实现已完成。ProofAgent BFF → guarded client → KSS management HTTP → PostgreSQL 的纵向合同证明 Profile `draft → validated → published`、同步首次 `202`/重放 `200` 和 queued 状态读取保持 exact identity，且浏览器投影不泄漏连接配置。KSS 加 ProofAgent 影响集为 440 passed；完整真实依赖后端为 2429 passed、24 个既有声明 skip、2 deselected，显式 Hybrid integration 另有 2 passed。OpenAPI 与 migration bytes/head 未变化。该证据只支持 `LOCAL_VERIFIED`，不支持部署或 Production GO；详见报告第 26 节。

[FRAME | HIGH] 2026-08-29 用户要求继续下一切片，进入 TDD-04C Base Draft → Preparation 管理 tracer。本片复用既有 KSS Draft/Preparation 权威，只增加 ProofAgent guarded management client 与同源 BFF：保存 Base Draft、按 exact revision 读取 Draft、按 exact Draft revision 启动 Preparation、读取 exact Preparation 当前状态。路径持有 Space/Base identity，浏览器 body 只提交 `expected_revision + members` 或 `draft_revision`；client 注入并核对 KSS scope。读取检查 `knowledge_source.view`，变更检查 `knowledge_source.edit`，写命令精确转发 `Idempotency-Key`；KSS start 首次与重放都保持 `202` 和原始 queued admission receipt。公开投影只含 Draft/Version/Preparation exact identity、digest、成员、状态与安全终态字段，不返回 KSS token、Worker identity、fencing token、lease deadline、artifact reference 或 raw failure detail。本片不增加 Worker/调度、publish/cancel/expiry command、Preparation audit、Dashboard 页面、SQL/migration、生产进程、部署、生产配置或 Git 操作。

[KNOWN | HIGH] TDD-04C 本地实现已完成。真实纵向合同证明 ProofAgent BFF → guarded client → KSS HTTP → PostgreSQL 可保存并读取 exact Draft revision、幂等启动并读取 queued Preparation，且不会产生 Release。37 个 focused BFF/client 合同、115 个受影响合同、2445 个全仓后端合同及 2 个显式 Hybrid integrations 通过；保留 24 个既有声明 skip 和 2 个默认排除。Mypy 454 个产品源、Ruff lint/format、根/KSS lock、domain/diff、TypeScript、Dashboard 225、Chat 35 与全部前端 build 通过。没有修改 KSS OpenAPI、migration 或依赖；该证据只支持 `LOCAL_VERIFIED`，不支持部署或 Production GO；详见报告第 27 节。

[FRAME | HIGH] 2026-08-29 用户要求做好验证、聚焦目标并继续下一切片，进入 TDD-04D one-shot Preparation execution responsibility。本片只在 KSS application/runtime composition 增加一个可选 `BasePreparationExecutionConfiguration` 和 `run_once()` handle：服务端配置独立 Worker identity、lease duration 与 candidate TTL；一次调用最多领取并处理一个 queued 或可接管 running Preparation，复用既有 frozen-plan builder、数据库租约、monotonic fence 和 `ready/failed` 原子提交。API runtime 默认不启用 execution；重建 execution runtime 可继续处理同一 durable queue。本片不增加 CLI、常驻循环、process role、batch、自动重试、publish/cancel/expiry BFF、Dashboard、SQL/migration、OpenAPI、部署、生产配置或 Git 操作。

[KNOWN | HIGH] TDD-04D 本地实现已完成。真实 BFF → KSS → PostgreSQL tracer 先由默认 API runtime 保存 queued Preparation，再由重建的 execution runtime 执行一次并得到 ready；浏览器投影仍无 Worker/artifact 字段，Release catalog 仍为空。one-shot 容量和非法 TTL 合同通过；Preparation 核心、真实 PostgreSQL lease/fence/recovery 与 runtime composition 聚焦回归为 160 passed，完整 KSS/ProofAgent KSS 影响集为 460 passed。全仓后端为 2449 passed、24 个既有声明 skip、2 deselected，2 个显式 Hybrid integrations 另行通过。Mypy 454 个产品源、全量 Ruff、受影响格式、domain/diff、根/KSS lock、TypeScript、Dashboard 225、Chat 35 和全部前端 build 通过。没有修改 OpenAPI、migration、依赖或 process role；该证据只支持 `LOCAL_VERIFIED`，不支持部署或 Production GO；详见报告第 28 节。

[FRAME | HIGH] 2026-08-28 用户确认 TDD-02G 精确契约。本片只增加可信 application-only `cancel(preparation_id, operator_id, idempotency_key)`：仅 queued/running 可原子进入 cancelled，使用数据库时间，状态、幂等收据和成功审计同事务提交；running 取消清除 owner/deadline 并保留 fence，使旧 Worker 后续提交稳定失败。ready/failed/expired/consumed/cancelled 不可取消；无自由文本原因、artifact 删除、重试、quarantine、HTTP/BFF、部署、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-02G 本地核心已完成。新增 `0013_preparation_cancellations.sql` 和 secret-free `CancelledReleasePreparation` 读取 schema；八路同 key 并发返回同一终态/一条审计，queued claim 与取消竞争线性化，在途 Builder 的旧 claim 不能提交，审计失败时状态与收据整体回滚，`0012 → 0013` active-running 升级和 migration 重放通过。Preparation/PG/distribution 回归为 170 passed；完整真实依赖受影响回归为 357 passed、0 skipped。取消命令仍未接 HTTP，异常 ready quarantine 仍是独立后续权威；详见报告第 18 节。

[FRAME | HIGH] 2026-08-28 用户要求继续下一切片。本片保持核心优先，不增加 SQL、公开状态、HTTP/BFF 或常驻进程；复用 `0012` 实现可信服务端 `expire_next(operator_id)`，每次按数据库时间、确定性顺序和 `SKIP LOCKED` 原子回收一个到期 ready candidate，并写入既有生命周期审计。

[KNOWN | HIGH] TDD-02F 已完成本地 one-shot 主动过期。新增一个内存合同和六个真实 PostgreSQL 合同，覆盖未到期/精确边界、非法 actor、八路并发、锁跳过、审计失败回滚、候选损坏失败关闭及 publish 竞争。Preparation 内存与 PostgreSQL 合同为 133 passed；完整真实依赖受影响回归为 339 passed、0 skipped。没有新增 migration、OpenAPI、自动调度、publish/expiry HTTP、ProofAgent 接线、生产配置或 Git 操作；详见报告第 17 节。

[FRAME | HIGH] 2026-08-28 用户要求继续下一分片并聚焦核心功能。本片实现 `ready → expired` 和一次性 publication CAS：最终数据库时间到期判断、exact candidate 纯校验、Release header/有序成员、`consumed` 或 `expired` 状态及生命周期审计在同一 PostgreSQL 事务内提交。只做本地应用/仓储/migration/合同，不新增 HTTP、BFF/Dashboard、角色接线、调度器、取消、部署、生产配置、生产 SQL 或 Git 操作。

[KNOWN | HIGH] TDD-02E 核心实现与隔离回归已完成。新增 `0012`，不改写 `0009` 至 `0011`；可信应用 Interface 可消费一个未到期 ready candidate，精确到期会持久化 expired 后返回稳定错误。相同 queryable Release 仅在 header、artifact、ordered members、projection 和状态全量相等时复用，并持锁至消费提交；retired、部分或冲突记录失败关闭。后续合法退役不破坏 consumed 历史或原始 queued 回执。该切片的完整受影响回归为 332 passed、0 skipped；详见报告第 16 节。TDD-02E 当时没有 publish HTTP、主动 reaper、cancel 或 ProofAgent 接线；TDD-02F 后续只补充 application-only one-shot 主动过期，仍未增加自动调度或其他接线。

[FRAME | HIGH] 2026-08-27 用户单独确认 TDD-02D 新 SQL、构建 Interface、仓储和管理状态合同调整：只按 frozen plan 构建 immutable candidate；最终 `ready/failed` 结果在短事务中校验 owner、lease、fencing token 和完整 admission。仅本地开发与隔离测试，不发布 Release、不部署、不改生产配置、不提交 Git。

[KNOWN | HIGH] TDD-02D 已完成本地候选构建和最终结果 fencing。新增 `0011`，不改写 `0009/0010`；GET 可读取 `ready/failed`，POST 重放仍保留原 `queued` 回执。新增 12 项行为合同，完整真实依赖回归为 316 passed、0 skipped。没有常驻 Worker、`ready → expired`、一次性 publication、孤立 artifact 回收或 ProofAgent 接线证据；详见报告第 15 节。

[FRAME | HIGH] 2026-08-27 用户单独确认 TDD-02C 新 SQL、配套仓储和管理状态合同调整：实现 Worker 领取、续租、超时接管、旧 claim fencing、状态推进后的原始回执保护与原子审计；验证真实 PostgreSQL 并发、迁移和安全投影。仅本地开发与隔离测试，不部署、不改生产配置、不提交 Git，不接构建或 Release 发布。

[KNOWN | HIGH] TDD-02C 已完成本地租约协调。新增 `0010`，不改写 `0009`；GET 读取 queued/running，POST 重放保留原 queued 回执。新增 26 项合同，完整真实依赖回归为 304 passed、0 skipped。没有常驻 Worker、构建、终态或 artifact 发布 fencing 证据；详见报告第 14 节。

[FRAME | HIGH] 2026-08-26 用户单独确认 TDD-02B 新 SQL、PostgreSQL 仓储和管理 API，限定本地开发与测试。以已实现的应用接口为入口，持久化 Draft 历史、exact Base Version、queued Preparation、幂等回执及审计；验证跨连接并发、一致 catalog 视图、应用重建读取和 HTTP 权限/安全投影。可补显式本地运行组合与打包合同，不启用生产进程、不执行生产 SQL、不改部署配置。Worker、取消/过期、ready/consumed 和一次性发布不在本轮范围。

[KNOWN | HIGH] TDD-02B 本地实现与回归已完成：新增 22 项 PG/HTTP 合同，真实 PG/MinIO/OpenSearch 受影响回归为 278 passed、0 skipped。详见 `tdd-report.md` 第 13 节；调用顺序见 `base-preparation-local-guide.md`。持久化 `queued` 不表示 Worker 已运行或 Release 可查询。

[FRAME | HIGH] 2026-08-26 按用户「继续下一 TDD 切片」进入 TDD-02A 本地核心：通过应用接口维护 Base Draft revision，并在启动 Preparation 时原子冻结 exact Source Version 组合和 `queued` 资源。先验证混合 Source 主路径，再覆盖重复/跨作用域/缺少 ready version、stale revision、幂等与并发。只新增核心合同、应用、仓储接口和测试用内存实现；不改 SQL、部署配置、HTTP、现有直接 Release 发布路径或生产进程。TDD-01 真实上游缺口不因此关闭；本轮不宣称完整 TDD-02 已交付。

[KNOWN | HIGH] TDD-02A 历史结果为核心 51 项测试通过、受影响回归 212 passed、44 skipped；当时跳过项缺少隔离 PG/S3/search 参数，事务证据仅来自内存仓储。后续 TDD-02B 已获独立确认并补持久化证据，不改变这次历史结果；日志摘要见 `tdd-report.md` 第 12 节。

[KNOWN | HIGH] 2026-08-26 用户已单独确认 TDD-01B SQL 与跨模块接线范围，限定本地实现和测试。TDD-01A 核心已接入 PostgreSQL migration/repository、受保护管理 HTTP、显式受管 Worker 和 Source Version 不可变 lineage。静态 v1 与受管 v2 使用互斥运行组合，不重写旧任务，不 fallback。真实策略/Secret/egress/TLS adapter、生产进程切换和 ProofAgent BFF/Dashboard 尚未完成，Feature 维持 `PARTIAL_VERIFICATION`。完整证据见 `tdd-report.md`，接口顺序见 `connection-profile-local-guide.md`。

| 设计树节点 | 场景 | 类型 | 优先级 | 数据要求 | 对应任务 |
| --- | --- | --- | --- | --- | --- |
| MAIN-1 | 外部连接配置、同步和 Source Version | contract/security | P1 | synthetic endpoint、Secret provider fake 与 deployment policy fake | TDD-01、TDD-04 |
| MAIN-2 | 多 Source Release preparation/publish | state/concurrency | P1 | 小型文档和结构化 fixtures | TDD-02 |
| MAIN-3/4 | Draft → Formal Candidate | authority/concurrency | P1 | exact revision、retired Release、profile mismatch | TDD-05 |
| MAIN-5 | Phase F/smoke/activation | transaction/integration | P1 | fake evidence authority 与 online KSS | TDD-05、TDD-07 |
| BRANCH-1/2/3 | fail-closed、race、rollback | negative/recovery | P1 | deterministic failure injection | TDD-03、TDD-06、TDD-07 |

## 12. ADR 判断

| 项 | 内容 |
| --- | --- |
| 是否需要 ADR | 是，已新增 ADR-0212 至 ADR-0217 |
| 判断理由 | 正式候选根、外部连接权威、Base 组合、Release 生命周期、跨客户端引用和 Preparation 状态合同都难逆且涉及真实取舍；首期角色包复用 ADR-0103、ADR-0126 和 ADR-0174，无需单独 ADR |
| 涉及决策点 | Draft revision、KSS candidate、Connection Profile revision、Base Draft、Source selection policy、Knowledge Base Version、Release Preparation state/fencing、Release deprecation/retirement/revocation、Reference Ledger、Secret Handle、Egress Policy、deployment Binding Profile、Phase F、online smoke、PostgreSQL activation |

## 13. 知识沉淀与上下文更新

| 目标文档 | 更新类型 | 内容摘要 | 处理方式 | 确认状态 |
| --- | --- | --- | --- | --- |
| `docs/domain/agent-configuration/CONTEXT.md` | 术语 | Formal Production Agent Candidate | 已更新 | 用户已确认 |
| `docs/domain/agent-configuration/decisions.md` | 歧义记录 | 完整流程包括正式发布，但保持三类权威分离 | 已更新 | 用户已确认 |
| `docs/adr/0212-bind-formal-production-publication-to-an-exact-draft-revision.md` | ADR | 正式 publisher 消费 exact Draft revision | 已新增 | accepted design，未实现 |
| `docs/domain/knowledge-evidence/CONTEXT.md` | 术语 | Connection Profile 与 Published Profile Revision | 已更新 | 用户已确认 |
| `docs/domain/knowledge-evidence/decisions.md` | 歧义记录 | KSS、Vault 与部署策略分权 | 已更新 | 用户已确认 |
| `docs/adr/0213-manage-source-connection-profiles-in-kss-with-external-secret-and-egress-authority.md` | ADR | KSS 管理非敏感 Profile revision，外部权威保留 secret 与 egress 策略 | 已新增 | accepted design，未实现 |
| `docs/adr/0214-resolve-versioned-knowledge-base-drafts-at-release-preparation-start.md` | ADR | Base Draft selection policy 在 Preparation 启动时冻结为 exact Knowledge Base Version | 已新增 | accepted design；Draft/Version/Preparation 核心及 TDD-04C Draft save/exact read、Preparation start/status BFF 已实现，执行/发布闭环未实现 |
| `docs/adr/0215-separate-release-deprecation-retirement-and-emergency-revocation.md` | ADR | 正常 deprecated/retired 与紧急 revoked 分离 | 已新增 | accepted design；TDD-03B 至 03E 已实现 application-only deprecate、可信 Reference 注销准入、ordinary retire 与 emergency revoke 核心，产品接线待实现 |
| `docs/adr/0216-register-executable-client-release-references-in-kss.md` | ADR | KSS Reference Ledger 是普通退役的本地权威 | 已新增 | accepted design；TDD-03A 至 03F 已实现 registration、可信 deregistration admission、零 active Reference retirement/deletion-eligibility gates 及 revocation 竞态收敛，ProofAgent verifier/background reconciler 待实现 |
| `docs/adr/0217-use-a-durable-one-use-release-preparation-state-machine.md` | ADR | durable Preparation、one-use ready candidate 与 fenced Worker 状态机 | 已新增 | accepted design；核心状态/事务、application-only cancel/expiry/publication、TDD-04C start/status BFF、TDD-04D one-shot execution runtime、TDD-04E controlled publish BFF、TDD-04F controlled cancel BFF、TDD-04G bounded audit read BFF 与 TDD-04H exact-resource expiry BFF 已实现；常驻执行进程和自动过期调度待实现 |
| `docs/domain/knowledge-evidence/CONTEXT.md` | 术语 | 三类可叠加 Hybrid Knowledge Configuration Role Bundle | 已更新 | 用户已确认 |
| `docs/domain/knowledge-evidence/decisions.md` | 歧义记录 | 首期不做复杂 RBAC 或强制四眼，复用全局 named permission 映射 | 已更新 | 用户已确认 |
| `docs/PROJ_CONTEXT.md` | Feature 索引 | TDD-01A/01B、TDD-02A 至 02G、TDD-03A 至 03F、TDD-04A 至 04H 与 TDD-05A 至 05R 本地执行状态为 `PARTIAL_VERIFICATION`，不是生产切换证据 | 已更新 | 当前事实 |

[KNOWN | HIGH] TDD-04E 已在既有 Scope 内完成 controlled Preparation publication BFF：
KSS 管理入口与 ProofAgent 同源入口均为 no-body `POST :publish`；BFF 要求
`knowledge_source.edit`，KSS 要求可信 operator authentication，成功
返回 consumed current-state projection 与同一 Preparation `Location`。它复用既有 one-use
PostgreSQL CAS，不新增 Idempotency-Key；响应不确定或重复调用时以 GET exact Preparation
恢复权威状态。权限、路径漂移、到期、重复消费、wire drift、secret-free projection 和真实
PostgreSQL 纵向合同已有本地证据。Dashboard、cancel/expiry BFF、常驻进程、Agent formal
publication、部署和生产配置均未纳入本片。

[KNOWN | HIGH] TDD-04F 已在同一既有 Scope 内完成 controlled Preparation cancellation
BFF：KSS 管理入口与 ProofAgent 同源入口均为 no-body `POST :cancel`，并要求
`Idempotency-Key`；BFF 额外要求 `knowledge_source.edit`，KSS 使用可信 operator identity
作为幂等作用域。成功返回 cancelled current-state projection 与同一 Preparation
`Location`。exact replay 复用原结果且只有一条成功审计；key 改绑、终态新命令、路径
Scope 漂移、body 和上游 identity/state/Location 漂移均失败关闭。该命令复用既有
PostgreSQL database-time cancellation/fencing 事务，没有新增 migration、取消状态权威或
浏览器 operator 输入。Dashboard、expiry BFF、常驻进程、artifact cleanup、ready
quarantine、Agent formal publication、部署和生产配置均未纳入本片。

[KNOWN | HIGH] TDD-04G 已在同一既有 Scope 内完成只读 Preparation audit 同源 BFF：
ProofAgent 新增 `GET .../preparation-audit`，只接受 `knowledge_source.view`，并通过 guarded
client 读取 KSS 既有 audit collection。client 严格校验 wire schema 与 exact Space/Base，
将 success/rejection 合并为时间有序、secret-free 投影，使用 `offset=0..20000`、
`limit=1..100` 的有界页，并把可识别 actor 明确标记为 `kss_service_operator`。该 actor 是
KSS 收到的可信服务身份，不是浏览器或终端操作者；本片不伪造委托链。当前分页基于单次
KSS 当前快照，不是稳定 cursor；当前 Base audit 也不合并 Worker 或 publication audit。
本片没有新增 KSS SQL、migration、OpenAPI、写命令、Dashboard、连续进程、expiry、artifact
cleanup、Agent formal publication、部署或生产配置。

[KNOWN | HIGH] TDD-04H 已在同一既有 Scope 内完成 exact-resource Preparation expiry
BFF：KSS 管理入口与 ProofAgent 同源入口均为 no-body `POST :expire`，并要求既有
`knowledge_source.edit`。KSS 在变更前读取 exact Preparation 并核对路径 Scope，随后使用
数据库时间、行锁和既有 publication audit 原语，把一个已到期 ready 原子推进为 expired；
不会创建 Release。重复请求直接返回同一 durable expired 终态，不新增 Idempotency-Key、
第二份回执或重复审计；不确定响应由 exact GET 或相同 exact 命令恢复。网络合同不公开
`expire_next()`，避免重试时选中另一资源。not-due、非 ready、body、权限、Scope 和上游
identity/state/Location 漂移均失败关闭。本片没有新增 SQL、migration、依赖、scheduler、
continuous process、Dashboard、artifact cleanup、Agent formal publication、部署或生产配置。

[FRAME | HIGH] 2026-08-30 用户确认进入 TDD-05A Formal Production Agent Candidate
tracer。本片只新增一个无副作用的 Control 装配入口：以调用方提交的 named Agent、exact
Draft ID 和 exact Draft revision 为候选根，从 Agent Configuration Store 读取该 Draft，使用
既有 publication-configuration projector 对 live KSS catalog 做完整重验，再把 Draft 内 exact
Space/Base/Base Version/Release 与 deployment-owned Production KSS Binding Profile 组合为一个
不可变、可摘要的 Formal Production Agent Candidate。Binding Profile 只持有 binding identity、
versioned Knowledge credential handle、Admission Scorer identity/revision 和 required failure mode，
不得携带或替换 Release identity。Draft 缺失、revision 漂移、catalog 不可用、Release 不再
queryable、authoring blocker 或非 versioned Knowledge credential 均失败关闭。本片不修改既有
publisher 输入，不注册 KSS Reference，不生成 Phase F Release Record，不执行 online smoke、
Published Version 写入、Active pointer CAS、HTTP/CLI/Dashboard、production composition、环境配置、
SQL、migration、部署或 Git 操作；后续切片才把该候选接入正式 publisher 并逐步移除独立
manifest/environment Release 候选路径。

[KNOWN | HIGH] TDD-05A 已按上述边界完成。新增 strict Production KSS Binding Profile、
immutable Formal Production Agent Candidate 和 Control-owned assembler。候选绑定 exact
Agent/Draft/revision、Contract Bundle、Draft KSS tuple、live catalog revision、resolved binding、
既有 Knowledge Release candidate digest 与包含 Draft revision 的 formal candidate digest；相同
Contract/Release/Profile 在不同 Draft revision 下保持前者稳定、后者变化。stale/missing Draft、
catalog failure/unversioned snapshot、deprecated 或 parent tuple 漂移、Profile 夹带 Release、
非 versioned Knowledge credential 均失败关闭。现有 publisher、production composition、Reference、
Phase F、smoke、Published Version 与 Active pointer 未改动。

[FRAME | HIGH] 2026-08-30 用户要求提交 Git 后继续下一切片，进入 TDD-05B
candidate-bound Phase F preparation。本片新增一个无持久化副作用的 Control 入口，只接受
TDD-05A `FormalProductionAgentCandidate`、四类 exact evidence 和可信 actor。入口先重验
Formal Candidate 的 Knowledge Release digest 与 formal digest，再封装同时绑定两类 digest 的
immutable Formal Phase F Record，交给独立 Phase F authority 验证；通过后输出独立的
Provisional Production Agent Version 与 preparation result。Provisional contract 使用
`prepared_at/prepared_by`，不得复用 `PublishedAgentVersion` 或声称已发布，并保留 exact Draft
revision、KSS binding、Phase F record、Workflow Stage 可用性和有效配置。candidate tamper、
evidence 重复/漂移、authority exception/deny、无可用 Workflow Stage 均失败关闭。本片不修改
现有 `ProductionAgentPublicationService`，不写 Agent Store/audit，不注册 KSS Reference，不执行
online smoke、Published Version 写入、Active pointer CAS、HTTP/CLI/Dashboard、production
composition、配置、SQL、migration、部署或 Git 提交；后续切片再把 preparation 接入唯一正式
publisher，并按 Reference-first 顺序继续。

[KNOWN | HIGH] TDD-05B 已按冻结边界完成。Control 现在重验 Formal Candidate 的两类 digest，
解析该候选的 Workflow Stage 配置，把四类互不相同的 exact evidence 封装为同时绑定 formal 与
Knowledge Release digest 的 immutable Phase F Record，并在独立 authority 明确批准后返回
`ProvisionalProductionAgentVersion`。篡改候选、重复或漂移 evidence、不可解析 Workflow、
authority deny/exception 均失败关闭。实现没有持久化副作用，也没有新增 Reference、smoke、
Published Version、Active CAS、Delivery、配置或部署行为。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05C Reference-first formal publication
staging。本片新增一个 application-only Control 入口，只接受 TDD-05B
`FormalProductionAgentPhaseFPreparation` 和注入的 KSS Reference registrar port。入口在任何
跨服务调用前重验 candidate、Phase F Record 与 preparation 的 exact identity，再以 provisional
version ID 作为 immutable `published_agent_version` external resource，为 Draft-owned exact
Space/Base/Release 构造 `execution_or_rollback` Reference 请求。幂等 key 由 Control 根据 exact
version ID 确定性生成，不接受调用方选择；相同 preparation 重放必须恢复同一 active Reference。
注册失败不得返回 staging；上游回执的 Scope、Release、external resource、purpose 或 active
state 漂移必须失败关闭。注册已成功但回执不可验证时保守保留 KSS Reference，视为可对账孤儿，
不得补偿性注销。本片不新增 KSS HTTP/BFF/production adapter，不写 Agent Store/audit，不执行
online smoke、`PublishedAgentVersion` 写入、Active pointer CAS、Delivery/Dashboard、production
composition、配置、SQL、migration、部署或 Git 提交，也不修改现有 publisher。

[KNOWN | HIGH] TDD-05C 已按上述边界完成。Control 以 exact provisional version ID 生成稳定
幂等 key，并通过注入 registrar port 提交 strict Space/Base/Release、
`published_agent_version` external resource 和 `execution_or_rollback` purpose。返回的 active
Reference 必须与请求逐项一致；上游异常映射为稳定错误且不泄漏 detail。相同 preparation
重放恢复同一 Reference；回执漂移在注册后失败关闭并保守留下可对账孤儿。为防止 Reference
目标漂移，Phase F Record 同时绑定 provisional version ID 与 validation run ID，stager 在跨服务
调用前重验该 Record。当前只有 port 合同和本地 fake 证据，没有 KSS HTTP/真实 registrar、
Agent 持久化、smoke、激活或生产接线。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05D authenticated Reference registration
transport。本片在 KSS public client API 新增
`POST /v1/knowledge-base-release-references`。请求必须使用现有 Bearer client authentication 和
`Idempotency-Key`；authenticated client ID 只来自服务端认证结果，不接受 body/header 自报。
Body 使用既有 strict `RegisterKnowledgeBaseReleaseReferenceRequest`，只包含 exact
Space/Base/Release、固定 `published_agent_version` external resource kind、exact external resource
ID 和固定 `execution_or_rollback` purpose。命令是 idempotent ensure，首次注册和精确重放均返回
`200` 与同一 active Reference；冲突、Release 不可采用、Scope 漂移、无效 key、认证失败和存储/
完整性失败映射为稳定、无输入回显的 problem contract。

[FRAME | HIGH] ProofAgent 本片新增独立 guarded registrar adapter，使用 HTTPS origin、
`GuardedHttpClient` 和专用 client authorization factory；不得复用 Knowledge Operator credential
或 management client。Adapter 发送 exact JSON 与 Control 生成的 key，strict 解析 KSS wire
response，再映射为 TDD-05C `RegisteredProductionAgentReleaseReference`。KSS runtime 使用既有
PostgreSQL Reference repository 接线，canonical OpenAPI 必须包含新 route/schema。验证至少覆盖
KSS in-memory HTTP、ProofAgent guarded transport、认证/unknown-field/幂等/上游漂移负向合同，
以及隔离 PostgreSQL 的 ProofAgent → HTTP → KSS application → Reference Ledger 纵向路径。本片
不新增 SQL/migration、浏览器 BFF/Dashboard、formal publisher consumption、online smoke、Agent
Store/audit、Published Version、Active pointer CAS、reconciler/deregistration、生产 Secret/egress
配置、部署或 Git 提交。

[KNOWN | HIGH] TDD-05D 已按上述边界完成。KSS public client API 通过既有 Bearer client
authentication 和 `Idempotency-Key` 接受 exact Reference registration，authenticated client
identity 只取服务端认证结果；strict body、Release admissibility、Scope、幂等冲突和持久化失败
均使用无输入回显的稳定 problem contract。ProofAgent 新增独立 HTTPS guarded registrar，使用
专用 client authorization factory，strict 解析 KSS wire resource 并映射为 TDD-05C receipt；
KSS runtime 复用既有 PostgreSQL Reference repository。隔离 PostgreSQL 纵向已证明
ProofAgent → guarded HTTP → KSS runtime → Reference Ledger 的首次注册与 exact replay 收敛到
同一 active Reference 和一条审计。canonical OpenAPI 已包含新 route/schema。本片没有新增
SQL/migration、BFF/Dashboard、publisher consumption、online smoke、Agent Store/audit、Published
Version、Active CAS、reconciler/deregistration、生产 Secret/egress 配置、部署或 Git 提交。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05E exact online smoke Control。本片新增一个
application-only Control 入口，只接受 TDD-05D 已完成注册的
`FormalProductionAgentReferenceStaging` 和非空 smoke question。入口在调用外部 validator 前
重验 Formal Candidate、Phase F Record、provisional version 与 active KSS Reference 的完整
identity，并由 Control 构造 strict smoke request，固定绑定 agent、provisional version、
validation run、两类 candidate digest、exact Space/Base/Release 和 release Reference。validator
只能返回同一组 identity、运行 outcome、accepted citation count，以及互不相同的 exact trace/
receipt artifact；仅 `ANSWERED_WITH_CITATIONS` 且至少一条 accepted citation 可形成仍未发布的
online-smoke qualification。validator exception、unknown/malformed result、identity drift、零引用、
非引用回答或 trace/receipt 混用均失败关闭，不泄漏上游 detail。

[FRAME | HIGH] 本片用结构性边界保证失败顺序：smoke service 不接受 Phase F preparation 代替
registered staging，也不注入 Agent Store、Active pointer、audit writer 或 KSS deregistrar。
因此 smoke 失败或结果不确定时不能写 `PublishedAgentVersion`、不能更新 Active pointer，也不能
补偿性注销已成功注册的 KSS Reference；该 Reference 保留为可对账的保守孤儿。本片不实现真实
online runner adapter、Store transaction、activation CAS、formal publisher cutover、HTTP/CLI/
Dashboard、Delivery、reconciler/deregistration、生产 Secret/egress、配置、SQL、migration、部署或
Git 提交。

[KNOWN | HIGH] TDD-05E 已按上述边界完成。Control 只从完整、active 的 registered staging
构造 exact smoke request，并把 agent、provisional version、validation run、两类 candidate
digest、Space/Base/Release、Reference ID 和规范化 question 一并交给单一 validator port。只有
identity 完全一致、`ANSWERED_WITH_CITATIONS`、accepted citation count 至少为 1，且 trace/
receipt exact artifact 互不相同的结果，才能形成不含 publication/activation 声明的 strict
qualification。非法 staging、空白 question、validator exception、失败 outcome、零引用、结果
漂移或 evidence 混用均稳定失败关闭且不泄漏上游 detail。service 没有 Store、Active pointer、
audit writer 或 KSS deregistrar 依赖；失败后已注册 Reference 保留。本片没有真实 runner adapter、
Published Version、Active CAS、publisher cutover、Delivery、Dashboard、部署或 Git 提交。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05F formal publisher core。本片新增后续唯一
正式入口的 application-only 目标实现，按既有 Control 服务依次执行 exact Draft/KSS/Profile
candidate assembly、candidate-bound Phase F、Reference-first staging 和 exact online smoke。Phase F 通过后、
Reference 注册前，publisher 使用一个短只读 Configuration UoW 读取当前 Active Agent Version，
冻结 `ActiveAgentPointerExpectation` 后立即关闭事务；Reference 和 smoke 等外部调用期间不得持有
数据库事务。

[FRAME | HIGH] smoke 通过后，publisher 从 exact provisional version 构造 immutable
`PublishedAgentVersion`。版本新增单一 strict formal-publication evidence envelope，保留 exact Draft
revision、Formal Phase F Record、active Release Reference receipt 和 online smoke result，并要求
version/run/Release/Reference identity 完全一致。最终一个 Configuration UoW 必须同时执行 Draft
revision check、Active pointer CAS、Published Version/activation 写入和 trace-safe publication audit；
仅全部成功后 commit。Draft 或 Active pointer 漂移、audit/storage exception 均回滚，不留下部分
Published/Active/audit 状态；已经注册的 KSS Reference 继续保留，不做补偿性注销。

[FRAME | HIGH] 本片复用既有 PostgreSQL repository/UoW，不新增 SQL 或 migration，也不修改旧
manifest-based publisher、HTTP/CLI/Dashboard、Delivery、runtime、reconciler/deregistration、生产
Secret/egress、配置或部署。真实 online runner、公开 formal publication command 与持久化
Idempotency-Key receipt 留到后续独立切片；因此本片不能被当作可安全重试的网络发布入口或
Production GO。本片不执行 Git 提交。

[KNOWN | HIGH] TDD-05F 已按上述边界完成并本地验证。新的 formal publisher core 在 Reference
注册前通过短只读 UoW 冻结 Active expectation，外部 Reference/smoke 调用期间不持有数据库事务，
并在 smoke 成功后通过一个最终 UoW 原子提交 immutable Published Version、Active pointer CAS 与
publication audit。Published Version 保留 exact Draft revision、Phase F Record、active Reference
receipt 和 online smoke result 的 strict evidence envelope。Draft/Active 并发漂移、audit/storage
失败均不留下部分 Version/Active/audit 状态；已注册 Reference 继续保留。旧 manifest publisher、
真实 online runner、公开且持久化幂等的正式发布命令和 runtime composition 尚未切换，因此
TDD-05F 为 `LOCAL_VERIFIED`，Feature 仍为 `PARTIAL_VERIFICATION`。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05G real online smoke runner adapter。本片只
关闭“如何把 TDD-05E strict request 和已验证 staging 交给现有 governed execution，并形成 exact
Trace/Receipt/citation result”的缺口。`FormalProductionAgentOnlineSmokeValidator` port 增加同一
`FormalProductionAgentReferenceStaging` 参数；Control 仍先完成 staging/request 的 exact identity
校验，runner 也必须在执行前重验 agent、version、run、两类 candidate digest、Space/Base/Release
和 Reference identity，不引入按 ID 查找 mutable candidate 的全局注册表。

[FRAME | HIGH] runner 从 provisional version 的 immutable `ContractBundle` 在私有临时目录生成
只读 Agent package，路径校验必须拒绝绝对路径、反斜杠、空段、`.`、`..`、NUL 和 core contract
shadow。它以 `RunPurpose.VALIDATION`、exact validation run ID、exact resolved KSS binding、冻结的
Workflow Stage runtime facts 与部署注入的 Institution Authorization 调用现有 governed execution。
完成的 run 只统计同时具有 `accepted` 状态和非空 citation 的 Evidence Chunk；Trace 与 Receipt
必须是非空、有限大小的普通文件，并分别写入 immutable artifact store 后 exact read-back。runner
返回 strict `FormalProductionAgentOnlineSmokeResult`；是否达到 cited-answer Gate 仍由 TDD-05E
Control 决定。

[FRAME | HIGH] 执行、materialization、artifact 限界或 read-back 异常全部失败关闭，由 Control
映射为不泄漏内部 detail 的稳定错误。临时 package 与本地 RunStore 在调用结束后清理；已经注册
的 KSS Reference 不变。失败 run 已写入的 immutable Trace/Receipt 可以作为运行诊断事实，但不是
publication evidence，也不授权激活。本片不修改 SQL/migration、KSS API、公开 formal publication
command、持久化 Idempotency-Key receipt、旧 publisher composition、HTTP/CLI/Dashboard、Run
Executor、reconciler/deregistration、生产配置、部署或 Git 提交。

[KNOWN | HIGH] TDD-05G 已按上述边界完成并本地验证。新增 concrete
`FormalProductionAgentOnlineSmokeRunner`，它重新验证 strict request 与完整 staging，从 provisional
`ContractBundle` 安全物化私有只读临时 package，并以 `RunPurpose.VALIDATION`、exact validation
run ID、exact KSS binding、冻结的 Workflow Stage runtime facts 和注入的 Institution Authorization
复用既有 governed execution。只有 `accepted` 且 citation 非空的 Evidence Chunk 被计数；非空、
有限大小的 Trace/Receipt 分别写入 immutable artifact store 并完成 exact read-back。Control 继续
独占 cited-answer Gate，runner 不获得 publication/activation authority。identity 漂移、无有效引用、
artifact 回读失败和内部异常均失败关闭；临时 package/RunStore 清理，已注册 KSS Reference 保留。
本片没有新增 SQL、migration、KSS API、公开幂等发布命令、旧 publisher/runtime 切换、生产上游
联机证明、部署或 Git 提交，因此 TDD-05G 为 `LOCAL_VERIFIED`，Feature 仍为
`PARTIAL_VERIFICATION`。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05H durable formal publication command。
本片新增唯一一个受 `agent.publish` 权限保护的生产配置 API：
`POST /api/config/agents/{agent_id}/drafts/{draft_id}/formal-publications`。请求必须携带
`Idempotency-Key`，body 只包含 exact `draft_revision`、四类 `KnowledgeReleaseEvidenceSet` 和
规范化前的 `smoke_question`；Agent/Draft identity 来自 path，actor 来自可信 OIDC session，
`ProductionKssBindingProfile` 只由部署注入。strict body 拒绝 caller-selected Profile、Release、
provisional version、validation run、Reference、Active pointer、actor、publication timestamp 或
结果字段。

[FRAME | HIGH] Command 以 `(actor subject, Idempotency-Key)` 为作用域，并对 path/body 计算
canonical SHA-256。任何外部 Phase F、KSS Reference 或 online smoke 调用前，必须在短 PostgreSQL
事务中持久化 `in_progress` receipt；相同 key/fingerprint 的 terminal replay 返回原 receipt，
`in_progress` replay 返回同一资源和 `202` 且不得重复调用外部边界，不同 fingerprint 在外部调用前
返回稳定冲突。Idempotency-Key 不进入公共响应、audit metadata 或异常 detail。Receipt 只保留
command、Agent/Draft/revision、request digest、状态、时间、成功时的 version/run/Reference identity，
或失败时的稳定 code；不得保存或返回 raw smoke question、evidence payload、ContractBundle、Secret
Handle、上游 detail 或 artifact bytes。

[FRAME | HIGH] 成功路径必须在 TDD-05F 的最终 Configuration UoW 中，同时提交 immutable Published
Version、Active pointer CAS、publication audit 和 `succeeded` command receipt；receipt 写入失败必须
回滚全部本地最终状态。已准入命令在 publisher 返回稳定失败后，以独立短事务从 `in_progress`
转换为 `failed`；exact replay 返回同一 failure code，不重复 Phase F/Reference/smoke。若最终 commit
结果不确定，failure completion 必须先恢复已存在的 terminal receipt，不能把已成功命令降级为失败。
进程在 terminal receipt 前丢失时保守保留 `in_progress`，本片不自动超时接管或以同一 key 重跑；
该状态需要后续受信 reconciler。新 key 表示新命令，不能用来覆盖或修改旧 receipt。

[FRAME | HIGH] 本片新增 PostgreSQL command table、repository/UoW seam、strict application command
和可注入 HTTP 入口。它不把新入口接入 Dashboard，不删除或改写旧 manifest CLI publisher，不切换
Published Agent runtime/rollback，不增加 background reconciler、lease/takeover、command GET/list/
cancel、receipt deletion/retention job、KSS API、生产 Secret/egress 配置或部署，也不执行 Git 提交。
生产 API composition cutover 与真实上游联机仍需后续独立切片；因此本片即使本地通过，也不能称为
系统级唯一发布入口或 Production GO。

[KNOWN | HIGH] TDD-05H 已按上述边界完成并本地验证。公开命令现在以可信 actor 和
`agent.publish` 权限接收 strict path/body，先持久化 actor-scoped `in_progress` receipt，再在事务外
执行 exact formal chain；exact replay、changed-request conflict、process-exit in-progress、稳定失败
和 terminal non-downgrade 均有合同覆盖。`0022_formal_publish_cmd` 与 Configuration UoW 让成功
receipt 和 Version/Active/audit 原子提交。真实 PostgreSQL 迁移、仓储、UoW 和并发 9 项通过，
受影响集 170 项通过，最终全仓 2578 项通过。production concrete composition、stuck-command
reconciler、旧 publisher/runtime 切换、真实 KSS/model 联机与部署仍未完成，因此 TDD-05H 为
`LOCAL_VERIFIED`，Feature 仍为 `PARTIAL_VERIFICATION`，没有 Git 提交或 Production GO。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05I production composition cutover。本片只让
production API 从部署权威装配 TDD-05H 的 durable formal publication command：使用 PostgreSQL
Configuration UoW、live KSS catalog、deployment-owned `ProductionKssBindingProfile`、独立 Phase F
authority、专用且版本化的 KSS Reference service-client credential、TDD-05G governed online smoke
runner、immutable artifact store 和部署注入的 Institution Authorization。Draft 仍独占 exact
Release 选择；Profile 只提供 binding、credential 和 Admission Scorer identity，不能夹带 Release。

[FRAME | HIGH] `create_app(mode="production")` 必须把 formal publication command 列为强制依赖，
缺失时在应用启动阶段失败关闭；development 仍允许不注入并由既有 Delivery seam 返回不可用。
production API 是本片唯一正式发布 composition root。旧 `production-publish-agent` manifest CLI
及其 `compose_production_agent_publisher` production composition 必须移除，避免绕过 exact Draft、
durable command receipt 和 Reference-first chain；旧 application core 可暂留作历史兼容测试，但
不再有 production entry 或导出装配函数。

[FRAME | HIGH] 本片不增加 SQL/migration、command recovery/takeover、GET/list/cancel、Dashboard、
reconciler/deregistration、Release revocation runtime、真实 KSS/model 联机、production Compose/
Blue-Green 配置、secret 值、部署或 Git 提交。Composition 测试只证明依赖接线、专用凭据隔离、
启动失败关闭与唯一入口，不证明外部服务可用、生产发布成功或 Production GO。

[KNOWN | HIGH] TDD-05I 已按冻结边界完成并本地验证。production API 现在装配 PostgreSQL UoW、
live KSS catalog、deployment Profile、Phase F authority、dedicated versioned Reference client、
governed online runner 与 immutable artifact store，且 `create_app(mode="production")` 缺 command
即启动失败。旧 manifest `production-publish-agent` CLI 和
`compose_production_agent_publisher` 已移除。聚焦 16 项、受影响 180 项和 loopback-capable 全仓
2354 项均通过；267 个依赖条件 skip 不作为外部依赖证据。production-local 专用 Reference client
Secret/Grant、真实上游、stuck-command recovery、部署和 Production GO 仍未完成，也没有 Git
提交。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05J production-local dedicated Reference client。
本片只补 checked-in production-local 的专用、版本化 Reference client Secret Handle、独立 Vault
fixture、KSS service-client identity bootstrap，以及一个隔离 PostgreSQL/KSS/ProofAgent registrar
纵向。KSS API 必须在该 client identity 幂等注册完成后启动；ProofAgent formal composition 使用的
Reference credential 必须与 operator credential、runtime query credential 使用不同 handle 和本地
fixture 值。纵向只注册一个 exact、queryable Release 的 `published_agent_version` Reference，并证明
receipt 中的 `authenticated_client_id` 来自该专用凭据。

[FRAME | HIGH] 当前 `knowledge_client_grants` 只表达 exact-Release Knowledge Query Grant；Reference
registration 目前以已认证 service-client identity 为授权边界。TDD-05J 不把 Query Grant 误称为
Reference Grant，也不为专用 Reference client 创建查询权限。纵向必须反证该 client 在没有 exact
Query Grant 时无法创建 Knowledge Query。action-scoped Reference Grant 若需要，必须由后续独立
设计和 migration 切片处理，不能隐含进本地部署 fixture。

[FRAME | HIGH] 本片不调用 formal publication endpoint，不创建或激活 Published Agent Version，
不运行真实模型或完整 online smoke，不新增 KSS 管理 API、Query Grant provisioning、SQL migration、
reconciler、Dashboard、恢复器、production Vault/egress/TLS 变更，也不启动或修改既有
`proofagent-production-local` 项目。验证只使用静态 Compose 合同、受控 fake 和独立 PostgreSQL
测试 schema；不读取 `.env`、secret 值、生产数据或生产日志，不执行部署或 Git 提交。

[KNOWN | HIGH] TDD-05J 已按上述边界完成并本地验证。production-local 现在声明专用、版本化
Reference client Secret Handle 和独立 Vault fixture；一次性 KSS bootstrap 在 migration 后、API
启动前幂等注册 `proof-agent-formal-publication-reference` identity。production composition 拒绝
Reference Handle 与 Operator/runtime Query Handle 复用，并补齐既有本地 Phase F evaluator origin。
隔离纵向证明该 client 可首次/重放同一 exact active Reference，且在没有 Query Grant 时调用 Query
稳定返回 `403`。受影响集 593 项通过、13 项依赖条件 skip；PostgreSQL-enabled 全仓 2588 项通过、
37 项依赖条件 skip、2 项 deselected。没有启动 production-local 全栈、正式发布、真实模型 smoke、
部署或 Git 提交；Feature 仍为 `PARTIAL_VERIFICATION`。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05K runtime Query client exact-Release
Grant provisioning core。本片只新增 KSS application-only、secret-free provisioning 接口，
复用既有 `knowledge_client_grants` PostgreSQL 权威。已注册 runtime client identity、允许
strategy、服务端预算上限和 effective access scope digest 必须在受信 KSS composition
时注入 immutable policy；每次调用只接受 Draft 后续传入的 exact Release identity，不接受
client、credential、预算、strategy 或 Knowledge Space。Space 必须由 KSS 通过 exact Release
权威反推并返回 secret-free receipt。

[FRAME | HIGH] Grant identity 必须由全部 immutable Grant facts 内容寻址生成。同一事实精确
重放返回同一 receipt；同一 runtime client 已绑定同一 exact Release 后，改变策略、
预算或 scope digest 不得原地扩权，必须冲突失败。隔离纵向必须证明 runtime
credential 只能在 exact Release 和 Grant 预算内创建 Query；越预算、其他 Release 以及
未获 Grant 的专用 Reference credential 均返回稳定 `403`。

[FRAME | HIGH] 本片不新增 SQL migration、KSS HTTP/管理 API、ProofAgent transport 或 formal
publisher composition，不改 Compose、Vault、egress/TLS 或 Dashboard，不调用 formal publication
endpoint，不运行真实模型、不部署且不提交 Git。验证只使用独立 PostgreSQL 测试
schema、本地 KSS HTTP application 和受控 fixture；不读取 `.env`、secret 值、生产数据或日志。

[KNOWN | HIGH] TDD-05K 已按上述边界完成并本地验证。KSS application-only provisioning core
只接受 exact `knowledge_base_release_id`，runtime client、strategy、预算和 scope 由 immutable
policy 注入，Space 由 KSS Release 权威反推。隔离 PostgreSQL/KSS 纵向证明 exact replay、
policy drift 冲突、预算上限、其他 Release 和 Reference credential 拒绝；最终全仓后端 2588 项
通过，37 项依赖条件 skip、2 项 deselected。没有 KSS provisioning HTTP、ProofAgent transport、
formal publisher composition、部署、Git 提交或 Production GO。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05L Query Grant provisioning transport。本片只在
既有 KSS operator 管理认证和 `knowledge_source.edit` 权限后增加
`POST /v1/knowledge-query-grants`。strict JSON 请求体只允许 Draft 后续选择的 exact
`knowledge_base_release_id`；runtime Query credential、Reference credential 或请求字段都不能选择
client、Space、strategy、预算或 scope。KSS runtime 只有同时注入 TDD-05K immutable policy 和
operator authentication 时才暴露该入口，否则启动或路由按配置失败关闭。

[FRAME | HIGH] ProofAgent 只新增独立 `KnowledgeQueryGrantProvisioner` port、secret-free strict
request/receipt 和 guarded HTTPS adapter。Adapter 必须拒绝非 HTTPS origin、redirect、非 200、
超限或未知响应字段、非 active receipt，以及与请求不一致的 Release；它不拥有或复制 KSS 的
client、Space、strategy、预算或 scope policy。KSS immutable authority 冲突映射为稳定 `409`，
receipt integrity failure 映射为稳定 `503`，且错误响应不得回显 bearer token 或伪造输入。

[FRAME | HIGH] 本片更新 canonical KSS OpenAPI 和本地合同测试，但不把 provisioner 接入 formal
publisher，不新增 SQL/migration、operator audit 表、Secret Handle、Compose/Vault/egress/TLS、
Dashboard/BFF 或 production 配置，不调用 formal publication endpoint，不运行真实模型、不部署且
不提交 Git。operator 级逐命令审计仍是命名残余风险；当前 durable Grant row/receipt 只证明授权事实，
不能替代未来审计证据或 Production GO。

[FRAME | HIGH] 2026-08-30 用户确认继续进入 TDD-05M candidate-bound Query Grant Control staging。
本片只在已验证 `FormalProductionAgentReferenceStaging` 之后新增 Control stager：从 Formal
Candidate 读取 exact `knowledge_base_release_id`，调用既有 provider-neutral provisioner，并严格
复核 active receipt 的 Release 与 Knowledge Space。online smoke 必须显式消费该 staging，不能再
直接从 Reference staging 进入执行。

[FRAME | HIGH] Grant 成功后若 smoke 或最终 publication 失败，TDD-05M 保留 KSS 中 exact、
policy-bounded 的 durable Grant，不伪造补偿撤销。该 Grant 不代表 Agent 已发布或激活；ProofAgent
仍独立授权用户侧运行，KSS 仍在每次 Query 时执行 exact-Release authorization。本片不增加
Grant revoke/reconciler、operator-command audit migration、新 Secret Handle、production-local
egress/TLS 配置、真实模型调用、部署或 Git 提交。具体决策见 ADR-0220。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05N production-local immutable Query Grant
policy/bootstrap。本片只让 KSS API 进程从一个 strict、secret-free 的 deployment value 装配
TDD-05K `KnowledgeQueryGrantPolicy`，并增加一次性 runtime Query client identity bootstrap。配置
缺失时继续不暴露 provisioning route；配置存在但 JSON、字段或 policy fact 无效时，必须在进程配置
阶段失败关闭。checked-in production-local 必须让 policy client 与 bootstrap client 完全一致，并让
KSS API 等待 runtime 与 Reference 两个独立 identity 注册完成。

[FRAME | HIGH] 隔离纵向只证明 checked-in policy/bootstrap facts 可形成 Reference → operator-protected
exact-Release Grant staging，并且 runtime credential 获得的 Grant 仍受 exact Release 与 policy budget
约束。runtime bootstrap 只注册 credential digest，不创建 Grant；Reference/runtime credential 均不能
认证 operator command。本片复用现有 runtime/operator Secret，不新增 SQL、Secret Handle、egress/TLS
规则、Dashboard/BFF、真实模型调用、selective revoke/reconciler、operator audit migration、部署或 Git
提交。具体决策见 ADR-0221。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05O production-local Query authority
verifier。本片只新增一个显式运行的本地验证入口。调用者必须选择一个已存在、不可变的 exact
Release；verifier 不允许 `latest`、占位 ID 或自动选择 Release。入口先通过现有 operator Secret
Handle 创建或精确重放 TDD-05K Grant，再通过独立 runtime client Secret Handle 和现有 KSS runtime
执行一次 `single_pass` Query。Grant receipt 的 runtime client、exact Release、strategy 和预算必须与
checked-in deployment facts 一致；Query result 必须保留同一 Release，并处于 Grant 预算以内。

[FRAME | HIGH] verifier 只输出 secret-free 的 Release、Space、Grant、Query、strategy、预算使用量和
候选数量，不输出 token、Secret Handle、问题文本、Candidate Evidence 内容或上游 detail。缺少 exact
Release、身份/预算漂移、operator provisioning 失败、runtime credential 失败或 Query 失败都退出非零。
本片不修改 readiness，不创建 KSS Release、Reference 或 Published Agent，不调用真实外部模型，不增加
Grant revoke/reconciler、operator-command audit migration、SQL、Dashboard/BFF、生产部署或 Git 提交。

[KNOWN | HIGH] TDD-05O 最终 live 验证保持上述 verifier 边界。操作者先在 verifier 外部通过
production-local 已装配的 KSS 管理发布 API 创建独立 Base，并发布一个没有冲突 Grant 的 exact
Release。两次 verifier 均退出 0，第二次精确重放第一次创建的 active Grant，同时创建新的 succeeded
Query；每次返回 3 个候选。三个历史 Grant 均未修改、撤销或删除。TDD-05O 为
`LOCAL_VERIFIED`，Feature 仍为 `PARTIAL_VERIFICATION`；该结果不是外部模型、生产部署或
Product Release Authority 证据。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05P production-local Formal Candidate
preflight。本片复用既有 `FormalProductionAgentCandidateAssembler`，只接受显式
`agent_id`、`draft_id` 和 exact `draft_revision`。deployment Profile 仍由 production composition
注入，KSS Release 仍从 exact Draft 读取。preflight 只返回 secret-free 的 Draft、Release、Profile
公开标识、catalog revision 和候选摘要；不返回 Secret Handle，不接受 caller-selected Release 或
Profile，也不创建 formal publication command receipt。

[FRAME | HIGH] preflight 不运行 Phase F，不注册 Reference，不创建或重放 Query Grant，不运行
online smoke，不创建 Published Agent Version，不修改 Active pointer 或 readiness。缺少 Draft、
revision 漂移、KSS catalog 不可用或 authoring blocker 必须输出稳定失败 JSON 并退出非零。当前
production-local Draft `c8191d9e-ee0a-5324-8c6d-e0b88622ab61@12` 仍绑定历史 Release
`release-a4b70851cb914862000e15c3`；TDD-05O 已证明该 Release 存在历史 Grant 冲突。因此本片最多
证明候选装配可复核，不声称正式发布可执行，也不修改 Draft binding、生产配置、SQL、Dashboard、
部署或 Git 状态。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05Q exact Draft Memory repair。
本片只允许对 production-local 中
`agent_management_insurance_specialist/c8191d9e-ee0a-5324-8c6d-e0b88622ab61@12`
执行一次显式 CAS 修改：修改前 Tools 必须为 disabled、Memory 必须为 enabled；修改后
只允许 `capabilities.memory` 从 enabled 形态收敛为 disabled 形态，并由既有
`AgentConfigurationWorkspace.update_contract` 完成整包校验、revision CAS、原子保存和审计。
任何 identity/revision 漂移、Tools 已启用、Memory 已禁用、YAML 异常或返回的
revision/identity 不符都必须失败关闭，不得再写一个 revision。

[KNOWN | HIGH] 首次 live CAS 在整包 Contract 校验阶段失败关闭，Draft 仍为 revision 12，
contract-update audit 仍为 6。既有校验契约禁止 disabled Memory 保留 `provider`；随后的
只读 Workspace 检查确认当前 Memory 只含 `enabled=true` 和 `provider`，不含 `scopes`。
因此本片的最小有效语义变更收敛为：把 `enabled` 原位改为 `false`，同时删除同一
Memory 映射内的唯一 `provider` 键值行。实现必须保留 Memory 之外的 YAML 原始字节；
若出现 `scopes`、缺少/重复 provider 或非简单标量 provider，必须拒绝，不自动扩大清理范围。

[FRAME | HIGH] TDD-05Q 只新增一个显式三参数的 production-local 维护入口，不新增 SQL、
直连数据库更新或通用 Contract 编辑器。入口只输出 secret-free 的 Draft identity、修改前后
revision 和 Memory/Tools 布尔结果，固定 `publication_authorized=false`。状态变更后只重跑
TDD-05P read-only preflight；不运行 Phase F、Reference、Query Grant、Query、online smoke、
Published Version 或 Active pointer 变更。旧 Release 的历史 Grant 冲突仍是后续独立阻断，
本片不得修复、删除或绕过它。

[FRAME | HIGH] 2026-08-31 用户确认进入 TDD-05R，并明确不处理已有历史 Grant 的兼容。
本片不修改同一 client/Release 的不可变事实，也不增加兼容探测、revoke、reconcile 或 SQL。
checked-in production-local 将 active runtime Query authority 切换到版本化 identity
`proof-agent-production-local-v2`。ProofAgent runtime、KSS deployment policy 和 KSS bootstrap
必须使用同一 identity。

[FRAME | HIGH] 新 identity 使用独立 Secret Handle
`knowledge/source-service/runtime-client-v2`、独立 Vault path 和新生成的
`KSS_RUNTIME_CLIENT_V2_BEARER_TOKEN`。旧 Secret Handle 不再进入 active locator map；旧
client、Secret 和 Grant 保持原状，本片不宣称其已撤销。bootstrap 仍只注册 credential digest，
新的 exact-Release Grant 仍只由既有 KSS operator-authenticated endpoint 创建。

[FRAME | HIGH] TDD-05R 的可观察成功标准是：静态契约绑定三处 identity 与新 Secret；隔离
PostgreSQL 在同一 Release 存在旧 client Grant 时仍可为 v2 client 创建独立 Grant；保留卷通过
既有 verifier 为当前 Draft 选择的 exact Release 创建并精确重放 v2 Grant，随后完成有界 Query。
本片不运行 formal publication，不创建 Published/Active Agent Version，不改变 readiness，不处理
真实外部模型、stuck-command recovery、Dashboard 或 Production GO。具体决策见 ADR-0222。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05S formal publication command
recovery/takeover。本片只处理进程在 durable `in_progress` 之后退出的恢复。首次命令获得一个由
PostgreSQL 时间控制的租约和 fence；同键、同请求在租约未到期时只重放 `in_progress`，到期后仅
允许一个执行者原子接管并递增 fence。旧执行者不能提交 Version、Active pointer、command receipt
或 audit。

[FRAME | HIGH] command ID 必须稳定派生 Phase F Record、provisional Version 和 validation Run
identity；Phase F 时间固定为原始 command `started_at`。接管必须精确重放同一 Reference request
与 idempotency key，不能因进程重启创建第二套 provisional external identity。租约由部署配置，范围
为 1–3600 秒；请求 body、浏览器和 operator 不能选择 owner、时限或 fence。

[FRAME | HIGH] 本片增加 expand-only `0023_formal_publish_claim` 和 production-local 900 秒配置，
但不运行 formal publication endpoint，不增加后台扫描、heartbeat、cancel、Dashboard、Reference
deregistration、Grant revoke、真实外部模型或 Production GO。接管仍重新装配并重验 exact candidate；
中间 candidate checkpoint 和自动恢复进程属于后续独立切片。具体决策见 ADR-0223。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05T durable Formal Candidate checkpoint。
本片只冻结同一 durable formal command 首次成功装配的 candidate identity。首次执行必须在 Phase F、
Reference、Query Grant、online smoke 和最终发布前，以当前 fenced claim 原子写入
`formal_candidate_sha256`、`knowledge_release_candidate_sha256` 和 PostgreSQL checkpoint 时间。

[FRAME | HIGH] 到期接管仍须从 exact Draft revision、live KSS catalog 和 deployment-owned Profile
重新装配 Candidate。两个摘要必须与既有 checkpoint 完全一致；任一摘要漂移都以稳定失败结束原
command，且不得进入 Phase F 或任何后续外部调用。操作者必须在复核新 Candidate 后使用新的
`Idempotency-Key` 发起新命令，不能把旧 checkpoint 改绑到新 Candidate。

[FRAME | HIGH] checkpoint 只属于内部恢复权威，不进入 public receipt、Dashboard 或请求 body。
checkpoint 写入必须校验当前 command state、command identity、lease owner 和 fencing token；旧执行者
或 terminal command 不能写入或改写 checkpoint。相同摘要的重复写入返回原 checkpoint 时间，
不同摘要保持原值并失败关闭。迁移使用 expand-only `0024_formal_candidate_checkpoint`。

[FRAME | HIGH] 本片不持久化完整 Candidate payload，不增加后台 recovery process、heartbeat、cancel、
Reference/Grant 清理、真实外部模型、formal endpoint 调用或 Production GO。具体决策见 ADR-0224。

[FRAME | HIGH] 2026-08-31 用户确认继续进入下一切片。源码复核确认，既有
formal publication POST 已经在同一请求与 `Idempotency-Key` 下负责未到期重放和
到期接管。TDD-05U 因此不增加第二条 recovery 写路径，只增加 exact command
receipt 读取，供原操作者判断是否需要精确重放。

[FRAME | HIGH] 公开接口为
`GET /api/config/agents/{agent_id}/drafts/{draft_id}/formal-publications/{command_id}`。
调用者必须持有 `agent.publish`，并且 OIDC actor subject 必须与 command 创建者
完全一致。错误 command ID、其他 actor、错误 Agent 或 Draft path 统一返回
`formal_publication_command_not_found`，不泄露资源是否存在。

[FRAME | HIGH] 响应只复用既有 trace-safe public receipt。它不返回 actor、
`Idempotency-Key`、lease owner、fencing token、Candidate checkpoint、原请求、问题或证据
内容，也不改变 lease、command 状态或外部系统。本片不增加列表、后台扫描、
请求正文持久化、自动接管、Dashboard 或 Production GO。

[FRAME | HIGH] 2026-08-31 用户确认继续进入 TDD-05V exact Formal Candidate
external dependency probe。production-local Phase F compatibility endpoint 按设计固定返回
`authorized=false`；本片不伪造 Phase F，也不调用 formal publication endpoint。

[FRAME | HIGH] 新增一个显式 host 入口，只接受 exact `agent_id`、`draft_id` 和
正数 `draft_revision`。同一 production composition 只读装配 Candidate；Draft 选择 exact
KSS Release 与 model-role configuration，deployment 注入 Binding Profile、Secret Handle、egress、
Admission Scorer 和执行预算。验证问题是 checked-in 非敏感 fixture，调用者不能
选择 Release、model connection、credential、Profile、question 或 budget。

[FRAME | HIGH] probe 通过既有 governed `RunPurpose.VALIDATION` 执行 exact Candidate，要求
`ANSWERED_WITH_CITATIONS` 和至少一条 accepted nonblank citation，并通过既有 immutable
artifact store 保留 trace/receipt 后 exact read-back。成功输出不返回 question、answer、
Candidate/Evidence 内容、credential、raw prompt 或上游 detail；只返回 exact Candidate/Release、
question SHA-256、model connection IDs、run、outcome、citation count 和 artifact refs。

[BOUNDARY | HIGH] 本片允许新增一条 durable KSS Query 和两个 immutable validation
artifacts，但必须精确复用既有 active Query Grant。不创建或重放 Command、Phase F、
Reference、Grant、Published Version 或 Active pointer。缺少 KSS、Grant、Admission、model、
credential、egress 或 artifact 依赖时失败关闭。结果不是 formal online-smoke
qualification、publication approval、release Gate 或 Production GO。具体决策见 ADR-0226。

[KNOWN | HIGH] production-local exact Draft@13 验证发现 Candidate Contract Bundle 的 audit
paths 会逃逸 materialized package。secure materializer 因此在 KSS Query 前返回
`formal_candidate_contract_bundle_not_materializable`。本片不放宽 traversal 校验、不重写
Candidate、不改 Draft/Grant；Command、Version、Active、Reference、Grant、Query 六项计数前后
不变。下一片如处理该 blocker，必须通过既有 Workspace complete-Contract validation、exact
revision CAS 和 audit 创建新的 Draft revision，并只收敛 Contract paths。

[FRAME | HIGH] 2026-08-31 用户确认进入 TDD-05W exact Draft Contract path normalization。
新增一个显式 production-local host 入口，只接受 exact `agent_id`、`draft_id` 和 expected
revision。调用者不能提供目标路径或 Contract 内容。checked-in 命令只允许把
`../../runs/latest/trace.jsonl` 和
`../../runs/latest/governance_receipt.md` 分别收敛为 `./trace.jsonl` 和
`./governance_receipt.md`。

[FRAME | HIGH] 命令必须要求两个 `audit` 字段唯一、为 scalar 且同时处于已知旧状态。
missing、duplicate、mixed、unexpected 或 already-normalized 都在 Workspace 写入前失败。
候选 YAML 的 parsed structure 只能在这两个字段变化；真正保存继续复用既有 complete-Contract
validation、exact revision CAS、原子 Draft save 和 configuration audit。成功后还必须重验
Agent/Draft identity、`revision + 1`、exact YAML bytes 和两个新路径。具体决策见 ADR-0227。

[BOUNDARY | HIGH] 本片最多创建一个新 Draft revision 和一条既有类型的 configuration audit。
它不修改 Policy/Tools/extra files，不创建 Command、Phase F、Reference、Grant、Version 或 Active
pointer，也不授权发布。完成后只对新 revision 重跑 read-only preflight 与 TDD-05V probe；不调用
formal publication endpoint。

[KNOWN | HIGH] 用户随后明确授权对 exact Draft@14 执行一次固定问题 probe，允许最多一条新 KSS
Query 和两份 immutable validation artifacts。实际只执行一次：exact Release Query succeeded，返回
3 条 Candidate Evidence；随后以 `formal_candidate_external_smoke_failed` 失败，未写入 ProofAgent
validation artifacts。Command、Version、Active 与 Reference 保持 0，Grant 保持 5，Query 由 21
变为 22。没有重试，也没有进入 formal publication。

[FRAME | HIGH] 下一切片应先收敛 secret-free probe stage diagnostics，而不是再次调用真实依赖。
稳定错误只允许区分 KSS、Evidence Admission、model transport/output、citation validation 和
artifact retention；不得返回 question、answer、Candidate/Evidence content、credential、raw prompt
或 provider detail。完成测试和本地回归后，任何新 external probe 都需要新的明确外发授权。

[FRAME | HIGH] TDD-05X 按 ADR-0228 固定上述五类错误码。分类只读取既有结构化错误码、
accepted/citation 事实和 trace-safe final-answer validation code，不解析 exception message、
provider response 或业务内容。结构化事实缺失或含义不明确时继续返回
`formal_candidate_external_smoke_failed`，不猜测根因。

[BOUNDARY | HIGH] 本片只改现有 probe 的失败诊断，不新增执行路径、重试、HTTP/Dashboard
接口或外部调用。验证全部使用本地可控替身；本片不会再次执行真实 KSS/model probe。任何后续
真实 probe 仍需针对 exact Candidate 和允许副作用取得新的明确授权。

[FRAME | HIGH] 2026-08-31 用户在收到 TDD-05X 完成结果及下一切片副作用说明后确认“继续下一
切片”。这足以继续本地 preflight、ArtifactStore 修复和无外发验证，但安全审批要求对具体数据外发
作更明确确认：把 `agent_management_insurance_specialist`、Draft
`c8191d9e-ee0a-5324-8c6d-e0b88622ab61` revision 14 的 fixed-question Candidate Evidence
发送给只读确认的当前受管连接 `model_deepseek` revision 1（ACTIVE，DeepSeek
`deepseek-v4-flash`，`https://api.deepseek.com`），并允许最多一条新 KSS Query 和两份
immutable validation artifacts；不读取或外发 credential。

[FRAME | HIGH] 执行前必须重建包含 TDD-05X 的 production-local 镜像，通过 baseline，并重验
Draft@14 read-only preflight、exact Candidate/Release identity 及 Query/artifact 前置计数。probe
只能调用既有三参数 host entry 一次。成功时记录 bounded success result；失败时只记录新增的 stable
stage code，并立即停止，不读取 exception detail、Candidate Evidence、answer、raw prompt、provider
response、credential 或 `.env` 内容，也不使用本次授权重试。

[BOUNDARY | HIGH] TDD-05Y 不创建或重放 Formal Publication Command、Phase F、KSS Reference、
Query Grant、Published Agent Version 或 Active pointer，不调用 formal publication endpoint，也不
授权上线。执行后必须核对 Query/artifact 增量与 Command、Version、Active、Reference、Grant 状态。
无论结果成功或失败，都只是 bounded production-local external-dependency evidence，不是 formal
online-smoke qualification、publication approval、release Gate 或 Production GO。

[KNOWN | HIGH] TDD-05Y 在消耗唯一外部 Query 前发现生产 composition 注入当前
`S3ArtifactStore`，但候选验证运行时仍调用已淘汰的 `key/content/media_type + get_exact`
协议。真实执行即使通过 model/citation 阶段，也会在 artifact retention 失败；既有测试因使用旧协议
fake 未覆盖该边界。因此暂停外部 probe，授权预算保持未使用。

[FRAME | HIGH] 本片先以 TDD 把候选验证运行时收敛到仓库唯一的 `ArtifactStore` 端口：使用
`ArtifactPutRequest` 写入 RUN_TRACE/GOVERNANCE_RECEIPT，以 exact version head/open 回读验证，
再由存储适配器生成不含凭据的 canonical artifact URI。只修复 production composition 已存在的
接口不一致，不新增存储、执行器、重试或发布入口。

[KNOWN | HIGH] ArtifactStore cutover、重建 baseline、真实 MinIO validation pair 和 Draft@14
read-only preflight 已通过。用户随后按 exact Draft、模型目的地、副作用预算、单次执行和禁止发布
范围作出明确同意。既有三参数入口只执行一次，返回
`formal_candidate_external_smoke_evidence_admission_failed` 后立即停止，没有重试。

[KNOWN | HIGH] 本次调用精确重放既有 succeeded KSS Query
`knowledge-query-f25bebcd4a9946578c46280a68387e32`，没有创建新 Query；Query 保持 22，Grant
保持 5，Command、Version、Active、Reference、Artifact 保持 0。结果只定位到 Evidence
Admission 边界，不读取或输出 Candidate Evidence、answer、provider detail、credential 或日志，
也不构成 positive cited-answer evidence 或发布授权。

## 14. TDD-05Z：secret-free Evidence Admission reason diagnostics

[FRAME | HIGH] 本片只细化 external probe 已有 Evidence Admission 阶段诊断。公开失败 envelope
保留原 stage `error_code`，并仅在结构化事实充分时增加 allowlist `reason_code`。允许分类
Scorer 不可用、分数无效、Candidate 集为空、分数缺失、未达阈值和策略拒绝；不得返回分数、
阈值、Candidate/Evidence 标识或内容、question、answer、provider response、credential、raw prompt、
artifact path 或 exception message。

[FRAME | HIGH] Scorer adapter 通过 typed port error 传递边界类别；完成的 governed Run 只从既有
trace-safe `evidence_evaluation.metadata.no_evidence_reason_code` 投影类别。错误正文不得参与分类；
未知或不完整事实不输出 `reason_code`。有 Candidate 且存在受管分数但全部低于 `min_score` 时，
内部 metadata 使用 `knowledge_candidate_threshold_not_met`，不再误标为
`zero_knowledge_candidates`。

[BOUNDARY | HIGH] failure envelope 是 strict contract，因此从 v1 显式升级到 v2；success envelope
不变。非 Admission stage 不接受 Admission reason。本片不新增重试、持久化、HTTP/Dashboard
入口、KSS Query、model/scorer 调用、artifact、Grant 或发布状态变化。

[KNOWN | HIGH] RED 的四个用例分别证明 scorer category 缺失、threshold metadata 错标、runner
丢失 allowlist reason 和 CLI 无法投影 reason。GREEN/REFACTOR 后 11 项核心行为、146 项受影响
回归通过；完整后端在允许本机回环端口的环境中为 2474 passed、272 skipped、2 deselected，另有
一项既有 Authlib warning。没有执行真实 KSS、Scorer 或模型调用。

## 15. TDD-06A：fixed-synthetic production-local Admission Scorer verification

[FRAME | HIGH] 2026-09-01 用户要求继续下一切片。本片只增加一个零参数 production-local
Admission Scorer 验证入口。入口固定构造一个完全虚构的问题和一个 relevance Candidate，通过既有
production `KnowledgeCandidateRuntime.bind_for_run()` 取得部署装配的 Scorer，并只调用
`KnowledgeCandidateAdmissionScorer.score_candidates()`。调用者不能传入 Draft、Release、问题、
Candidate、Model Connection、credential 或 budget。

[FRAME | HIGH] 验证必须复用 deployment-owned Scorer ID/revision、versioned Secret Handle、Vault
Secret Provider 和 guarded egress。响应必须覆盖 exact synthetic Candidate set，且每个分值为 0 至
1 的有限数。成功输出只包含 Scorer identity/revision、固定输入摘要、计数和显式 false authority
flags；失败输出不能包含 exception、请求、响应或 credential detail。

[BOUNDARY | HIGH] 本片不调用构造出的 KSS service 或 query factory，不调用 Draft 选择的 answer
model，不写 artifact，也不创建 Query、Grant、Reference、Formal Command、Version 或 Active
pointer。通过结果只能证明 production-local compatibility Scorer composition；不能判断 Draft@14
Candidate 质量、阈值或 policy root cause，也不是 external model evidence、Phase F、publication
approval、release Gate 或 Production GO。具体决策见 ADR-0231。

## 16. TDD-06B：fixed-synthetic Control Plane Admission verification

[FRAME | HIGH] 本片在 TDD-06A 的固定合成输入上再前进一层，但不扩大到真实 KSS 或 Agent Run。
入口通过 production runtime binding 取得部署装配的 Admission Scorer，只在
`KnowledgeCandidateService` 端口放置固定内存 Candidate Result，再调用公开的
`KnowledgeRetrievalService.retrieve()`。`PolicyEngine`、Candidate 投影、Scorer 和 Evidence
Evaluation 均复用生产代码。

[FRAME | HIGH] question、Candidate、strategy、单 Candidate 预算和 `min_score` 全部固定，调用者不能
覆盖。成功必须同时满足 Scorer identity/revision 精确匹配、策略明确允许、Candidate 集合不漂移、
Evidence Evaluation 通过且 accepted count 恰为 1。策略拒绝、分数低于阈值、Scorer 或 Candidate
漂移均失败关闭。公开结果不得包含输入正文、Candidate 标识/内容、分数、阈值、citation、credential、
endpoint、raw response 或 exception。

[BOUNDARY | HIGH] 固定内存 Candidate Service 不创建 KSS Query；本片不调用 DeepSeek，不读写
Artifact Store，不进入 Phase F，也不创建 Grant、Reference、Formal Command、Version 或 Active
pointer。通过结果只证明一条 fixed-synthetic production-local Control Plane Admission 路径，不能
判断 Draft@14、真实 Candidate 质量、引用回答、正式发布、release Gate 或 Production GO。具体决策
见 ADR-0232。

## 17. TDD-06C：fixed-synthetic governed Run verification

[FRAME | HIGH] 本片继续使用 TDD-06A/06B 的固定 synthetic question/Candidate 和 production
runtime binding，只把验证入口推进到公开 `execute_agent_package_run()`。KSS service 端口仍返回
固定内存 Candidate；query factory、Admission Scorer、Controlled ReAct、Evidence Evaluation、
deterministic planner/reviewer/answer、citation 和 governance receipt 均复用当前运行代码。

[FRAME | HIGH] verifier 为零参数入口。question、Candidate、Release、strategy、budget、Scorer
identity 和 deterministic model fixture 全部固定；调用者不能覆盖。成功必须得到
`ANSWERED_WITH_CITATIONS`、1 份 Accepted Evidence、1 条 citation，并在临时目录中同时生成 trace
和 receipt。低于 threshold、identity/fixture 漂移、临时审计缺失或 outcome/count 漂移均失败关闭。

[BOUNDARY | HIGH] 临时 trace/receipt 在运行结束后删除，不写 ArtifactStore。固定内存 Candidate
Service 不创建 KSS Query；本片不调用 DeepSeek，不读取 Draft@14 Candidate，不进入 Phase F，
也不创建 Grant、Reference、Formal Command、Version 或 Active pointer。通过结果只证明一条
fixed-synthetic production-local governed Run，不是 exact Candidate 外部验证、formal online-smoke
qualification、release Gate 或 Production GO。具体决策见 ADR-0233。

## 18. TDD-06D：Release 状态与回滚失败关闭

[FRAME | HIGH] 2026-09-01 用户确认提交 TDD-06B/06C 后启动本窄切片。本片只
加固既有 `AgentConfigurationWorkspace.rollback_version()`：当目标 immutable Published Agent
Version 绑定 KSS 时，必须在 active pointer 和 audit 写入前重验 live Catalog。

[FRAME | HIGH] Catalog 必须 ready，exact Release 必须唯一。正式版本使用已保留
Reference 的 Space/Base/Release 三元组；非正式 KSS 版本只在 Release ID 全 catalog
唯一时可继续。`queryable` 与 `deprecated` 允许回滚；`retired`、`revoked`、缺失、
歧义、Catalog 不可用或读取异常均返回稳定 conflict，且不产生 activation 或 audit。

[FRAME | HIGH] RED 先证明 `retired/revoked` 目标会被旧实现错误激活；GREEN 只增加
Release 预检与写前目标一致性重读；REFACTOR 再补 `queryable/deprecated`、精确正式
身份、missing/ambiguous/unready/exception 和无 KSS binding 的回归。聚焦 Workspace public method，
不新建平行 rollback service。

[BOUNDARY | HIGH] 本片不开放 production rollback HTTP/capability，不调用 KSS Query、
DeepSeek 或 ArtifactStore，不创建/注销 Grant 或 Reference，不进入 Phase F，不新建或发布
Agent Version，不执行 formal publication activation，不新增 reconciler、schema、部署或
Production GO。具体决策见
ADR-0234。

## 19. TDD-06E：回滚确认新鲜度

[FRAME | HIGH] TDD-06D 已在 Workspace 内完成 exact Release 状态预检，但现有回滚命令只
提交 target version，未绑定 Operator 确认时看到的 active pointer。本片只关闭这一并发缺口：
`AgentConfigurationWorkspace.rollback_version()` 增加必填
`expected_active_version_id`，`None` 表示显式预期当前无 active version。

[FRAME | HIGH] Workspace 首次读取 immutable target 时同时读 active pointer。调用方预期已
过期时，必须在 KSS Catalog 调用前返回 `active_agent_version_conflict`。Release 预检通过后，
写 UoW 再次读取 target 和 pointer；任一漂移均不产生 activation/audit。最终 CAS expectation 与
`rollback_from_version_id` 都必须使用调用方确认值。

[FRAME | HIGH] 现有 development rollback HTTP body 同步要求该字段，Dashboard 在打开确认框时
冻结并提交当时显示的 active version；后续页面重渲染不能替换该 expectation。缺失字段返回
422，显式 `null` 代表无 active pointer。本片不
修改 Production configuration router，`can_rollback` 继续为 `false`。

[BOUNDARY | HIGH] 本片不开放 Production rollback endpoint，不修改权限映射，不调用真实
KSS Query、model 或 ArtifactStore，不创建 Grant/Reference，不进入 Phase F，不发布 Version、
部署、执行真实回滚或授予 Production GO。具体决策见 ADR-0235。

## 20. TDD-06F：PostgreSQL 回滚事务纵向验证

[FRAME | HIGH] 本片复用 TDD-06D/06E 的 `AgentConfigurationWorkspace.rollback_version()`，
并将其接到生产使用的 `PostgresConfigurationUnitOfWork`。验证对象是既有三层合同的组合：
Workspace caller expectation、PostgreSQL Active pointer CAS，以及 pointer/audit 同事务提交。
不增加第二套 rollback service、repository 或 SQL。

[FRAME | HIGH] 测试只使用 disposable PostgreSQL schema、完全虚构的 Agent/Version facts 和
固定内存 KSS Catalog。主路径必须保留两个 immutable Published Versions，仅把 Active pointer
切回目标版本，并写入一条 `agent.version.rolled_back` audit。两个共享同一旧 expectation 的
并发命令必须只有一个成功；失败命令不得产生第二条 audit。

[FRAME | HIGH] 在真实 PostgreSQL 事务中，若 audit append 后的应用边界失败，pointer 与 audit
必须一起回滚，两个 Published Versions 保持不变。该故障通过 Unit of Work 的测试专用 audit
wrapper 注入，不修改生产 adapter，也不把测试替身当成 PostgreSQL 权威。

[BOUNDARY | HIGH] 本片不开放 Production HTTP/capability，不调用真实 KSS、model、ArtifactStore
或生产数据库，不创建/注销 Grant 或 Reference，不进入 Phase F，不发布新版本，不部署，不执行
线上 rollback，也不建立跨 KSS/ProofAgent 的分布式事务或 lease。若 disposable PostgreSQL
不可用，只能记录环境缺口，不能把 skipped 用例称为通过。

## 21. TDD-06G：Production 回滚准入合同与能力门控

[FRAME | HIGH] 本片只在既有 Production Agent Configuration router 上增加
`POST /config/agents/{agent_id}/versions/{version_id}/rollback`。请求体严格要求
`expected_active_version_id`，字符串表示调用方确认的 exact Active pointer，JSON `null`
明确表示预期当前无 Active Version；缺失字段和未知字段均返回 422。Delivery 只负责 HTTP、
`agent.publish` 权限、稳定错误映射和审计 actor 投影，实际状态变化仍只调用现有
`AgentConfigurationWorkspace.rollback_version()`。

[FRAME | HIGH] Production composition 新增 server-owned rollback capability gate，默认值为
`false`。门控关闭时，路由返回稳定的 `production_agent_rollback_unavailable`，不得调用
Workspace；Draft capability 继续投影 `can_rollback=false`。只有门控显式开启且当前 Operator
持有 `agent.publish` 时，capability 才可为 `true`，路由才可进入 Workspace。现有 Production
OIDC session 与 same-origin CSRF middleware 继续覆盖该 POST 命令。

[FRAME | HIGH] Workspace 的 `agent_version_not_found` 映射 404；pointer、target 或 Release
冲突映射 409；`agent_knowledge_catalog_unavailable` 映射 503；未知内部异常只返回
`production_agent_rollback_failed`，不得泄露 exception detail。response-loss retry 继续依赖
caller-confirmed pointer 失败关闭：旧 expectation 返回 conflict，调用方必须重载后重新确认，
本片不新增第二套幂等收据。

[BOUNDARY | HIGH] 本片不会在真实 Production composition 中开启 rollback gate，不修改角色映射、
Dashboard、SQL、migration 或 KSS 服务，也不连接真实 PostgreSQL/KSS、执行线上 rollback、创建或
注销 Grant/Reference、进入 Phase F、发布、部署或授予 Production GO。cross-service rollback
lease、真实依赖演练与正式启用属于后续独立切片。具体决策见 ADR-0236。
