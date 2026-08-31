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
| 当前状态 | `PARTIAL_VERIFICATION`：TDD-01A/01B 本地接线、TDD-02A 至 02G Preparation 核心、TDD-03A 至 03F Reference/lifecycle 核心、TDD-04A lifecycle/reference-summary 只读 BFF、TDD-04B Profile → Synchronization BFF、TDD-04C Base Draft save/exact read → Preparation start/status 同源 secret-free BFF、TDD-04D 可选 one-shot Preparation execution runtime、TDD-04E controlled Preparation publication BFF、TDD-04F controlled Preparation cancellation BFF、TDD-04G bounded Preparation audit read BFF、TDD-04H exact-resource Preparation expiry BFF、TDD-05A 至 05P 的 exact Draft/KSS/Profile 候选、Phase F、Reference、Query Grant、online smoke、publisher/command、production composition、production-local Query authority 与 read-only preflight 纵向，以及 TDD-05Q exact Draft Memory normalization 已有本地证据。当前 Draft@13 的 Formal Candidate 可只读装配，但 `publication_authorized=false`；旧 Release 的历史 Grant 冲突与后续发布 Gate 仍是独立阻断。后台 reconciler、真实外部 KSS/model 上游 online smoke 证据、stuck-command recovery/takeover、Query Grant selective revoke/reconciliation 与 operator command audit、Preparation 常驻执行进程、自动过期调度、deregistration/lifecycle 命令 BFF、终端操作者到 KSS audit 的委托身份链、生产 egress/TLS、artifact-retention adapter、物理删除、affected-reference 明细/通知、Dashboard 页面、生产 retention 配置和生产切换尚未完成 |

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
| MAIN-4 | 正式候选 | Release Operator 提交 exact Draft revision | 重验 Draft、Release、权限和部署级 Binding Profile | 形成 Formal Production Agent Candidate | 不接受 latest Draft、独立 manifest 或环境替代 Release | P1 | TDD-05A 已实现 application-only、无副作用的 exact Draft revision + live KSS catalog + strict deployment Profile 装配；TDD-05B 已生成 authority-approved、未持久化的 Phase F preparation；TDD-05C 已新增 Reference-first registrar port 与严格 staging；TDD-05D 已接 authenticated KSS HTTP 与 concrete guarded registrar；TDD-05F publisher core 已消费完整 exact chain；TDD-05H 已增加 `agent.publish` 权限入口、可信 actor 和部署注入 Profile 边界；TDD-05I 已由 production API 装配 concrete command，并要求专用 versioned Reference client credential；TDD-05J 已补 production-local Secret/identity bootstrap 与 Handle 隔离合同；TDD-05P 已增加同一 production composition 的只读预检；TDD-05Q 已经由既有 Contract validator/CAS/audit 把 exact Draft 从 12 推进到 13，并证明该 revision 可只读装配 Formal Candidate。本片仍为零发布/KSS 写入，不授权发布 |
| MAIN-5 | 发布激活 | Phase F 证据与在线 smoke 通过 | 冻结 Published Agent Version，并以 PostgreSQL CAS 激活 | Active Agent Version 更新 | 并发、审计、exact evidence、失败无状态改变 | P1 | TDD-05D 已证明 staging 可创建 durable active Reference；TDD-05E 已新增 exact online smoke Control qualification 与失败顺序；TDD-05F 已以最终单一 UoW 原子提交 Published Version、Active CAS 与 audit，并保留 strict formal evidence；TDD-05G 已接 governed execution concrete runner、exact artifact retention 与 cited evidence 统计；TDD-05H 已让 success receipt 与 Version/Active/audit 原子提交，并持久化 exact replay/failure；TDD-05I 已移除旧 manifest production CLI/composition 并使 production 缺 command 时启动失败；TDD-05J 已补 production-local 专用 Reference client Secret/identity bootstrap，并证明该身份不含 Query Grant；TDD-05K/05L 已补 runtime Query client exact-Release Grant core、operator transport 与 ProofAgent guarded adapter；TDD-05M 已让 formal publisher 在 Reference 后、smoke 前完成 candidate-bound Grant staging；TDD-05N 已让 checked-in production-local 装配同一 runtime client 的 immutable policy/bootstrap；TDD-05O 已增加显式 exact verifier，并证明保留卷冲突失败关闭、正向 exact Grant 重放和独立 Query。真实外部上游联机、Grant selective revoke/reconciliation、operator command audit 和 stuck-command recovery 待实现 |
| MAIN-6 | 运行使用 | Run 解析 Active Agent Version | exact KSS Query → Candidate Evidence → ProofAgent Admission | 引用回答或受治理失败结果 | 无 fallback、引用可回放、Admission 权威正确 | P1 | 已实现主体路径 |
| BRANCH-1 | 依赖失败 | KSS、Secret、Grant、Scorer 或 Release 不可用 | 失败关闭，不替换 Release 或走本地知识 | 稳定 blocker/problem | 负向依赖矩阵 | P1 | 已确认 |
| BRANCH-2 | 并发与过期 | Draft revision 变化，或 Release deprecated/retired/revoked | 新发布拒绝 deprecated/retired/revoked；既有 deprecated binding 保持运行；retired/revoked 查询失败关闭 | 无旧候选误激活或 fallback | KSS 内 registration/deregistration/lifecycle serialization，跨服务保守引用 | P1 | TDD-03A 至 03F 已实现 durable Reference、可信注销准入、`queryable → deprecated → retired` 普通路径、`queryable/deprecated → revoked` 紧急路径、并发门控和只读删除资格；TDD-04A 已接 exact KSS/BFF 只读生命周期与 Reference 汇总。真实 verifier/reconciler、生产 artifact-retention adapter、命令接线和 ProofAgent runtime/rollback 接线待后续切片 |
| BRANCH-3 | 回滚 | 当前 Agent Version 需要回退 | 只选择绑定 queryable 或 deprecated Release 且持有 KSS reference 的既有 Published Agent Version | Active pointer 原子更新 | retired/revoked Release 不可作为回滚目标 | P1 | 目标已确认；实现待切片 |

