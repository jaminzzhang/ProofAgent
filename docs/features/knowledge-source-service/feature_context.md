# Knowledge Source Service Feature Context

## 1. 需求基本信息

| 字段 | 内容 |
| --- | --- |
| 需求名称 | 将 Hybrid Knowledge Sources 拆分为独立运行的 Knowledge Source Service |
| Feature ID | `knowledge-source-service` |
| 需求来源 | 当前 Goal 与用户确认记录；`docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` |
| 实施计划 | `docs/superpowers/plans/2026-08-11-knowledge-source-service.md` |
| 所属版本 | V1；具体发布版本未指定 |
| 业务、研发、测试、发布负责人 | 未提供；不在本地实现中推定 |
| 当前状态 | `VERIFIED_LOCAL`；2026-08-12 的 Goal 验收已通过，不代表生产发布批准 |

## 2. 需求目标与范围

| 目标 | 说明 | 验收口径 |
| --- | --- | --- |
| 独立服务 | Knowledge Source Service 拥有独立运行入口、进程角色和逻辑数据权限 | API、Query Executor、Worker、Scheduler、Migration 角色可独立组合；类生产部署使用独立 PostgreSQL 数据库、非超级用户登录凭证和 S3 namespace；生产依赖缺失时失败关闭 |
| 异构知识处理 | 分析、版本化和存储结构化与非结构化数据 | 格式矩阵、失败隔离、不可变 Source/Base Version 与原子 Release 测试通过 |
| 标准查询 | 为多个 Agent 提供 exact-Space、exact-Release 的 Candidate Evidence 查询 | Knowledge Query 契约、授权、幂等、状态机、取消、过期和 typed result 测试通过 |
| 混合与 Agentic 检索 | 支持 Lexical、Dense、Sparse、Structured 及显式的有界 Agentic 检索 | 检索质量、lineage、预算、逐轮 Gate、取消和提示注入测试通过 |
| ProofAgent 接入 | ProofAgent 通过远程端口查询，并通过显式组合的已批准评分器继续负责 Evidence Admission 和最终答案 | 端到端测试证明候选证据可进入既有 Admission 流程；缺少评分器或评分无效时失败关闭；服务不可越过权限边界 |

### 范围内

| 范围项 | 说明 | 依据 |
| --- | --- | --- |
| 服务与运行边界 | 一个产品和镜像，隔离 API、Query Executor、Worker、Scheduler、Migration 角色 | ADR-0207 |
| 空间与授权 | V1 单组织 Knowledge Space；一个 Space 可授权多个 Agent；查询不跨 Space | ADR-0196、ADR-0197 |
| 摄取与快照 | 文档、表格、关系数据、HTTP JSON、对象清单等格式先物化后查询 | 设计第 8 节、ADR-0199 |
| 版本与发布 | 不可变 Source Version、Base Version 和原子 Knowledge Base Release | ADR-0195、ADR-0205 |
| 查询与结果 | `POST /v1/knowledge-queries`、查询、取消和 typed Evidence Group | ADR-0203、ADR-0206 |
| 检索 | Lexical、learned Sparse、Dense、Structured；前三者以 Weighted RRF 融合 | ADR-0200、ADR-0201、ADR-0203 |
| Agentic | 显式启用、预算约束、逐轮 Plan Gate、固定 Space/Release/scope | ADR-0202 |
| ProofAgent 适配 | 远程 Candidate Service、稳定幂等键、显式 Admission Scorer 组合缝、无本地生产回退 | 设计第 17 节；Knowledge/Evidence 领域决策 |
| 类生产部署 | KSS 五个角色使用同一固定镜像；外部查询只通过 `https://proof-agent.localhost:8444`；KSS 数据库由专用非超级用户角色拥有；OpenSearch、projection encoder、Agentic controller 和 OCR 只通过内部 TLS 网关 | `docker-compose.production-local.yml`、`docker/production-local/nginx.conf` |

### 范围外与非目标

| 范围项 | 排除原因 | 影响 |
| --- | --- | --- |
| Evidence Admission、事实裁决、冲突解决、最终答案 | 这些权限属于 ProofAgent Control Plane | KSS 只能返回 Candidate Evidence 与 retrieval lineage |
| 查询时直连外部数据库或 HTTP API | 会破坏可重放性、版本绑定和稳定引用 | 外部数据必须先生成不可变快照 |
| 跨组织或跨 Space 查询 | V1 的隔离边界已收敛为单组织、单 Space | 联邦检索需要后续 ADR 和安全模型 |
| Agentic 外部工具调用或权限扩展 | Agentic 只改善已授权范围内的检索覆盖 | 不提供浏览、写操作、Admission 或答案工具 |
| 用本地实现作为生产故障回退 | 与逻辑数据权威和失败关闭规则冲突 | 生产依赖故障必须返回稳定失败 |

## 3. 设计树

