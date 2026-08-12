# Knowledge Source Service Scope、准入与 TDD 计划

本文件将已确认设计映射为可独立验证的 TDD 切片。详细技术设计和任务顺序分别以
`docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` 和
`docs/superpowers/plans/2026-08-11-knowledge-source-service.md` 为准。

## 1. 建议结论

| 项 | 内容 |
| --- | --- |
| 建议结论 | `TDD_INPUT_READY` |
| 最高风险等级 | P1 |
| 一句话依据 | 目标、权限边界、主流程、关键状态、异常分支、验收矩阵、ADR 和纵向切片均有已确认记录，无未关闭 P0/P1 设计阻断项 |
| 下一步建议 | 从公共 Knowledge Query contract 的单一 observable behavior 开始 `hicode:tdd`；本结论不代表已实现或获发布批准 |

## 2. 依据与输入缺口

| 材料 | 来源 | 是否读取 | 关键证据 | 缺口 |
| --- | --- | --- | --- | --- |
| Goal 与用户确认 | 当前任务历史 | 是 | 独立服务、多格式、多 Agent、Agentic、ProofAgent 接入、精准 API 命名 | 无阻断项 |
| 总体设计 | `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` | 是 | 权威边界、数据模型、API、检索、运行、迁移、验收 | 生产参数仍需运行数据校准 |
| 实施计划 | `docs/superpowers/plans/2026-08-11-knowledge-source-service.md` | 是 | Task 0 至 Task 14 的依赖顺序和退出条件 | 无阻断项 |
| 领域与 ADR | `docs/domain/knowledge-evidence/`、ADR-0192 至 ADR-0207 | 是 | 稳定术语和难逆决策 | 无阻断项 |
| 项目规则 | `AGENTS-COMMON.md`、`docs/rules/hicode-coding-rules.md` | 是 | 生产权威、安全、TDD 和证据要求 | 无阻断项 |
| 代码图与代码入口 | 现有 Graphify 图及 `proof_agent/` | 是 | bootstrap、resolver、provider、retrieval、local index seam | Graphify 未重建；实现时以代码为准 |

## 3. 需求准入评审

| 项 | 内容 |
| --- | --- |
| 准入结论 | `NO_BLOCKING_GAPS` |
| 需求分析输入 | Goal、连续设计确认、总体设计、16 个 ADR、领域上下文、实施计划、当前知识调用链 |
| 证据缺口 | Agentic/SLO/provider/retention 的生产校准参数；均为 P2，不改变第一批 contract 和 authority slices |
| 高风险评审 | 状态、幂等、并发、事务、权限、审计、隐私、生产回滚均已进入设计树和测试矩阵 |

## 4. 需求分析与范围边界

| 项 | 内容 |
| --- | --- |
| 需求目标 | 独立运行的 KSS 对异构知识执行摄取、分析、版本化、存储和查询，并通过标准 Candidate Evidence API 服务 ProofAgent 等多个 Agent |
| 范围内 | 服务运行边界、逻辑数据权威、多格式摄取、版本与 Release、四类检索、Agentic、权限、审计、ProofAgent 远程适配 |
| 范围外 | Evidence Admission、事实和冲突裁决、最终回答、live upstream query、跨 Space 查询、Agentic 外部工具 |
| 非目标 | 用文档或本地测试声称生产就绪；用本地 provider 作为生产故障回退；一次性迁移全部旧路径 |
| 验收标准 | 设计第 20 节矩阵全部通过，且 ProofAgent E2E 证明 Candidate Evidence 可查询、引用、Admission，并保持权限边界 |
| `feature_context.md` 更新 | 已创建 |
| ADR 处理 | ADR-0192 至 ADR-0207 已创建；当前切片无需新增 ADR |

## 5. 设计树方案

