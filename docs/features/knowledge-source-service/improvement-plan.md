# KSS 简化与多源整合查询完善规划

更新时间：2026-08-20

## 1. 结论

| 项 | 结论 |
| --- | --- |
| 建议结论 | `SPLIT_REQUIRED` |
| 最高风险等级 | P1 |
| 推荐方向 | 继续以「一个 Query 绑定一个 exact Knowledge Base Release」为核心；一个 Release 可以冻结多个 Source Version，从而完成多数据源和外部知识库快照的整合查询 |
| 不推荐方向 | V1 不让 Query 同时携带多个 Release，也不在查询时临时直连多个外部知识库 |
| 第一实施切片 | 先用契约测试固化现有多 Source Release 行为，再收敛 Source Connector、Release Composer 和 Query Pipeline；不先扩展 Agentic、OCR 或新的排序算法 |

[KNOWN | HIGH] KSS 已经具备多数据源整合的核心数据模型：
`KnowledgeBaseReleaseSnapshot.knowledge_source_version_ids` 可以冻结多个 Source
Version，发布逻辑会拒绝空集合、重复版本、未知版本和跨 Space 版本。查询引擎读取
Release 的全部成员，并将文档与数据集结果返回为带来源和引用的 Candidate
Evidence。证据见
`knowledge_source_service/domain/knowledge_catalog.py`、
`knowledge_source_service/application/knowledge_releases.py` 和
`tests/contract/knowledge_service/test_hybrid_retrieval_tracer.py`。

[KNOWN | HIGH] 当前 Query 只接受一个 `knowledge_base_release_id`，Client Grant 也只授权
一个 exact Release。这个限制是权限、版本和重放边界，不是多数据源能力缺失。证据见
`knowledge_source_service/contracts/knowledge_query.py` 和
`knowledge_source_service/adapters/postgres/access_control.py`。

[INFERRED | HIGH] 本规划建议将「外部知识库」解释为一种可同步的 Knowledge Source：先通过
Connector 捕获为不可变 Source Version，再与其他 Source Version 一起发布为一个聚合
Release。若业务要求查询时实时访问多个外部知识库，应单独形成 Federation ADR；该能力
不进入本轮简化核心。

## 2. 需求解释与边界

### 2.1 一句话目标

[INFERRED | HIGH] 建议 KSS 通过统一 Source 接入、不可变版本和聚合 Release，为多个 Agent 提供
简单、可授权、可重放的多源整合查询，并只返回 Candidate Evidence。

### 2.2 核心术语

| 术语 | 本规划中的含义 |
| --- | --- |
| Knowledge Space | 单次查询的组织和授权隔离边界 |
| Knowledge Source | 一个可独立同步和版本化的数据来源；可以是文件、数据集、API、数据库快照、对象清单或外部知识库快照 |
| Source Version | 一次不可变捕获结果，包含规范化内容、引用和处理 lineage |
| Knowledge Base | 一组 Source 的可管理组合定义；不直接作为运行时可变查询目标 |
| Knowledge Base Release | Knowledge Base 的不可变发布快照，冻结全部 exact Source Version |
| Knowledge Query | 对一个 exact Release 的异步查询资源 |
| Candidate Evidence | KSS 的唯一查询输出；ProofAgent 仍负责 Evidence Admission 和最终答案 |

### 2.3 范围内

- 统一文件、结构化数据、外部快照和外部知识库快照的 Source Connector 边界。
- 让 Knowledge Base 的 Source 组合可读、可审查、可发布，而不是要求操作员手工拼接一组不透明 Version ID。
- 保留一个 Query 对一个 exact Release 的契约。
- 在一个 Release 内跨多个文档 Source 进行相关性检索和融合。
- 将结构化结果保留为 typed Evidence Group，不强行转换成相关性排名。
- 统一来源、版本、引用、内容摘要和检索 lineage。
- 收敛应用层、HTTP 路由和 PostgreSQL Catalog 中的重复实现。

### 2.4 范围外与非目标