## 4. 核心业务规则

| 规则编号 | 业务域 | 规则说明 | 输入 | 输出 | 边界/例外 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| LOOP-001 | 权威 | KSS 是 Source、Source Version、Base 和 Release 的唯一逻辑数据权威 | KSS 命令 | KSS 资源 | ProofAgent 只保存外部不可变引用 | 已确认 |
| LOOP-002 | Agent 配置 | Draft KSS candidate 只表达 authoring intent，不可执行 | exact Release tuple | Draft revision | 不含凭据、Scorer 或 endpoint | 已确认 |
| LOOP-003 | 正式发布 | Formal Production Agent Candidate 必须根植于 exact Draft revision | Draft identity 与 revision | 可发布候选 | 不接受独立 manifest 或 mutable latest Draft | TDD-05A 至 05P 已实现 exact candidate、Phase F、Reference、Grant、smoke、publisher/command、production composition 和 read-only preflight 纵向；TDD-05Q 已在既有 Draft Contract 校验、CAS 与审计边界内收敛 Memory，并使 Draft@13 成功生成绑定 exact Release 的 Formal Candidate digest。本地装配结果固定 `publication_authorized=false`；真实外部上游联机、旧 Release Grant 冲突、Grant selective revoke/reconciliation、operator command audit 和 stuck-command recovery 仍待处理 |
| LOOP-004 | 角色授权 | 首期使用 Knowledge Operator、Agent Editor、Release Operator 三个可叠加角色包；身份权限取角色并集 | trusted external role claims | 全局 named permissions 与审计 | 不做 per-Space ACL、negative grant、强制四眼或本地用户授权；服务端命令仍是授权权威 | 已确认 |
| LOOP-005 | 激活 | Knowledge 或 Draft 保存动作不得激活 Agent | 配置命令 | 配置状态变化 | 只有正式发布可更新 Active pointer | 已确认 |
| LOOP-006 | 失败处理 | exact Release、Grant、Secret、Scorer 或依赖异常时失败关闭 | 运行或发布请求 | 稳定失败结果 | 无 local/latest fallback | 已确认 |
| LOOP-007 | 外部连接 | KSS 拥有非敏感 Connection Profile 的版本化逻辑状态；Vault 拥有凭据值；部署拥有 connector、egress、trust root 和硬限制策略 | Profile Draft、Secret Handle、部署策略 | Published Profile revision | Worker 只解析通过部署策略准入的 exact revision；TDD-04B BFF 接受 versioned Secret Handle 引用但响应不返回 endpoint、Handle、egress/trust 或 raw problem | TDD-04B 本地验证；真实 adapter 与生产切换待完成 |
| LOOP-008 | Base 组合 | KSS 维护版本化、不可查询的 Base Draft；成员使用 `exact` 或 `latest_ready_at_preparation`，并在 Preparation 启动时一次性冻结 | exact Base Draft revision | immutable Knowledge Base Version 与 Preparation | Query 不读取 Draft/latest；Source 更新不自动发布或更新 Agent | TDD-04C 本地 BFF、TDD-04D one-shot execution runtime、TDD-04E controlled publication BFF、TDD-04F controlled cancellation BFF、TDD-04G bounded audit read BFF 与 TDD-04H exact-resource expiry BFF 已验证；常驻运行、自动过期调度及正式 Agent 发布责任待完成 |
| LOOP-009 | Release 退役 | deprecated 阻止新采用但保护既有运行；retired 需要零可执行引用和 retention；revoked 仅用于安全或严重数据问题并立即失败关闭；只读删除资格还需完整退役历史、零 active Reference 与 artifact-retention clear | exact Release、KSS reference/lifecycle facts、服务端 artifact-retention assessment、bounded reason、exact confirmation | lifecycle state、affected active Reference count、只读 eligibility/blockers 与命令审计 | 资格不是删除权限；revoked 保留 incident blocker；物理删除是后续独立命令并须重验 | TDD-03B 至 03F 已实现 application-only 生命周期与资格核心；TDD-04A 已实现 `knowledge_source.view` 保护的 exact KSS/BFF 只读投影。生产 artifact adapter、命令网络权限、明细投影/通知、物理删除与 ProofAgent 失败关闭接线待实现 |
| LOOP-010 | 引用权威 | 每个客户端在外部资源可执行前向 KSS 幂等注册 exact Release reference；只有 owning client 及服务端可信 verifier 证明 external resource 永久失去执行与回滚资格后才可注销；KSS 账本是普通退役和删除资格的本地引用权威 | client/resource/Release exact identity、trace-safe verification identity | durable active/deregistered Reference、资格计数或稳定拒绝 | 注册失败不激活；不确定或验证失败保留安全孤儿引用；后台 reconciler 不可按 TTL 盲删；deregistered 只保留历史且不阻断；emergency revoke 保留 Reference facts | TDD-03A 至 03F 已实现 KSS application-only lifecycle；TDD-05C 已实现 ProofAgent port 级 staging；TDD-05D 已实现 authenticated registration HTTP、concrete guarded registrar 与真实 PostgreSQL 纵向；TDD-05J 已实现 production-local 专用 Reference client Secret/identity bootstrap，并证明该身份没有 Query Grant；ProofAgent verifier、注销网络命令和后台 reconciler 待实现 |
| LOOP-011 | Preparation 状态 | `queued → running → ready → consumed`，失败分支为 `failed/cancelled/expired`；失败重试使用新 identity | exact Base Draft revision、Idempotency-Key | durable Preparation | 仅 unexpired ready 可消费一次；Worker claim 必须 lease/fence | 已确认 |
| LOOP-012 | Query Grant | KSS deployment policy 固定 runtime client、strategy、预算和 scope；operator-authenticated provisioning 只接受 exact Release，Space 由 KSS 反推 | exact Release | strict active Grant receipt | runtime/Reference credential 不可自授；ProofAgent adapter 必须拒绝 receipt、Release 或 Space 漂移；下游失败保留 exact policy-bounded Grant | TDD-05K application core、TDD-05L KSS HTTP/ProofAgent adapter、TDD-05M formal Control staging/composition、TDD-05N production-local policy/runtime bootstrap 与 TDD-05O explicit verifier 本地验证；当前保留卷已证明历史 Grant 冲突失败关闭，以及同一 exact Grant 重放两次独立 Query。selective revoke/reconciliation、operator command audit 与生产联机证据待实现 |

