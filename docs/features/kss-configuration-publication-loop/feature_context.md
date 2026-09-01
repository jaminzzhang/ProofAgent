# KSS Configuration And Agent Publication Loop Feature Context

## 1. 需求基本信息

| 字段 | 内容 |
| --- | --- |
| 需求名称 | KSS 数据配置与 Agent 正式发布完整流程 |
| 需求编号 | `kss-configuration-publication-loop` |
| 需求来源 | 2026-08-25 `grill-with-docs` 设计评审 |
| 所属版本 | 待确认 |
| 业务负责人 | 待确认 |
| 研发负责人 | 待确认 |
| 测试负责人 | 待确认 |
| 发布负责人 | 待确认 |
| 当前状态 | `PARTIAL_VERIFICATION`：TDD-01A/01B 本地接线、TDD-02A 至 02G Preparation 核心、TDD-03A 至 03F Reference/lifecycle 核心、TDD-04A 至 04H 管理 BFF、TDD-05A 至 05P 正式候选/发布纵向、TDD-05Q Draft Memory normalization、TDD-05R versioned runtime client/new Grant、TDD-05S fenced takeover、TDD-05T Candidate checkpoint、TDD-05U actor-owned receipt read、TDD-05V 发布外 exact Candidate external-dependency probe、TDD-05W exact Draft Contract path normalization、TDD-05X secret-free probe stage diagnostics、TDD-05Y current ArtifactStore validation retention cutover、TDD-05Z secret-free Evidence Admission reason diagnostics，以及 TDD-06A 至 06C 的三层 fixed-synthetic verification、TDD-06D Release-state rollback application core、TDD-06E caller-bound rollback confirmation 与 TDD-06F PostgreSQL rollback transaction verification 已有本地证据。TDD-05W 已将 Draft@13 推进为 Draft@14；其首次 probe 在 exact KSS Query 成功后以 generic failure 停止。TDD-05X 增加五类稳定错误码；TDD-05Y 关闭 shared validation runtime 与生产 `S3ArtifactStore` 的协议不一致，并通过真实 MinIO exact write/read/URI/delete。取得 exact 数据外发授权后，新 probe 只执行一次并返回 `formal_candidate_external_smoke_evidence_admission_failed`。该调用精确重放既有 succeeded Query，没有新增 Query；Query 保持 22。Command、Version、Active、Reference 与 Artifact 仍为 0，Grant 为 5。TDD-05Z 为未来 Admission failure.v2 增加六类 allowlist reason，并修正 threshold metadata，不追溯判断已结束 probe。TDD-06A 使用一个完全虚构 Candidate，在不调用 KSS 或 DeepSeek 的情况下验证 production-local compatibility Scorer composition；TDD-06B 在相同固定输入上复用公开 Knowledge Retrieval Service、deterministic Policy、部署装配的 Scorer 和 Evidence Evaluation，接纳数为 1；TDD-06C 再通过公开 governed Run 入口生成 1 份 Accepted Evidence、1 条 citation 和 cited answer，临时 trace/receipt 已清理。KSS Query 保持 22，Formal Command 保持 0。TDD-06C 的独立 immutable overlay image 已让 API、model-plane、Run Executor 使用同一 digest，并通过完整 baseline 与 checked-in host 入口；完整 production Dockerfile build 仍受外部基础镜像 metadata 解析阻塞。TDD-06D 同时完成 `queryable/deprecated` rollback 允许态和 `retired/revoked`、missing/ambiguous/unavailable 失败关闭；TDD-06E 再要求 rollback 绑定调用方确认的 Active pointer，并在 KSS 预检前与写事务内拒绝漂移；TDD-06F 使用 disposable PostgreSQL 验证 pointer/audit 原子提交、并发单赢家与失败回滚。production rollback endpoint、真实 KSS 依赖演练与线上 rollback 仍未开放。前三项 fixed-synthetic 结果均不能判断 Draft@14 的真实 Admission 根因，也不是正向 external cited-answer evidence。后台 recovery process、Query Grant selective revoke/reconciliation、cross-operator command audit/listing、Preparation 常驻执行、自动过期、deregistration/lifecycle 命令 BFF、终端操作者到 KSS audit 的委托身份链、生产 egress/TLS、Release 删除 retention adapter、物理删除、affected-reference 明细/通知、Dashboard 页面、生产 retention 配置和生产切换尚未完成 |