- 不让 KSS 执行 Evidence Admission、事实裁决、冲突解决或最终回答。
- 不在 Query 执行时访问 live upstream；外部数据先物化为 Source Version。
- 不支持跨 Space 或跨组织检索。
- 不把 Agentic、OCR、reranker 或更多模型能力作为多源查询成立的前提。
- 不用一个通用分数混合结构化记录与相关性候选。
- 不以本地测试或规划文档声明生产就绪。

## 3. 现状梳理

### 3.1 运行链路

```text
文件 / 数据集 / HTTP / PostgreSQL / Object Manifest / 外部知识库快照
                              │
                              ▼
                 Source intake / synchronization
                              │
                              ▼
                immutable Source Version + artifacts
                              │
                              ▼
          Knowledge Base Release（冻结多个 Source Version）
                              │
                              ▼
       authorize → plan → retrieve → fuse/group → persist result
                              │
                              ▼
          Candidate Evidence + Citation + Retrieval Lineage
                              │
                              ▼
          ProofAgent Evidence Admission 与最终答案（KSS 范围外）
```

### 3.2 已实现能力

| 能力 | 现状 | 证据 |
| --- | --- | --- |
| 多 Source Release | [KNOWN | HIGH] 已实现；Release 接受多个 exact Source Version | `application/knowledge_releases.py` |
| 文档与数据集混合查询 | [KNOWN | HIGH] 已实现；Markdown 与 CSV 可共享一个 Release，并分别返回 relevance 与 structured group | `tests/contract/knowledge_service/test_hybrid_retrieval_tracer.py` |
| 多格式管理接入 | [KNOWN | HIGH] 已实现文档、CSV、JSON、XLSX、Parquet 等入口 | `delivery/management_http.py` |
| 外部数据同步 | [KNOWN | HIGH] 已实现 HTTP JSON、PostgreSQL 和 object manifest 的先物化路径 | `application/synchronization_executor.py`、`application/external_snapshots.py` |
| exact Release 授权 | [KNOWN | HIGH] 已实现 Client Grant、预算和 strategy 收窄 | `adapters/postgres/access_control.py` |
| 多 Release Query | [KNOWN | HIGH] 未实现，且当前契约和 ADR 明确绑定一个 exact Release | `contracts/knowledge_query.py`、ADR-0210 |
| 外部知识库实时联邦 | [KNOWN | HIGH] 未实现；当前规则要求查询前物化外部数据 | `docs/features/knowledge-source-service/feature_context.md` |

### 3.3 代码结构与复杂度

[COMPUTED | HIGH] KSS 当前约有 14,691 行 Python 源码。其中 application 约 5,725
行、adapters 约 5,081 行，二者合计占主要复杂度。按
`rg --files ... -g '*.py' | xargs wc -l` 统计，最大的文件包括：

| 文件 | 行数 | 主要问题 |
| --- | ---: | --- |
| `adapters/postgres/knowledge_catalog.py` | 1,457 | Catalog、序列化、完整性校验和多类资源持久化集中在一个模块 |
| `application/document_intake.py` | 1,106 | 多格式分支、规范化、引用构建和发布耦合 |
| `application/hybrid_retrieval.py` | 1,079 | 文档排名、结构化查询、结果组装和 lineage 集中 |
| `delivery/management_http.py` | 860 | 合同、路由、格式分派和应用组装混在一个 HTTP 模块 |
| `application/dataset_intake.py` | 823 | CSV、XLSX、Parquet 的读取、类型解析和发布存在平行路径 |
| `bootstrap/processes.py` | 597 | 配置解析、依赖装配、角色循环和 readiness 集中 |

[COMPUTED | MED] 本次 Graphify 本地结构图包含 1,018 个节点、3,223 条边和 58 个
community。Release Catalog、Dataset Parsing Helpers 和 Document Intake Pipeline 的
cohesion 分别为 0.05、0.08 和 0.08；`StrictContract`、
`PublishedDatasetSourceVersion`、`KnowledgeQueryResult` 等对象跨越大量 community。
这些指标只用于定位耦合热点，不构成代码缺陷或发布证据。图谱位于
`services/knowledge-source-service/graphify-out/`。

### 3.4 主要问题