## 5. 高严谨业务系统风险基线

| 维度 | 是否涉及 | 已知规则/证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑严谨性 | 是 | KSS Candidate Evidence 与 ProofAgent Admission 分离 | 无 | P1 |
| 金额与关键数值精度 | 间接 | 结构化数据保留类型，不由本流程改写业务值 | 数据质量审批规则待后续确认 | P2 |
| 交易与数据一致性 | 是 | Source/Release 不可变；Preparation 启动冻结 exact Version plan；TDD-02E 在一个 KSS PostgreSQL 事务提交 Release 与 consumed/expired；TDD-02F 原子提交 one-shot expired 与审计；TDD-02G 原子提交 queued/running → cancelled 与幂等收据/审计并 fence 旧 Worker；TDD-04E/04F/04H 分别复用同一 publication/cancellation/exact-expiry 事务；TDD-05F 以一个 Configuration UoW 执行 Draft check、Active CAS、Version/activation/audit 提交；TDD-05H 在同一最终 UoW 完成 success receipt，且 reservation 在外部调用前由独立短事务持久化 | 自动过期调度、stuck-command recovery、既有直接入口与正式 publisher runtime 切换 | P1 |
| 状态流转 | 是 | TDD-03A 至 03F 已持久化 `active → deregistered` `published_agent_version` 引用，并原子实现 `queryable → deprecated → retired` 普通路径和 `queryable/deprecated → revoked` 紧急路径；retired/revoked 从 Catalog、完整性扫描和既有 Query authorization 中移除；只读 eligibility 不写 lifecycle state | ProofAgent verifier、后台 reconciler、生产 artifact-retention adapter、物理删除、受影响运行/回滚接线与重试运行责任 | P1 |
| 幂等与并发 | 是 | 长命令、Draft 保存和激活需要幂等/CAS；TDD-05H 以 `(actor subject, Idempotency-Key)` + path/body canonical fingerprint 持久化正式发布 receipt，并证明并发同键唯一创建者与终态不降级 | stuck `in_progress` 的可信恢复/接管与统一保留策略 | P1 |
| 权限与审计 | 是 | 三个粗粒度角色包映射到全局 named permissions，可叠加；TDD-04A 只读路径检查 `knowledge_source.view`；TDD-04B Profile/同步和 TDD-04C Draft/Preparation 的读取检查 `knowledge_source.view`、变更检查 `knowledge_source.edit`；TDD-04E publication、TDD-04F cancellation 与 TDD-04H expiry BFF 只接受 `knowledge_source.edit`；TDD-04G audit read 只接受 `knowledge_source.view`，严格校验 KSS wire/Scope，并把 actor 标为 `kss_service_operator` | KSS 当前记录 ProofAgent 服务 operator；终端操作者委托身份及 lifecycle/Reference 命令角色映射仍待实现 | P1 |
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
