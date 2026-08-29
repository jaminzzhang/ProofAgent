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
| 执行证据缺口 | Connection Profile 已有本地 PostgreSQL/HTTP/同步 Worker 证据；TDD-02A 至 02G 已有 Preparation 持久化准入、租约协调、候选构建、fenced `ready/failed` 结果、`ready → expired/consumed` 核心单事务发布、显式 one-shot 主动过期和 queued/running 协作取消；TDD-04E/04F 已公开 controlled publish/cancel KSS/BFF，TDD-04G 已公开有界、secret-free audit read BFF，但仍无 expiry HTTP/BFF、常驻 Worker、自动过期调度或终端操作者委托身份，既有直接 Release 发布路径也尚未收敛。异常 ready quarantine、真实策略/Secret/egress/TLS、生产进程切换、Reference/lifecycle command 闭环、正式 publisher cutover、三角色端到端与 Phase F 尚未完成；正式验收人员仍需在发布前指派 |

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
| `docs/adr/0217-use-a-durable-one-use-release-preparation-state-machine.md` | ADR | durable Preparation、one-use ready candidate 与 fenced Worker 状态机 | 已新增 | accepted design；核心状态/事务、application-only cancel/expiry/publication、TDD-04C start/status BFF、TDD-04D one-shot execution runtime、TDD-04E controlled publish BFF、TDD-04F controlled cancel BFF 与 TDD-04G bounded audit read BFF 已实现；常驻执行进程和 expiry 产品接线待实现 |
| `docs/domain/knowledge-evidence/CONTEXT.md` | 术语 | 三类可叠加 Hybrid Knowledge Configuration Role Bundle | 已更新 | 用户已确认 |
| `docs/domain/knowledge-evidence/decisions.md` | 歧义记录 | 首期不做复杂 RBAC 或强制四眼，复用全局 named permission 映射 | 已更新 | 用户已确认 |
| `docs/PROJ_CONTEXT.md` | Feature 索引 | TDD-01A/01B、TDD-02A 至 02G、TDD-03A 至 03F 与 TDD-04A 至 04G 本地执行状态为 `PARTIAL_VERIFICATION`，不是生产切换证据 | 已更新 | 当前事实 |

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