| 节点 | 类型 | 触发条件或输入 | 处理方案 | 输出或状态变化 | 验证点 | 风险等级 | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ROOT | 业务目标 | Agent 需要查询异构、版本化知识 | 独立 KSS 处理摄取、存储、分析和查询 | 标准 Candidate Evidence API 可供 ProofAgent 使用 | 全部验收矩阵 | P1 | 已关闭 |
| MAIN-1 | 查询受理 | 认证 client、Space、exact Release、query、`Idempotency-Key` | 校验契约、grant、scope、release 和预算，创建 Knowledge Query | `queued` 资源及 durable work | API、权限、幂等测试 | P1 | 已关闭 |
| MAIN-2 | 查询执行 | Query Executor 领取可执行查询 | Plan Gate 后执行允许的 lane，融合并固化结果 | `running` → 终态；可重试领取 | 状态机、lease、fencing 测试 | P1 | 已关闭 |
| MAIN-3 | 摄取与版本 | 管理面提交文档或外部数据快照 | 保存原始对象，解析、规范化、构建 Base Version | 不可变版本和可诊断产物 | 格式、完整性、重放测试 | P1 | 已关闭 |
| MAIN-4 | 原子发布 | Base Version 已成功构建 | 一次可见性事务发布 exact Release | 查询只能观察完整 Release | 并发发布、失败恢复测试 | P1 | 已关闭 |
| MAIN-5 | 混合检索 | 已通过 Gate 的 single-pass plan | 运行 Lexical、Sparse、Dense 与可选 reranker；Structured 单独执行 | typed `evidence_groups` 与 lineage | 排名、类型、引用测试 | P1 | 已关闭 |
| MAIN-6 | Agentic 检索 | 请求显式选择 Agentic 且 grant 允许 | 每轮评估覆盖、选择允许 lane、再次过 Gate，并扣减预算 | 有界多轮 Candidate Evidence 或稳定失败 | 预算、取消、注入、权限不扩展测试 | P1 | 已关闭 |
| MAIN-7 | ProofAgent 接入 | ProofAgent retrieval action | 远程适配器提交、等待并轮询 Knowledge Query，再由显式组合的已批准评分器生成 Evidence Admission 输入 | 既有 Admission 流程继续执行；未配置评分器时，候选保持不可准入 | adapter、契约、端到端测试 | P1 | 已关闭 |
| BRANCH-1 | 幂等冲突 | 同一 client 和 key 重放 | 相同 fingerprint 返回同一资源；不同 fingerprint 返回 `409` | 无重复 Query 或工作项 | 并发重放测试 | P1 | 已关闭 |
| BRANCH-2 | 权限拒绝 | grant、Space、Release 或过滤范围不匹配 | Gate 拒绝且不执行任何 retrieval lane | 稳定 Problem Details 与审计事件 | 隔离、越权和 side-channel 测试 | P1 | 已关闭 |
| BRANCH-3 | 取消与期限 | client 取消或 execution deadline 到期 | 持久化意图；executor 在安全点停止；区分 `cancelled` 与 `expired` | 单一合法终态 | race、重试、恢复测试 | P1 | 已关闭 |
| BRANCH-4 | 依赖失败 | PostgreSQL、对象存储、搜索或模型依赖失败 | 分类重试或失败关闭；不切换本地权威 | 可诊断失败且无部分可见状态 | fault injection 测试 | P1 | 已关闭 |
| BRANCH-5 | 恶意内容 | 文档或查询包含提示注入文本 | 内容始终视为数据；planner 仅输出受约束计划并逐轮过 Gate | 无工具调用、权限扩展或答案输出 | prompt-injection suite | P1 | 已关闭 |
| BOUND-1 | 权限边界 | 检索生成候选结果 | KSS 停止于 Candidate Evidence | ProofAgent 执行 Admission、冲突处理和答案生成 | schema 与集成断言 | P1 | 已关闭 |

## 4. 核心业务规则

| 规则编号 | 规则说明 | 边界或例外 | 状态 |
| --- | --- | --- | --- |
| KSS-R01 | 一个 Knowledge Query 只绑定一个 Knowledge Space 和一个 exact Knowledge Base Release | 不接受 `latest`；Agentic 期间不可切换 | 已确认 |
| KSS-R02 | 一个 Space 可服务多个 Agent，但 V1 不跨组织或 Space 检索 | grant 仍按 client、Space 和能力约束 | 已确认 |
| KSS-R03 | KSS 只返回 Candidate Evidence，不执行 Evidence Admission 或最终回答 | 无内部 fallback 可绕过该边界 | 已确认 |
| KSS-R04 | `Idempotency-Key` 的作用域为认证 client；完整请求和契约版本进入 fingerprint | 同 key、不同 fingerprint 返回 `409` | 已确认 |
| KSS-R05 | Lexical、Sparse、Dense 是独立排序 lane，并使用 Weighted RRF 融合 | Structured 不进入 RRF | 已确认 |
| KSS-R06 | Structured 结果保留字段、类型、运算和集合语义 | 不伪装为通用相关性分数 | 已确认 |
| KSS-R07 | Agentic 必须显式启用并受轮数、模型调用、候选数、token 和时长预算限制 | 预算具体默认值属于实施校准，不改变 hard-bound 规则 | 已确认 |
| KSS-R08 | 外部数据库、API 和对象清单在查询前物化为不可变 Source Version | 查询时不得访问 live upstream | 已确认 |
| KSS-R09 | Release 只在全部必需投影就绪后原子可见 | 失败构建不可被查询 | 已确认 |
| KSS-R10 | KSS 排序与 lane-native score 不得直接变成 Evidence Admission Score | ProofAgent 只能通过显式组合、已批准且输出 0–1 有限值的评分器生成 Admission 输入；缺失或非法值失败关闭 | 已确认 |