## 2. 需求目标与范围

| 目标 | 说明 | 验收口径 |
| --- | --- | --- |
| 形成完整配置与使用流程 | 从 KSS 数据接入开始，经不可变 Release、Agent Draft 绑定、正式发布、运行和回滚，形成可观察、可审计且失败关闭的流程 | 每个权威交接都有明确输入、输出、权限、状态、失败结果和验证证据 |
| 保持服务权威分离 | KSS 拥有数据和 Release；ProofAgent 拥有 Agent Draft、Evidence Admission、正式发布、激活和最终答案 | 任一界面或 API 都不能绕过所属服务的权威边界 |
| 绑定正式候选 | 正式生产发布消费一个指定 Draft revision，不再从独立 manifest 和环境选择另一套 Agent/KSS 候选 | 发布记录可追溯到 exact Draft revision、exact KSS Release、部署级 Binding Profile 和候选绑定证据 |

### 范围内

| 范围项 | 说明 | 依据 |
| --- | --- | --- |
| KSS 数据资产管理 | Space、Source、不可变 Source Version、版本化 Base Draft、Knowledge Base Version 和 exact Release 的创建、查看与状态管理 | ADR-0193、ADR-0205、ADR-0214 |
| KSS 数据接入 | 文件摄取和外部快照同步；KSS 管理版本化的非敏感 Connection Profile，Vault 管理凭据值，部署策略管理连接类型、egress、trust root 和硬限制 | KSS management API、ADR-0199、ADR-0213 |
| ProofAgent 管理入口 | 通过同源 BFF 提供 secret-free 管理投影和受权限控制的命令 | 当前 BFF 与安全边界 |
| Agent Draft 绑定 | 在 Draft 上选择并保存 exact KSS Release authoring candidate | ADR-0211 |
| 正式生产发布 | 绑定 exact Draft revision，重验 KSS Release，组合部署级 Binding Profile、Phase F 证据和在线 smoke 后原子发布并激活 | 2026-08-25 用户确认、ADR-0212 |
| 运行与回滚 | Published Agent Version 固定 exact KSS binding；回滚选择另一个有效的不可变版本 | ADR-0210 |
| 可观察与审计 | 投影资源状态、阻断项、任务状态和 trace-safe 审计身份 | `AGENTS-COMMON.md` |

### 配置与使用主链

```mermaid
flowchart LR
    CP[Connection Profile revision] --> SV[Source Version]
    SV --> BD[Base Draft revision]
    BD --> RP[Release Preparation]
    RP --> KR[Exact KSS Release]
    KR --> AD[Agent Draft revision]
    AD --> FC[Formal Production Candidate]
    FC --> RR[KSS Reference Registration]
    RR --> QG[Exact Query Grant Staging]
    QG --> OS[Exact Online Smoke]
    OS --> AV[Published and Active Agent Version]
    AV --> KQ[Exact KSS Query]
    KQ --> CE[Candidate Evidence]
    CE --> EA[ProofAgent Evidence Admission]
    EA --> AO[Governed Answer or Failure]
```

### 范围外

| 范围项 | 排除原因 | 影响 |
| --- | --- | --- |
| Query 时实时联邦外部数据源 | 会破坏 exact Release、重放和引用边界 | 外部数据必须先物化为 Source Version |
| 浏览器持有 KSS token、上游凭据或 Secret Handle 值 | 违反 secret-free 浏览器边界 | 所有敏感调用留在服务端 |
| Knowledge 配置动作直接激活 Agent | 会绕过 Phase F 和正式发布权限 | 数据发布与 Agent 激活保持分离 |
| KSS 执行 Evidence Admission 或生成最终答案 | 违反 Control Plane 权威边界 | KSS 只返回 Candidate Evidence |
| 将本地验证称为 Production GO | 发布 Gate 尚需独立证据 | 所有状态保留证据限定 |

## 3. 设计树