| 节点 | 类型 | 触发条件或输入 | 处理方案 | 输出或状态变化 | 范围边界 | 验证点 | 风险等级 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | Agent 查询异构知识 | KSS 成为查询和知识数据的独立逻辑权威 | Candidate Evidence 标准服务 | 不接管 ProofAgent Control Plane | 端到端验收 | P1 |
| MAIN-1 | 公共 contract | client 创建、读取或取消 Query | strict typed resource、Problem Details、idempotency | durable Knowledge Query | exact Space 和 Release | schema、HTTP contract | P1 |
| MAIN-2 | 服务执行 | queued query | claim、Gate、retrieve、persist terminal result | 可恢复状态机 | process roles 隔离 | lease/fencing/race | P1 |
| MAIN-3 | 摄取和版本 | operator 提交源或 snapshot | stream、hash、parse、normalize、project | immutable Base Version | 不在 query 时访问 upstream | format/replay/failure | P1 |
| MAIN-4 | Release | Base Versions 就绪 | atomic publish | exact Release 可查询 | 失败版本不可见 | transaction/concurrency | P1 |
| MAIN-5 | 混合检索 | gated query plan | 3 ranked lanes + typed Structured | evidence groups + lineage | Structured 不进 RRF | golden/ranking/schema | P1 |
| MAIN-6 | Agentic | 显式请求并获授权 | bounded rounds、per-round Gate、cancel checks | coverage 改善或稳定终止 | 不调用工具、不扩权、不回答 | budget/injection/cancel | P1 |
| MAIN-7 | ProofAgent | retrieval action | remote provider、wait/poll、mapping | 候选证据进入 Admission | 无 direct DB read 或 prod fallback | adapter/E2E | P1 |
| BRANCH-1 | 幂等 | key replay/concurrent create | canonical fingerprint | same resource 或 `409` | client scoped | concurrency contract | P1 |
| BRANCH-2 | 权限 | grant/scope mismatch | deny before execution | stable failure + audit | 不泄露资源存在性 | isolation suite | P1 |
| BRANCH-3 | 故障 | dependency/worker/process failure | retry policy、reconciliation、fail closed | no partial authority | 不静默降级 | fault injection | P1 |
| BRANCH-4 | 生命周期 | cancel/deadline/result retention | legal state transitions | `cancelled`、`expired`、availability metadata | 区分执行过期与结果保留 | state/race/time | P1 |
| BRANCH-5 | 恶意输入 | source/query prompt injection | content-as-data、typed planner、Gate | 无权限或工具副作用 | 不信任模型输出 | adversarial suite | P1 |

## 6. 澄清问题队列

| 问题 | 状态 | 推荐答案 | 推荐理由 | 影响 | 建议确认人 |
| --- | --- | --- | --- | --- | --- |
| 一个 Knowledge Space 是否支持多个 Agent | 已关闭 | 支持；grant 独立约束 | 复用知识并保持 service-side isolation | Space/client 数据模型 | 用户已确认 |
| 是否支持 Agentic 检索 | 已关闭 | 显式、有界、逐轮 Gate | 改善覆盖且不扩大权限 | planner、budget、审计 | 用户已确认 |
| 查询接口如何命名 | 已关闭 | `KnowledgeQuery` 与 `/v1/knowledge-queries` | 资源语义精确，避免 job/search 混淆 | 公共 contract | 用户已确认 |
| 是否使用 live upstream query | 已关闭 | 否；先生成不可变快照 | 保证重放、引用和 exact Release | ingestion/snapshot | 已确认设计 |
| Agentic 默认预算和正式 SLO | 待负责人确认，不阻断首批切片 | 使用受配置约束的保守开发默认值；不得称为生产批准值 | 可先验证 hard-bound 行为 | capacity/config | 技术与运营负责人未指定 |
| provider 与保留策略 | 待负责人确认，不阻断端口和 contract | 先定义端口、能力和 fail-closed contract | 避免过早绑定供应商 | adapters/deployment | 技术与数据负责人未指定 |

## 7. 关键规则与影响范围

| 对象 | 影响说明 | 证据来源 | 确认状态 | 风险等级 |
| --- | --- | --- | --- | --- |
| `KnowledgeQuery` | 公共异步资源；状态和结果可查询、可取消 | ADR-0206、设计第 12 节 | 已确认 | P1 |
| Idempotency | client + key + full request contract fingerprint | 设计第 12.8 节 | 已确认 | P1 |
| Space/Release | 每次 query 均 exact-bound，Agentic 期间冻结 | ADR-0195 至 ADR-0198 | 已确认 | P1 |
| Candidate Evidence | KSS 最终权限边界 | ADR-0192、ADR-0204 | 已确认 | P1 |
| Structured | 保留 typed semantics，独立 evidence group | ADR-0194、ADR-0203 | 已确认 | P1 |
| Ranked fusion | Lexical、Sparse、Dense 使用 Weighted RRF | ADR-0200、ADR-0201 | 已确认 | P1 |
| Persistence | PostgreSQL authority、S3 immutable objects、rebuildable search | AGENTS-COMMON、设计第 7 节 | 已确认 | P1 |
| ProofAgent | 只通过远程 adapter 查询，Admission 仍在 Control Plane | 设计第 17 节 | 已确认 | P1 |

## 8. 风险与阻断建议