| 问题 | 判断 | 风险 |
| --- | --- | --- |
| 能力面大于核心目标 | [INFERRED | HIGH] OCR、Agentic、四类检索、完整性巡检和多格式细节同时暴露在主组合路径，使“多源查询”不容易独立理解和验证 | P2 |
| Intake 按格式增长 | [KNOWN | HIGH] HTTP 层和应用层为不同格式维护平行分支；新增格式通常需要修改中央路由 | P2 |
| Retrieval 存在双引擎叠加 | [KNOWN | HIGH] `IndexedHybridKnowledgeRetrievalEngine` 先执行内存 baseline，再替换 relevance group，导致结果组装语义分布在两个实现 | P2 |
| Knowledge Base 缺少可管理组合 | [KNOWN | HIGH] 发布接口直接接收 `knowledge_source_version_ids`；Base 本身没有清晰的 Source membership/spec 工作流 | P2 |
| 外部知识库语义不明确 | [INFERRED | HIGH] 现有 Snapshot Connector 能覆盖数据 API 和数据库，但没有统一说明“外部知识库”应作为快照 Source 还是 live provider | P1 |
| 运行角色对使用者过多 | [INFERRED | MED] 五个角色有明确隔离价值，但内部 composition 和工作循环可以共用一个 job runtime，减少代码路径 | P2 |
| 文档状态漂移 | [KNOWN | HIGH] Service README 曾写 `VERIFIED_LOCAL`，而 Feature Index 和 cutover 证据为 `PARTIAL_VERIFICATION`；`DOMAIN_KNOWLEDGE.md` 还引用了不存在的 `docs/domain/CONTEXT-MAP.md` | P2 |

## 4. 推荐目标架构

### 4.1 保留五个核心资源

[INFERRED | HIGH] 建议对外领域模型只保留 `Space`、`Source`、`SourceVersion`、
`BaseRelease` 和 `Query` 五个核心资源。Knowledge Base 的 Draft/Spec 是管理辅助对象，
不成为第二个运行时权威。

```text
Space
 ├─ Source ── SourceVersion ─┐
 ├─ Source ── SourceVersion ─┼─ BaseRelease ── Query ── CandidateEvidence[]
 └─ Source ── SourceVersion ─┘
```

### 4.2 Source Connector

[INFERRED | HIGH] 建议所有来源通过一个 capture 边界进入系统：

```text
SourceConnector.capture(SourceSpec, Cursor?)
  -> CapturedSourceVersion
     - original artifact references
     - canonical document units or structured records
     - source revision observation
     - processing lineage
```

Connector 只负责捕获和规范化，不负责跨 Source 排名、Admission 或回答。建议的 V1
Connector family：

- `upload`：Markdown、text、PDF、office、image、CSV、JSON、XLSX、Parquet。
- `http_snapshot`：有界 HTTPS JSON 快照。
- `postgres_snapshot`：只读、可重复的 relation 快照。
- `object_manifest`：精确对象版本清单。
- `knowledge_base_snapshot`：通过受信任适配器导出外部知识库的文档、chunk、citation
  和 upstream revision；仍然落为 KSS Source Version。

[INFERRED | HIGH] 建议 Source Connector 使用注册表分派。新增 Connector 时，不应修改 Query
contract、Query Executor 或结果合同。

### 4.3 Release Composer

[DECISION | HIGH] KSS 使用版本化 `KnowledgeBaseDraft`/Release Composer：

1. 管理员在 Base Draft 中选择 Source，每次 Preparation 提交 exact Draft revision。
2. 每个 Source 指定版本选择策略：exact version 或 `latest_ready_at_preparation`。
3. Preparation 启动事务在一致性视图中解析并冻结 exact Source Version ID，创建 immutable Knowledge Base Version。
4. Composer 校验同一 Space、无重复成员、全部 ready、授权与必要投影完整。
5. 异步 Preparation 完成后，经一次短事务发布 immutable Release；Query 仍只看到 exact Release ID。

`latest_ready_at_preparation` 只允许在 Preparation 启动时解析，绝不能在 Query 执行时解析。新 Source Version 只产生管理面的升级提示，不自动创建 Release、更新 Agent Draft 或激活 Agent。该目标模型已由 ADR-0214 接受；当前直接 Release API 在切换完成前仍是实现事实。

### 4.4 Query Pipeline

[INFERRED | HIGH] 建议将 Query 主链收敛为六步：