| 节点 | 类型 | 触发条件/输入 | 处理方案 | 输出/状态变化 | 验证点 | 风险等级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | 操作员需要让一组受管知识供生产 Agent 使用 | 贯通 KSS 数据、Release、Draft、正式发布和运行权威 | 可重放的 Published Agent Version | 端到端 exact identity 追踪 | P1 | 已确认 |
| MAIN-1 | 数据接入 | 文件或已批准外部连接 | KSS 使用 exact Published Connection Profile revision 摄取或同步，生成不可变 Source Version | 新 Source Version 可供 Release 组合 | 格式、安全、幂等、profile revision、lineage | P1 | TDD-01B 已接 PostgreSQL、KSS 管理 HTTP、显式受管 Worker 与不可变 lineage；TDD-04B 已接 ProofAgent 同源 Profile 生命周期与同步任务 BFF。真实策略/Secret/egress/TLS、终端操作者审计链、Dashboard 页面和生产进程切换待验证 |
| MAIN-2 | Release | exact Base Draft revision | KSS 在 Preparation 启动时解析选择策略并冻结 Knowledge Base Version；持久化状态机异步准备后原子消费一次并发布 exact Release | Release 变为 queryable，Preparation 变为 consumed | 无部分可见、无跨 Space、无 runtime latest、可重放 | P1 | TDD-02A 至 02G 已有 Draft CAS、冻结、queued/running/ready/failed/cancelled/expired/consumed、application-only 单事务 publication、one-shot 主动过期和 queued/running 协作取消；TDD-04C 已接 ProofAgent 同源 Draft save/exact read 与 Preparation start/status；TDD-04D 已接可选、一次最多处理一个任务的 execution runtime；TDD-04E 已接 no-body、edit-protected controlled publish BFF，使未过期 ready 通过既有 one-use CAS 进入 consumed/queryable Release；TDD-04F 已接 no-body、Idempotency-Key-bound controlled cancel BFF；TDD-04G 已接 `knowledge_source.view` 保护、有界、secret-free 的 Preparation 审计读取；TDD-04H 已接 no-body、edit-protected 的 exact-resource expiry BFF，以数据库时间原子收敛到 expired 并自然重放同一终态。常驻进程、自动过期调度、终端操作者委托身份、旧直接入口收敛和生产接线待实现 |
| MAIN-3 | Draft 绑定 | Agent Editor 选择 queryable Release | 保存 secret-free Draft candidate，使用 revision CAS | Draft revision 前进，Active Version 不变 | exact parent identity 与冲突测试 | P1 | 已实现 |
| MAIN-4 | 正式候选 | Release Operator 提交 exact Draft revision | 重验 Draft、Release、权限和部署级 Binding Profile | 形成 Formal Production Agent Candidate | 不接受 latest Draft、独立 manifest 或环境替代 Release | P1 | TDD-05A 至 05P 已建立 exact Candidate 与只读 preflight；TDD-05Q 经既有 validator/CAS/audit 把 Draft 12 推进到 13并关闭 Memory；TDD-05W 复用同一权威把 Draft 13 推进到 14，仅收敛两个 audit path。Draft@14 preflight 成功并产生新 Candidate 摘要，仍为零发布/KSS 写入且不授权发布 |
| MAIN-5 | 发布激活 | Phase F 证据与在线 smoke 通过 | 冻结 Published Agent Version，并以 PostgreSQL CAS 激活 | Active Agent Version 更新 | 并发、审计、exact evidence、失败无状态改变 | P1 | TDD-05D 至 05U 已覆盖 Reference、Grant、governed online smoke、原子发布、durable command、production composition、versioned runtime authority、fenced takeover、Candidate checkpoint 与 actor-owned receipt read。TDD-05V 新增发布外 exact Candidate external-dependency probe；TDD-05W 已修复 Draft path blocker；TDD-05X 已增加五类 secret-free stage diagnostics；TDD-05Y 已让 shared validation runtime 使用生产当前 `ArtifactStore` 端口并通过真实 MinIO exact retention 验证。取得具体外发同意后，Draft@14 probe 只执行一次，精确重放既有 succeeded Query 并停在 Evidence Admission；无新 Query、validation artifact 或发布状态。TDD-05Z 增加 future failure.v2 Admission reason allowlist，不执行外部调用。Grant selective revoke/reconciliation、cross-operator command audit/listing 与后台 recovery process 待实现 |
| MAIN-6 | 运行使用 | Run 解析 Active Agent Version | exact KSS Query → Candidate Evidence → ProofAgent Admission | 引用回答或受治理失败结果 | 无 fallback、引用可回放、Admission 权威正确 | P1 | 已实现主体路径。TDD-06A 独立验证 fixed-synthetic production-local Scorer composition；TDD-06B 再通过公开 Knowledge Retrieval Service 验证 deterministic Policy、bound Scorer 和 Evidence Evaluation 接纳 1 个固定 Candidate；TDD-06C 继续通过公开 governed Run 入口得到 1 份 Accepted Evidence、1 条 citation 和 cited answer。三者均不调用真实 KSS Query 或 Draft-selected answer model，不替代真实 exact Candidate/完整外部验证；06C immutable overlay 与 checked-in host 入口已通过，完整 production Dockerfile build 待外部 metadata 恢复后补证 |
| MAIN-7 | Agent Version 回滚 | Operator 选择 immutable Published Version，并确认当前 Active pointer | live ready Catalog 重验 exact KSS Release；Workspace 在预检前和写事务内校验 caller expectation，再以 pointer CAS 原子写 activation/audit | 新 Active pointer 或稳定 conflict | `queryable/deprecated` 允许；`retired/revoked`/missing/ambiguous/unavailable 或 pointer 漂移失败关闭 | P1 | TDD-06D 已完成 Release-state application core；TDD-06E 已将 caller-confirmed pointer 贯穿 Workspace、development HTTP 与 Dashboard；TDD-06F 已用 disposable PostgreSQL 证明 pointer/audit 原子提交、并发单赢家与失败回滚。production rollback HTTP/capability、cross-service lease 与真实操作演练仍在范围外 |
| BRANCH-1 | 依赖失败 | KSS、Secret、Grant、Scorer 或 Release 不可用 | 失败关闭，不替换 Release 或走本地知识 | 稳定 blocker/problem | 负向依赖矩阵 | P1 | 已确认 |
| BRANCH-2 | 并发与过期 | Draft revision、Active pointer 变化，或 Release deprecated/retired/revoked | 新发布拒绝 deprecated/retired/revoked；既有 deprecated binding 保持运行；retired/revoked 查询与新回滚失败关闭；caller-confirmed pointer 漂移返回 conflict | 无旧候选误激活、无并发 pointer 被静默采用、无 fallback | KSS 内 registration/deregistration/lifecycle serialization，跨服务保守引用 | P1 | TDD-03A 至 03F 已实现 durable Reference、可信注销准入、Release 生命周期与并发门控；TDD-04A 已接 exact KSS/BFF 只读投影；TDD-06D/06E 已完成 Workspace rollback Release 预检与 caller expectation fencing；TDD-06F 已在真实 PostgreSQL CAS 竞争中验证单赢家。真实 verifier/reconciler、production rollback endpoint/演练、生产 artifact-retention adapter 和 lifecycle 命令接线仍待后续切片 |
| BRANCH-3 | 回滚 | 当前 Agent Version 需要回退 | 只选择绑定 queryable 或 deprecated Release 且持有 KSS reference 的既有 Published Agent Version；命令绑定确认时的 Active pointer | Active pointer 原子更新或稳定 conflict | retired/revoked Release 不可作为回滚目标；pointer 漂移不得自动采用 | P1 | TDD-06D/06E 已完成本地 Workspace、development HTTP 与 Dashboard 核心；TDD-06F 已验证 PostgreSQL pointer/audit 原子提交和失败回滚。Production 命令、真实 KSS 依赖演练及跨服务 lease 待后续切片 |