| 风险 | 等级 | 证据 | 建议动作 | 建议确认人 |
| --- | --- | --- | --- | --- |
| Contract 漂移导致多个 Agent 不兼容 | P1 | 新增公共 API | 先冻结 strict schema 和 golden fixtures，再写执行器 | 研发与 API 评审人未指定 |
| 幂等或 fencing 缺陷产生重复/陈旧结果 | P1 | durable async state | 并发失败测试先行，状态改变保持原子 | 研发与数据评审人未指定 |
| 权限或检索过滤泄露跨 Space 数据 | P1 | 多 Agent 共享 Space、service grants | deny-before-retrieve，构造负向隔离矩阵 | 安全评审人未指定 |
| Release 部分可见或引用不可重放 | P1 | 多投影构建 | immutable hashes、atomic publish、rebuild test | 数据评审人未指定 |
| 模型提示注入扩大 Agentic 行为 | P1 | untrusted source/query content | typed plan、allow-list、per-round Gate、无工具 | 安全评审人未指定 |
| 一次性大爆炸替换现有知识路径 | P1 | 既有 ProofAgent provider chain | tracer bullet、shadow、pilot、gated cutover | 发布负责人未指定 |

当前无 P0/P1 设计阻断项。P1 表示实现和 Review 必须保留对应测试证据，不表示风险已被生产负责人接受。

## 9. 推荐设计树方案与取舍

| 方案 | 是否推荐 | 主干逻辑 | 分支处理 | 范围边界 | 收益 | 代价或风险 | 不选原因 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 独立 KSS + ProofAgent remote port + shadow cutover | 是 | KSS 独占知识权威，ProofAgent 保留 Admission | durable queue、fail closed、可回滚 binding | Candidate Evidence 边界 | 清晰权限、独立扩展、可多 Agent 复用 | 新服务与运维复杂度 | — |
| 继续嵌入 ProofAgent 进程 | 否 | 保留现有 local/blended providers | 进程内降级 | 无独立数据权威 | 短期改动少 | 无法实现独立服务目标，扩展和隔离受限 | 与 Goal 和 ADR-0192 冲突 |
| KSS 与 ProofAgent 同时直读数据存储 | 否 | 两侧共享 schema/index | 各自处理失败 | 权威重叠 | 迁移看似直接 | 契约、权限、迁移和回滚不可控 | 与 ADR-0193 冲突 |

## 10. 设计树到 TDD 任务计划

所有任务共享以下输入和约束：

- 输入：Feature Context、总体设计、实施计划、ADR-0192 至 ADR-0207、项目规则。
- 范围外：未在当前任务列出的下一 slice，不以 placeholder 冒充实现。
- 实现方式：每次只增加一个 observable behavior；先记录 RED，再写最小 GREEN，最后 REFACTOR。
- 停止条件：发现会改变权限边界、公开 contract、状态含义或数据权威的未决规则；发现需要真实生产凭证、未脱敏数据或发布权限。

| 任务 | 对应节点 | 目标与范围内对象 | TDD 起点 | 最小验证 | 独立回滚边界 |
| --- | --- | --- | --- | --- | --- |
| T0 公共契约 | MAIN-1、BRANCH-1、BRANCH-4 | request/resource/result/evidence/problem schemas 与路由语义 | strict schema、必需 idempotency、same/mismatch replay 失败测试 | contract tests + golden JSON | 仅 contracts 与 fixtures |
| T1 服务基础 | ROOT、MAIN-2 | 独立 package、app、role commands、health/readiness、composition | API 可启动且 production 缺依赖失败的测试 | process smoke + composition tests | 新 distribution/entry points |
| T2 Query admission | MAIN-1、BRANCH-2 | Space、client grant、scope intersection、create/read/cancel | exact Release、cross-Space denial、atomic enqueue 测试 | API + repository integration | admission application slice |
| T3 durable executor | MAIN-2、BRANCH-3、BRANCH-4 | state machine、outbox、claim、lease、fencing、cancel/reconcile | stale lease 与 cancel race 失败测试 | PostgreSQL integration + fault tests | executor and queue adapters |
| T4 version/release | MAIN-3、MAIN-4 | Source Version、Base Version、Release schema 与 atomic publish | immutability、partial publish、concurrent release 测试 | migration + transaction tests | versioning bounded context |
| T5 Markdown tracer | MAIN-3 至 MAIN-5 | Markdown upload → parse → evidence units → lexical query | citation/hash/replay E2E 失败测试 | one-format end-to-end test | Markdown profile adapter |
| T6 layout/OCR | MAIN-3 | PDF/DOCX/PPTX/image/HTML layout profiles 与 OCR | table/list/page citation and malformed-file tests | fixture matrix | format adapters |
| T7 Structured | MAIN-3、MAIN-5 | CSV/XLSX/Parquet/JSON typed datasets 与 bounded query | type fidelity、unsafe operation、result-group tests | structured golden suite | structured engine adapter |
| T8 external snapshots | MAIN-3、BRANCH-3 | PostgreSQL、HTTP JSON、object manifest connectors | no-live-query、cursor/retry/hash tests | connector contract + snapshot replay | connector adapters |
| T9 ranked retrieval | MAIN-5 | Lexical/Sparse/Dense indexes、Weighted RRF、optional reranker | deterministic fusion、lane degradation、lineage tests | quality corpus + determinism | ranked retrieval module |
| T10 planner/Agentic | MAIN-6、BRANCH-2、BRANCH-5 | planner、Gate、coverage evaluator、budgets、cancel | per-round Gate、hard limit、injection、no-answer schema tests | adversarial + bounded-loop suite | agentic application module |
| T11 admin/source API | MAIN-3、MAIN-4 | Space/Base/Source/Release mutation API、multipart、optimistic concurrency | malformed stream、idempotency、stale revision tests | API + transaction tests | management delivery module |
| T12 ProofAgent | MAIN-7、BOUND-1 | remote provider、binding、wait/poll、mapping、stable key | no direct DB/local prod fallback、Admission boundary tests | adapter + ProofAgent E2E | remote provider and config |
| T13 shadow/pilot | MAIN-7、BRANCH-3 | dual-run comparison、metrics、pilot binding、rollback | mismatch recording and reversible switch tests | shadow evaluation fixture | deployment binding only |
| T14 hardening/cutover | 全部 | load、security、backup/rebuild、runbook、old authority removal gate | dependency outage、restore、quality threshold tests | full acceptance matrix | gated deployment changes |