1. `Admit`：认证 client，解析 exact Release Grant，冻结有效 scope 和预算。
2. `Load`：读取 Release Manifest 和 exact Source Version 元数据。
3. `Plan`：根据 Source capability 和请求约束选择允许的 retrieval lane。
4. `Retrieve`：各 lane 返回统一的内部 Candidate 和 typed Structured Result。
5. `Compose`：文档候选执行确定性融合；结构化结果保留独立 group。
6. `Persist`：固化 Result、引用、来源、版本、plan digest 和预算使用。

[INFERRED | HIGH] 建议以 `single_pass` 为核心路径。`agentic` 只包装同一个 Pipeline，并在每轮
重新经过 Plan Gate；它不能成为普通多源查询的必需依赖。

### 4.5 内部模块收敛

```text
contracts/             公开 Query、Result、Problem 合同
domain/                Source、Release、Query、Evidence 不变量
application/
  source_capture.py    Connector 编排与 Source Version 发布
  release_composer.py  Base membership 解析与 exact Release 发布
  query_pipeline.py    Admit/Load/Plan/Retrieve/Compose/Persist
  jobs.py              query、sync、integrity 的通用 fenced job runtime
ports/
  connectors.py        SourceConnector
  catalog.py           Source/Release authority
  retrieval.py         lane 与 projection 能力
  jobs.py              queue、lease、fencing
adapters/
  connectors/          upload、HTTP、PostgreSQL、object、external KB
  postgres/            按 source/release/query/grant/job 拆分 repository
  s3/                   immutable artifacts
  opensearch/           rebuildable projection
delivery/
  query_http.py         Agent Query API
  catalog_http.py       Space/Source/Base/Release 管理 API
  sync_http.py          同步资源 API
bootstrap/             统一 composition；角色只选择启用的 queue/route
```

[INFERRED | MED] 生产部署仍可以按 API、Query Worker、Knowledge Worker、Scheduler 和
Migration 隔离进程，但内部共享一个 composition root 和 fenced job runtime。是否减少
外部进程角色属于 ADR-0207 的变更，本轮不默认执行。

## 5. 多知识库整合策略

### 5.1 推荐：聚合 Release

[INFERRED | HIGH] 建议将本地数据源和外部知识库都建模为 Source，在同一 Space 内发布一个聚合
Release。Query 继续使用一个 target ID。

收益：

- 授权对象、幂等 fingerprint 和查询 lineage 保持简单。
- Release 能精确重放，引用不会因上游更新而漂移。
- 文档候选可以在一个确定性排名空间中融合。
- 外部依赖故障发生在同步阶段，不在用户查询关键路径临时放大。

代价：

- 数据存在同步延迟。
- KSS 需要保存或引用快照产物。
- 只提供 live query、不能导出的外部知识库无法进入核心模式。

### 5.2 延期：实时 Federation

[INFERRED | HIGH] 只有在外部知识库不能快照且业务明确接受不可完全重放、上游权限差异、
查询期依赖故障和跨 provider 排名校准时，才设计实时 Federation。该模式至少需要新 ADR，
并单独定义：

- 多 upstream 的授权交集与拒绝语义。
- upstream revision observation 和不可重放标记。
- required/advisory failure mode。
- provider-local score 与跨源融合规则。
- 超时、部分结果、审计和数据泄露边界。

## 6. 设计树