## 4. 核心业务规则

| 规则编号 | 业务域 | 规则说明 | 输入 | 输出 | 边界/例外 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| LOOP-001 | 权威 | KSS 是 Source、Source Version、Base 和 Release 的唯一逻辑数据权威 | KSS 命令 | KSS 资源 | ProofAgent 只保存外部不可变引用 | 已确认 |
| LOOP-002 | Agent 配置 | Draft KSS candidate 只表达 authoring intent，不可执行 | exact Release tuple | Draft revision | 不含凭据、Scorer 或 endpoint | 已确认 |
| LOOP-003 | 正式发布 | Formal Production Agent Candidate 必须根植于 exact Draft revision | Draft identity 与 revision | 可发布候选 | 不接受独立 manifest 或 mutable latest Draft | TDD-05A 至 05U 已实现 exact Candidate 到可恢复命令/只读 receipt 的受控纵向；TDD-05V 证明发布外探测也从 exact Draft revision 重新装配 Candidate。TDD-05W 通过 Workspace exact CAS 创建 Draft@14，并只规范化两个 audit path。其首次 probe 在 exact KSS Query 成功后 generic failure。TDD-05X 增加 secret-free stage diagnostics；TDD-05Y 关闭 production validation artifact port mismatch，并在取得具体授权后执行一次新 probe。该调用重放同一 succeeded Query，随后以 Evidence Admission stable code 失败，没有引用回答、validation artifact 或发布状态。TDD-05Z 为后续 failure.v2 增加 allowlist reason，未知事实仍不分类；本片无外部调用。后台 recovery、Grant lifecycle 和 cross-operator audit/listing 仍待处理 |
| LOOP-004 | 角色授权 | 首期使用 Knowledge Operator、Agent Editor、Release Operator 三个可叠加角色包；身份权限取角色并集 | trusted external role claims | 全局 named permissions 与审计 | 不做 per-Space ACL、negative grant、强制四眼或本地用户授权；服务端命令仍是授权权威 | 已确认 |
| LOOP-005 | 激活 | Knowledge 或 Draft 保存动作不得激活 Agent | 配置命令 | 配置状态变化 | 只有正式发布可更新 Active pointer | 已确认 |
| LOOP-006 | 失败处理 | exact Release、Grant、Secret、Scorer 或依赖异常时失败关闭 | 运行或发布请求 | 稳定失败结果 | 无 local/latest fallback | 已确认 |
| LOOP-007 | 外部连接 | KSS 拥有非敏感 Connection Profile 的版本化逻辑状态；Vault 拥有凭据值；部署拥有 connector、egress、trust root 和硬限制策略 | Profile Draft、Secret Handle、部署策略 | Published Profile revision | Worker 只解析通过部署策略准入的 exact revision；TDD-04B BFF 接受 versioned Secret Handle 引用但响应不返回 endpoint、Handle、egress/trust 或 raw problem | TDD-04B 本地验证；真实 adapter 与生产切换待完成 |
| LOOP-008 | Base 组合 | KSS 维护版本化、不可查询的 Base Draft；成员使用 `exact` 或 `latest_ready_at_preparation`，并在 Preparation 启动时一次性冻结 | exact Base Draft revision | immutable Knowledge Base Version 与 Preparation | Query 不读取 Draft/latest；Source 更新不自动发布或更新 Agent | TDD-04C 本地 BFF、TDD-04D one-shot execution runtime、TDD-04E controlled publication BFF、TDD-04F controlled cancellation BFF、TDD-04G bounded audit read BFF 与 TDD-04H exact-resource expiry BFF 已验证；常驻运行、自动过期调度及正式 Agent 发布责任待完成 |
| LOOP-009 | Release 退役 | deprecated 阻止新采用但保护既有运行；retired 需要零可执行引用和 retention；revoked 仅用于安全或严重数据问题并立即失败关闭；只读删除资格还需完整退役历史、零 active Reference 与 artifact-retention clear | exact Release、KSS reference/lifecycle facts、服务端 artifact-retention assessment、bounded reason、exact confirmation | lifecycle state、affected active Reference count、只读 eligibility/blockers 与命令审计 | 资格不是删除权限；revoked 保留 incident blocker；物理删除是后续独立命令并须重验 | TDD-03B 至 03F 已实现 application-only 生命周期与资格核心；TDD-04A 已实现 `knowledge_source.view` 保护的 exact KSS/BFF 只读投影。生产 artifact adapter、命令网络权限、明细投影/通知、物理删除与 ProofAgent 失败关闭接线待实现 |
| LOOP-010 | 引用权威 | 每个客户端在外部资源可执行前向 KSS 幂等注册 exact Release reference；只有 owning client 及服务端可信 verifier 证明 external resource 永久失去执行与回滚资格后才可注销；KSS 账本是普通退役和删除资格的本地引用权威 | client/resource/Release exact identity、trace-safe verification identity | durable active/deregistered Reference、资格计数或稳定拒绝 | 注册失败不激活；不确定或验证失败保留安全孤儿引用；后台 reconciler 不可按 TTL 盲删；deregistered 只保留历史且不阻断；emergency revoke 保留 Reference facts | TDD-03A 至 03F 已实现 KSS application-only lifecycle；TDD-05C 已实现 ProofAgent port 级 staging；TDD-05D 已实现 authenticated registration HTTP、concrete guarded registrar 与真实 PostgreSQL 纵向；TDD-05J 已实现 production-local 专用 Reference client Secret/identity bootstrap，并证明该身份没有 Query Grant；ProofAgent verifier、注销网络命令和后台 reconciler 待实现 |
| LOOP-011 | Preparation 状态 | `queued → running → ready → consumed`，失败分支为 `failed/cancelled/expired`；失败重试使用新 identity | exact Base Draft revision、Idempotency-Key | durable Preparation | 仅 unexpired ready 可消费一次；Worker claim 必须 lease/fence | 已确认 |
| LOOP-012 | Query Grant | KSS deployment policy 固定 runtime client、strategy、预算和 scope；operator-authenticated provisioning 只接受 exact Release，Space 由 KSS 反推 | exact Release | strict active Grant receipt | runtime/Reference credential 不可自授；ProofAgent adapter 必须拒绝 receipt、Release 或 Space 漂移；下游失败保留 exact policy-bounded Grant | TDD-05K application core、TDD-05L KSS HTTP/ProofAgent adapter、TDD-05M formal Control staging/composition、TDD-05N production-local policy/runtime bootstrap、TDD-05O explicit verifier 与 TDD-05R versioned runtime authority 本地验证；active v2 client 已对当前 exact Release 创建 1 条 Grant，并以同一 Grant 完成 2 次独立 Query。旧 client/Grant 保持原状且不再进入 active local composition；selective revoke/reconciliation、operator command audit 与生产联机证据待实现 |