| 项 | 内容 |
| --- | --- |
| 任务计划结论 | `TDD_INPUT_READY` |
| 下一步路由 | `hicode:tdd`，从 T0 第一项 strict request behavior 开始 |
| 未覆盖设计树节点 | 无；生产校准参数保留为 P2 待确认项，不在本地实现中宣称已批准 |

## 11. TDD 输入与测试重点

| 设计树节点 | 场景 | 类型 | 优先级 | 数据要求 | 对应任务 |
| --- | --- | --- | --- | --- | --- |
| MAIN-1 | 创建、重放、读取、取消 Query | contract/state | P1 | 合法/非法 golden payloads、固定时钟与 ID | T0、T2 |
| MAIN-2 | claim、执行、完成、恢复 | concurrency | P1 | PostgreSQL 测试库、可控 lease clock | T1、T3 |
| MAIN-3/4 | 摄取、版本、原子发布 | persistence | P1 | 小型合法/损坏 fixtures、fault injection | T4 至 T8、T11 |
| MAIN-5 | lane 与 typed composition | quality/contract | P1 | 版本固定的小型 golden corpus | T5、T7、T9 |
| MAIN-6 | bounded Agentic | security/model | P1 | deterministic fake model、注入 corpus | T10 |
| MAIN-7/BOUND-1 | ProofAgent remote flow | integration/authority | P1 | ASGI/HTTP fake、既有 Admission fixtures | T12、T13 |
| BRANCH-1 至 BRANCH-5 | 错误、越权、race、依赖失败、恶意内容 | negative/fault | P1 | 并发 barriers、fakes、redacted diagnostics | 各对应任务 |

## 12. ADR 判断

| 项 | 内容 |
| --- | --- |
| 是否需要 ADR | 当前无需新增 |
| 判断理由 | 难逆的权限、权威、版本、检索、Agentic、API 和部署取舍已由 ADR-0192 至 ADR-0207 覆盖 |
| 涉及决策点 | 若实现必须改变公共字段、状态含义、exact Release、Space 隔离、Evidence Admission 边界或逻辑数据权威，应停止 TDD 并更新/新增 ADR |

## 13. 知识与上下文更新

| 目标文档 | 更新类型 | 内容摘要 | 处理方式 | 确认状态 |
| --- | --- | --- | --- | --- |
| `docs/DOMAIN_KNOWLEDGE.md` | 新建索引 | 路由到领域上下文、总体设计和 ADR | 已写入 | 基于已确认设计 |
| `docs/PROJ_CONTEXT.md` | 新建索引 | 当前代码 seam 与 Feature 状态 | 已写入 | 基于仓库证据 |
| `feature_context.md` | 新建 | 目标、边界、设计树、风险和影响范围 | 已写入 | `TDD_INPUT_READY` |
| `scope-plan.md` | 新建 | 准入、取舍和 TDD 任务映射 | 已写入 | `TDD_INPUT_READY` |

`TDD_INPUT_READY` 仅表示证据足以进入测试驱动实现，不替代代码 Review、安全评审、发布审批或生产验证。