| 节点 | 触发条件 | 处理 | 结果 | 验证点 | 风险 |
| --- | --- | --- | --- | --- | --- |
| ROOT | Agent 需要查询多个来源 | 用一个 exact aggregate Release 承载多个 Source Version | 一个 Query 返回统一且可追溯的 Candidate Evidence | 多源 E2E | P1 |
| MAIN-1 | 新建或更新 Source | Connector capture 并发布 immutable Source Version | 可独立同步的版本 | Connector contract | P1 |
| MAIN-2 | 管理员组合 Base | Base Spec 选择 Source 和版本策略 | 可审查 Draft | CAS、权限、同 Space | P1 |
| MAIN-3 | 发布 Base | Composer 解析 exact versions 并原子发布 | immutable Release | 并发、失败恢复、manifest | P1 |
| MAIN-4 | Agent 查询 | 授权后执行统一 Query Pipeline | typed Evidence Groups | exact Release、budget、lineage | P1 |
| BRANCH-1 | Source 同步失败 | 保留上一 ready Version；不发布不完整 Release | 无部分可见状态 | fault test | P1 |
| BRANCH-2 | Source 跨 Space 或无权 | 发布或查询前拒绝 | 无检索 side effect | isolation matrix | P1 |
| BRANCH-3 | 文档与结构化结果共存 | 文档融合；structured 独立 group | 不丢失 typed semantics | mixed query contract | P1 |
| BRANCH-4 | 外部 KB 只能 live query | 不自动降级为核心 Source | 明确 `unsupported` 或进入 Federation ADR | negative contract | P1 |
| BRANCH-5 | 索引或模型不可用 | 核心依赖按 Release capability 失败关闭 | 稳定 Problem Details | dependency fault | P1 |

## 7. 分期实施规划

整体目标必须拆分；每个切片均采用 RED → GREEN → REFACTOR。

### Phase A：冻结简单核心

| 任务 | 目标 | TDD 起点 | 验收 |
| --- | --- | --- | --- |
| KSS-S1 多源行为保护 | 固化「多个 Source Version → 一个 Release → 一个 Query」 | 增加文档、结构化数据、外部快照共同发布与查询的失败测试 | 结果含全部适用来源、exact Release、citation 和 lineage |
| KSS-S2 核心契约说明 | 在 OpenAPI 和 README 中明确单 Release、多 Source 语义 | Contract golden 先体现缺失说明或字段约束 | Query 不新增 `release_ids`；未知字段继续拒绝 |
| KSS-S3 External KB 定义 | 待产品边界确认后定义 `knowledge_base_snapshot` Connector capability；不实现 live federation | 确认后补 Connector conformance contract | 未确认前保持 `BLOCKED_SCOPE`；确认后能表达 upstream revision、citation、content hash 和失败语义 |

### Phase B：收敛接入与发布

| 任务 | 目标 | TDD 起点 | 验收 |
| --- | --- | --- | --- |
| KSS-S4 Connector Registry | 用一个 registry 分派所有 capture adapter | 新 Connector 不修改中央 HTTP 分支的架构测试 | 上传、HTTP、PostgreSQL、object manifest 通过同一 contract suite |
| KSS-S5 Release Composer | 让 Base 可管理 Source membership，并在发布时冻结 exact versions | Draft CAS、跨 Space、重复成员、非 ready 成员失败测试 | Release manifest 确定、原子、可重放 |
| KSS-S6 管理 API 拆分 | 将 catalog、intake、sync、release 路由拆为独立模块 | OpenAPI golden 和现有 API 回归 | 无公共行为漂移；模块不互相导入 adapter 细节 |

### Phase C：收敛查询实现

| 任务 | 目标 | TDD 起点 | 验收 |
| --- | --- | --- | --- |
| KSS-S7 Query Pipeline | 建立 Admit/Load/Plan/Retrieve/Compose/Persist 明确阶段 | characterization tests 固化当前结果 | executor 只依赖一个 Pipeline port |
| KSS-S8 Retrieval Lane | 消除 baseline 执行后替换结果的双引擎语义 | indexed 与 non-indexed golden corpus | 公共 Result 一致；每个 lane 有独立 adapter contract |
| KSS-S9 Result Composer | 集中 Candidate、group、ranking 和 lineage 组装 | 多文档 Source + structured dataset 混合测试 | 文档跨 Source 融合；structured 不进入 RRF |

### Phase D：收敛持久化与运行

| 任务 | 目标 | TDD 起点 | 验收 |
| --- | --- | --- | --- |
| KSS-S10 Repository 拆分 | 按 Source、Release、Query、Grant、Job 拆分 PostgreSQL Catalog | repository contract 与真实 PostgreSQL 测试 | 事务边界明确；Result artifact 使用不会被 stale worker 占用的 staging/content-addressed identity |
| KSS-S11 Fenced Job Runtime | 复用 claim、heartbeat、fence、retry 和 terminal transition | Query 与 Sync 的 stale worker、过期未接管及外部写入测试 | 角色可隔离部署；过期 worker 不能提交状态、占用 Result artifact 或发布可见 Source Version |
| KSS-S12 Composition 收敛 | 将配置解析、adapter construction、role loop 分层 | composition tests | 生产依赖缺失继续失败关闭，无本地 fallback |