## 5. 高严谨业务系统风险基线

| 维度 | 是否涉及 | 已知规则或证据 | 待确认问题 | 风险等级 |
| --- | --- | --- | --- | --- |
| 领域业务逻辑严谨性 | 是 | Knowledge/Evidence 权限边界及 ADR-0192 至 ADR-0207 | 无阻断项 | P1 |
| 金额与关键数值精度 | 否 | 本功能不定义金额规则；Structured 必须保留源类型 | 特定业务数据精度由数据集 schema 约束 | P3 |
| 交易与数据一致性 | 是 | 不可变版本、原子 Release、outbox、fencing | 无阻断项 | P1 |
| 状态流转 | 是 | Query、ingestion、release 均有显式状态机 | 无阻断项 | P1 |
| 幂等与并发 | 是 | client-scoped fingerprint、lease 与 fencing | 无阻断项 | P1 |
| 权限与审计 | 是 | service grant、Space scope、Plan Gate、稳定审计事件 | 无阻断项 | P1 |
| 隐私与适用监管或合规 | 是 | 最小化日志、内容隔离、受控删除和保留 | 具体数据集监管标签由部署方提供 | P1 |
| 生产变更与回滚 | 是 | shadow、pilot、gated cutover；生产无本地回退 | 正式阈值和发布批准不属于本地编码结论 | P1 |

## 6. 影响范围

| 类型 | 对象 | 影响说明 | 风险等级 |
| --- | --- | --- | --- |
| 新服务 | `knowledge_source_service/` 与独立运行入口 | 新增 contracts、application、domain、ports、adapters 和 process roles | P1 |
| 公共 API | `/v1/knowledge-queries` 与管理 API | 新增稳定资源、错误和幂等语义 | P1 |
| 数据 | PostgreSQL schema、S3-compatible objects、search projections | 新增独立逻辑权威、迁移和重建路径 | P1 |
| ProofAgent | bootstrap、knowledge provider registry 和 remote adapter | 生产查询改为远程服务；Control Plane 权限不变 | P1 |
| 交付 | image、process commands、CI、migration、runbook | 新增多角色部署和故障恢复证据 | P1 |
| 测试 | unit、contract、integration、fault、quality、security、E2E | 增加完整验收矩阵 | P1 |

## 7. 测试与发布关注点

| 关注项 | 类型 | 优先级 | 证据或说明 |
| --- | --- | --- | --- |
| API strictness 与字段稳定性 | contract | P1 | 设计第 12 节 |
| exact Space/Release 与 grant 隔离 | security | P1 | ADR-0196、ADR-0197 |
| 幂等、lease、fencing 和状态 race | concurrency | P1 | 设计第 15 节 |
| 原子 Release 与重建一致性 | persistence | P1 | ADR-0205 |
| Citation 可重放与 content hash | provenance | P1 | ADR-0204 |
| Typed Structured 语义 | contract/data | P1 | ADR-0194、ADR-0203 |
| Agentic hard budgets 与 prompt injection | security/model | P1 | ADR-0202 |
| ProofAgent Admission 权限不迁移 | integration | P1 | ADR-0192 |
| Shadow 差异与回滚阈值 | release | P1 | 设计第 18 节；阈值待部署评审 |

## 8. 待确认问题

下列校准项不阻断第一批 TDD 切片，也不得被描述为已批准的生产参数。

| 问题 | 风险等级 | 影响 | 建议确认人 | 期望材料 |
| --- | --- | --- | --- | --- |
| 各环境的 Agentic 默认预算和硬上限 | P2 | 容量、成本和超时行为 | 技术与运营负责人（未指定） | 负载测试与成本数据 |
| 正式 SLO、shadow 差异阈值和 cutover 门槛 | P2 | 发布判断 | 产品、SRE、发布负责人（未指定） | 试运行指标与回滚演练 |
| OCR、embedding、learned Sparse 和 reranker 的具体 provider | P2 | 质量、成本和许可 | 技术负责人（未指定） | provider 评估记录 |
| 数据集级保留、删除和监管标签 | P2 | 合规策略 | 数据与安全负责人（未指定） | 数据分类和适用政策 |