## 5. 高严谨业务系统风险基线

| 维度 | 是否涉及 | 已知规则/证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑严谨性 | 是 | KSS Candidate Evidence 与 ProofAgent Admission 分离 | 无 | P1 |
| 金额与关键数值精度 | 间接 | 结构化数据保留类型，不由本流程改写业务值 | 数据质量审批规则待后续确认 | P2 |
| 交易与数据一致性 | 是 | Source/Release 不可变；Preparation 启动冻结 exact Version plan；TDD-02E 在一个 KSS PostgreSQL 事务提交 Release 与 consumed/expired；TDD-02F 原子提交 one-shot expired 与审计；TDD-02G 原子提交 queued/running → cancelled 与幂等收据/审计并 fence 旧 Worker；TDD-04E/04F/04H 分别复用同一 publication/cancellation/exact-expiry 事务；TDD-05F 以一个 Configuration UoW 执行 Draft check、Active CAS、Version/activation/audit 提交；TDD-05H 在同一最终 UoW 完成 success receipt，且 reservation 在外部调用前由独立短事务持久化；TDD-05S 以数据库时间 lease 和 monotonic fence 保证只有当前执行者可提交终态；TDD-05T 以当前 fenced claim 原子冻结 Candidate 摘要并保留首次 checkpoint | 后台 recovery process、自动过期调度与生产切换 | P1 |
| 状态流转 | 是 | TDD-03A 至 03F 已持久化 `active → deregistered` `published_agent_version` 引用，并原子实现 `queryable → deprecated → retired` 普通路径和 `queryable/deprecated → revoked` 紧急路径；retired/revoked 从 Catalog、完整性扫描和既有 Query authorization 中移除；只读 eligibility 不写 lifecycle state | ProofAgent verifier、后台 reconciler、生产 artifact-retention adapter、物理删除、受影响运行/回滚接线与重试运行责任 | P1 |
| 幂等与并发 | 是 | 长命令、Draft 保存和激活需要幂等/CAS；TDD-05H 以 `(actor subject, Idempotency-Key)` + path/body canonical fingerprint 持久化正式发布 receipt，并证明并发同键唯一创建者与终态不降级；TDD-05S 允许到期 exact replay 单一接管，复用稳定 Phase F/Version/Run/Reference identity，并拒绝 stale fence completion；TDD-05T 使并发 checkpoint 收敛到一个不可改绑摘要，并要求接管重新装配后精确匹配 | 后台 recovery process 与统一保留策略 | P1 |
| 权限与审计 | 是 | 三个粗粒度角色包映射到全局 named permissions，可叠加；TDD-04A 只读路径检查 `knowledge_source.view`；TDD-04B Profile/同步和 TDD-04C Draft/Preparation 的读取检查 `knowledge_source.view`、变更检查 `knowledge_source.edit`；TDD-04E publication、TDD-04F cancellation 与 TDD-04H expiry BFF 只接受 `knowledge_source.edit`；TDD-04G audit read 只接受 `knowledge_source.view`，严格校验 KSS wire/Scope，并把 actor 标为 `kss_service_operator`；TDD-05U command receipt read 要求 `agent.publish` 和创建者 actor subject 精确匹配，且隐藏 foreign-actor 资源 | KSS 当前记录 ProofAgent 服务 operator；终端操作者委托身份及 lifecycle/Reference 命令角色映射仍待实现 | P1 |
| 隐私与适用监管/合规 | 是 | 浏览器和审计不返回 secret/raw content | 数据分类、保留与删除负责人待确认 | P1 |
| 生产变更与回滚 | 是 | 正式发布必须候选绑定，回滚选择不可变版本 | KSS Release 退役与 Agent 回滚的协调策略 | P1 |