### Phase E：质量与生产门禁

| 任务 | 目标 | TDD 起点 | 验收 |
| --- | --- | --- | --- |
| KSS-S13 多源质量基线 | 建立跨 Source 去重、排名和 citation 覆盖数据集 | 固定小型 corpus | 指标可重复；阈值由评审后的运行数据确定 |
| KSS-S14 授权与审计 | 验证 Source membership、Grant、scope 与 lineage 一致 | 越权、资源存在性、删改和 replay 负向测试 | deny-before-retrieve；审计不泄露内容 |
| KSS-S15 生产闭环 | 完成 scorer、grant、secret、readiness、shadow、pilot 和 recovery 证据 | release Gate 缺失测试 | 只在全部正式 Gate 通过后更新生产状态 |

## 8. 验收标准

### 8.1 功能验收

- 一个 Base Release 可以冻结多个不同 Source 的 exact Source Version。
- 同一次 Query 可以检索多个文档 Source，并返回确定性融合顺序。
- 同一次 Query 可以同时返回 relevance group 与 structured group。
- 每条 Candidate 都包含 Source、Source Version、Release、citation、content hash 和
  retrieval lineage。
- 外部知识库快照与文件、数据库快照遵循同一 Source Version contract。
- Query request 只需要一个 exact Release ID，不暴露存储、索引或 provider 细节。

### 8.2 简洁性验收

- 新增 Source Connector 不修改 Query Pipeline 和公开 Result contract。
- 新增 intake 格式不在管理 HTTP 路由中增加新的业务分支。
- Query Result 的组装只有一个权威实现。
- Release membership 的解析和校验只有一个权威实现。
- Query、Sync 和 Integrity 的 lease/fencing 规则来自同一个 job runtime。
- 生产角色可以独立扩缩容，但不复制 composition 和状态机。

### 8.3 安全与一致性验收

- Query 始终固定一个 Space 和一个 exact Release。
- Release 不允许跨 Space 成员或部分可见。
- 外部依赖凭证只在对应 Worker/Connector adapter 边界解析。
- 外部知识库不可快照时，系统不静默退化为 live federation。
- KSS 只返回 Candidate Evidence；ProofAgent Admission 边界不变。

## 9. 风险与停止条件

| 风险或缺口 | 等级 | 停止条件或动作 |
| --- | --- | --- |
| 业务实际要求实时多知识库联邦 | P1 | 停止 KSS-S3，先确认 Federation ADR、授权和不可重放语义 |
| Base Spec 改变现有管理 API 或持久化权威 | P1 | 先更新设计记录和 OpenAPI contract，再进入 TDD |
| 重构改变 Candidate Evidence 排名或 typed semantics | P1 | 先建立 characterization corpus；差异必须被明确批准 |
| 合并 job runtime 弱化角色隔离或 fencing | P1 | 保留现有角色边界，不以减少代码为由降低 fail-closed 行为 |
| 生产 SLO、容量或质量阈值缺少数据 | P2 | 只定义测量和 Gate，不编造阈值 |

## 10. ADR 判断

| 决策 | ADR 结论 |
| --- | --- |
| 多 Source 组成一个 exact Release | [KNOWN | HIGH] 已被现有设计和实现覆盖，无需新 ADR |
| 外部知识库先快照为 Source Version | [INFERRED | MED] 与 ADR-0199 一致；实现前应确认产品边界并补充 Connector capability |
| Query 同时接收多个 Release | [INFERRED | HIGH] 不推荐；若采用，必须修改 ADR-0195、ADR-0197 和 ADR-0210 |
| 查询时实时 Federation | [INFERRED | HIGH] 需要新 ADR |
| 减少生产进程角色 | [INFERRED | HIGH] 需要更新 ADR-0207；本规划只复用内部 runtime，不默认减少角色 |

## 11. 输入缺口与建议确认

当前只有一个会改变产品边界的问题：

> 「多个知识库」是否包含只能实时查询、无法导出或快照的第三方知识库？