## 6. 影响范围

| 类型 | 对象 | 影响说明 | 风险等级 |
| --- | --- | --- | --- |
| KSS contract | management API、catalog、Connection Profile、synchronization、release application | 补齐版本化 Profile、任务资源、幂等和发布状态 | P1 |
| ProofAgent Control | Agent Configuration Workspace、formal publisher | 让正式候选消费 exact Draft revision | P1 |
| ProofAgent Delivery | KSS BFF、Agent publication API/CLI | 公开稳定、安全的管理和提交边界；按三类角色包执行服务端授权 | P1 |
| Dashboard | Knowledge 页面、Agent Detail、Publication 模块 | 展示任务、阻断和权威交接，不持有 secret | P1 |
| Persistence | KSS PostgreSQL Reference Ledger、ProofAgent Configuration UoW | 先注册 KSS reference、后执行本地发布/激活；不使用分布式事务 | P1 |
| Deployment | connector allowlist、Egress Policy、trust root、硬限制、Client Grant、Secret 与 Scorer 配置 | 部署级策略和 secret 值不能进入 Draft 或浏览器投影 | P1 |
| Release | Phase F、online smoke、candidate binding | 证据绑定 exact Draft 与 exact KSS Release | P1 |

## 7. 测试与发布关注点

| 关注项 | 类型 | 优先级 | 证据或说明 |
| --- | --- | --- | --- |
| Source → Base Draft → Base Version → Release → Agent Draft → Published Version identity | 端到端契约 | P1 | 每个阶段保留 exact identity、revision 和 digest |
| `latest_ready_at_preparation` 并发解析 | 并发 | P1 | 同一一致性视图只冻结一组 exact Source Version IDs |
| Draft revision 与 Release retire race | 并发 | P1 | 失败时不得发布或激活 |
| 浏览器 secret-free | 安全 | P1 | token、Secret Handle 值、endpoint 和 raw problem 不得投影 |
| 权限不可越权组合 | 授权 | P1 | Knowledge 编辑不能获得 Agent 激活能力 |
| 多角色权限并集 | 授权 | P1 | 单角色拒绝越界；多角色只累加对应 named permissions，不产生隐式 admin |
| 正式发布失败原子性 | 事务 | P1 | Phase F 或 smoke 失败不得改变 Active pointer |
| 回滚可执行性 | 恢复 | P1 | 目标版本的 exact KSS binding 必须仍可用 |
| 普通退役与紧急撤销 | 生命周期/安全 | P1 | deprecated 保护既有运行；retired 需零引用；revoked 立即失败关闭且不 fallback |
| reference 注册/激活失败矩阵 | 跨服务一致性 | P1 | 注册失败无激活；激活失败保留孤儿引用；对账失败继续保守保留 |
| Preparation state/race | 状态/并发 | P1 | idempotency fingerprint、lease takeover、stale fence、cancel/ready、expiry/publish、one-use CAS |

## 8. 架构问题关闭情况

| 结论 | 风险等级 | 说明 | 后续责任人 | 下一步 |
| --- | --- | --- | --- | --- |
| 当前无未决 P1 架构问题 | P1 | 已确认权威、Base composition、角色、Release lifecycle、Reference Ledger、Preparation 状态与正式发布候选；本地 Phase F preparation 已实现，但完整发布链仍未达到目标设计 | KSS、ProofAgent、Dashboard、测试与发布负责人 | 按 Scope TDD 切片实施；完成 Reference-first 正式发布、真实依赖和全部发布 Gate 前不得称 Production GO |