[INFERRED | MED] 建议默认答案为「不包含」：核心模式要求先快照。如果答案为「包含」，整体规划
仍可保留，但 `knowledge_base_snapshot` 之外必须新增独立 Federation 设计树，且本文件的
`SPLIT_REQUIRED` 结论不变。

## 12. 证据与文档状态

| 文档或产物 | 本次处理 |
| --- | --- |
| `docs/features/knowledge-source-service/improvement-plan.md` | 新建；记录现状、目标架构、设计树、分期任务和验收标准 |
| `docs/features/knowledge-source-service/feature_context.md` | 增加 2026-08-20 简化目标与边界说明 |
| `docs/features/knowledge-source-service/scope-plan.md` | 增加本完善规划的 Scope 结论和路由 |
| `services/knowledge-source-service/README.md` | 统一当前状态为 `PARTIAL_VERIFICATION` |
| `docs/DOMAIN_KNOWLEDGE.md` | 修正 Context Map 路径 |
| `services/knowledge-source-service/graphify-out/` | 新建本地导航图；1,018 nodes、3,223 edges、58 communities；本次语义抽取计量显示 0 input/0 output tokens，原因是子任务未返回可写入图谱的 token usage |

`SPLIT_REQUIRED` 表示本目标需要按独立切片推进，不代表实现被批准、风险被接受或生产发布
获准。

## 13. 2026-08-20 审查与修正追踪

| ID | 等级 | 发现 | 状态 | 修正或后续动作 |
| --- | --- | --- | --- | --- |
| KSS-REV-001 | P1 | [KNOWN | HIGH] Query 与同步任务都采用“先查幂等键、再插入”；并发请求可能在唯一约束处失败，未回读已提交的胜者 | `FIXED_LOCAL` | 唯一约束冲突后按 client/operator 与 key 回读；相同 fingerprint 返回精确重放，不同 fingerprint 保持 `409` |
| KSS-REV-002 | P1 | [KNOWN | HIGH] `save_claim` 只校验 owner 与 fencing token，租约过期但尚未接管时仍能保存 | `FIXED_LOCAL` | Repository protocol 显式接收 `now`；内存与 PostgreSQL 均要求保存时 `lease_expires_at > now` |
| KSS-REV-003 | P1 | [KNOWN | HIGH] Query Result artifact 在 PostgreSQL 最终 fence 校验前写入；[INFERRED | HIGH] stale worker 可能遗留孤儿对象，固定 object key 还可能阻塞胜者写入不同结果 | `OPEN_DESIGN` | 纳入 KSS-S10/S11：先定义 content-addressed/staged Result identity，再以 live fence 原子绑定元数据；增加 stale writer fault test |
| KSS-REV-004 | P1 | [KNOWN | HIGH] Synchronization Worker 在最终 `save_claim` 前已调用 intake 并发布 Source Version；[INFERRED | HIGH] 失去租约的 worker 可能留下未被同步资源承认的可见版本 | `OPEN_DESIGN` | 纳入 KSS-S11：将 capture/staging 与 fence-aware publish 分开；terminal commit 前不得产生未授权 catalog visibility |
| KSS-DOC-001 | P2 | [KNOWN | HIGH] 未经用户或 ADR 确认的推荐方案被标记为 `[FRAME]`，且部分可维护性问题被过度定级为 P1 | `CORRECTED` | 推荐设计改为 `[INFERRED]`；纯简洁性/可维护性问题降为 P2；外部知识库能力保持待确认 |

[KNOWN | HIGH] 本轮新增的四个行为测试经历了 `4 failed` 的 RED 和 `4 passed` 的
GREEN；KSS 本地 contract suite 为 `93 passed, 26 skipped`。跳过项包括需要真实
PostgreSQL、S3 或 OpenSearch 的集成验证，因此 KSS-REV-002 的 PostgreSQL SQL 分支已补
测试断言，但本地状态仍是 `PARTIAL_VERIFICATION`。

[INFERRED | HIGH] 当前审查结论为 `CONDITIONAL_RECOMMENDATION`：KSS-REV-001/002 可保留，
KSS-REV-003/004 必须在宣称 fenced job 副作用完整闭环或生产发布前关闭。
