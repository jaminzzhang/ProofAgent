# Knowledge Source Service 实施计划

> 按测试先行的垂直切片实施。每个切片必须贯通 Source、Release、Query、Candidate Evidence 和 Proof Agent 边界；在 shadow、security、recovery 和 release gates 完成前，不执行破坏性 cutover。

**目标：** 实现 [Knowledge Source Service 总体设计](../specs/2026-08-11-knowledge-source-service-design.md)。

**架构：** 一个独立版本化 Knowledge Source Service 产品，使用 API、Knowledge Query Executor、Knowledge Worker、Synchronization Scheduler 和 migration 进程角色。PostgreSQL 是可变状态与协调权威，S3-compatible storage 是不可变 original/artifact 权威，OpenSearch 是可重建投影。Proof Agent 只通过 `/v1/knowledge-queries` 获取 Candidate Evidence，并继续拥有 Evidence Admission 与答案治理。

**实施原则：** separate distribution and image；strict OpenAPI；PostgreSQL short transactions；S3-first artifact finalization；transactional outbox；leases and fencing；no direct storage access；no runtime latest；no local Hybrid fallback。

---

## Task 0：冻结公开契约与测试夹具

**Create：**

- `contracts/knowledge-service/knowledge-query.v1.openapi.yaml`
- `contracts/knowledge-service/schemas/`
- `tests/contract/knowledge_service/`
- Proof Agent fake Knowledge service fixture

- [ ] 为 `CreateKnowledgeQueryRequest`、`KnowledgeQuery`、`KnowledgeQueryResult`、Evidence Group、Candidate Evidence、Citation Locator、Retrieval Lineage 和 Problem Details 编写失败测试。
- [ ] 固定 `/v1/knowledge-queries`、`/{knowledge_query_id}`、`/{knowledge_query_id}:cancel` 路由和 `Idempotency-Key`、`Prefer`、`Location`、`Retry-After` 语义。
- [ ] 验证 unknown fields、unknown enums、ambiguous `score/confidence/accepted/answer` fields 均 fail closed。
- [ ] 建立 V1 positive/negative golden JSON，并验证 OpenAPI code generation 或手写客户端与 schema 一致。
- [ ] 为每个 stable problem `code` 建立唯一目录和契约测试。

**Exit：** Proof Agent fake adapter 可以完成 create → 202 → poll → succeeded 和 cancel/failed 两条路径，但不接触任何真实 Knowledge storage。

## Task 1：建立独立 distribution、image 与进程角色

**Create：**

- `services/knowledge-source-service/pyproject.toml`
- `services/knowledge-source-service/knowledge_source_service/`
- `services/knowledge-source-service/Dockerfile`
- 独立 migration、configuration 和 Compose role

**Modify：**

- root workspace/lock configuration
- production-local Compose 和 dependency compatibility manifest

- [ ] 先写 import-boundary 和 packaging 测试，证明 Proof Agent 不导入 service internals。
- [ ] 建立 `api`、`query-executor`、`knowledge-worker`、`sync-scheduler`、`migrate` entry points。
- [ ] 加入 `/livez`、`/readyz`、build/release identity 和 schema compatibility projection。
- [ ] 为每个角色配置独立 DB role、S3 prefix、OpenSearch namespace 和 least-privilege credentials。
- [ ] 证明服务可在不启动 Proof Agent 的情况下完成 migration、readiness 和空 Query API smoke。

**Exit：** 独立 OCI image 和进程角色可启动；任何缺失生产依赖均 fail closed，不使用 local filesystem fallback。

## Task 2：实现 Space、Client Grant 与 Query admission

**Create：**

- Space、service client、Client Grant、Knowledge Query domain/contracts/repositories
- OAuth client-token 和 signed access-narrowing assertion validators
- PostgreSQL migrations and integration tests

- [ ] 测试一个 Space 多个 Agent clients、不同 Base/Release/action/budget grants。
- [ ] 测试 cross-Space foreign key、forged Space id、missing required context、invalid issuer/signature/expiry 和 context widening 拒绝。
- [ ] 实现 mandatory idempotency fingerprint、exact replay 和 conflict。
- [ ] 实现 Query state machine、absolute deadline、cancel request、result availability 和 retention metadata。
- [ ] 对 queue capacity、per-client quota 和 `Retry-After` 编写 admission tests。

**Exit：** 两个客户端共享一个 Space 但不能越过各自 Grant；Query admission/replay/cancel 全部由独立服务权威完成。

## Task 3：实现 durable Query Executor

**Create：**

- Query queue/outbox、claim/lease/fencing repositories
- Knowledge Query Executor process role
- immutable Query Result S3 adapter and result binder

- [ ] 先覆盖 response loss、duplicate delivery、worker crash、lease expiry、stale claim、late success、cancel race 和 deadline race。
- [ ] 在同一事务写 Query、idempotency、queue item 和 outbox。
- [ ] Query Executor 在所有 bounded call 和 terminal commit 前后验证 claim ownership。
- [ ] S3 写入 result → length/digest/manifest verification → PostgreSQL visibility bind；partial write 永不成功可见。
- [ ] Result retention 到期后保留 `state=succeeded` 并切换 `result_availability=expired`。

**Exit：** 快速 Query 和 202/poll Query 共享一套状态与结果语义，且 crash/retry 不重复产生成功结果。

## Task 4：实现 Source Version、Base Version 与原子 Release

**Create：**

- Source/Base/Version/Release aggregate and repositories
- Release Preparation queue and worker
- S3 release manifest and OpenSearch attestation ports

- [ ] 测试每个 Source/Base 只能属于一个 Space，Base members 不得跨 Space。
- [ ] 测试 immutable Source Version、Base Version、Release 和 membership uniqueness。
- [ ] Preparation 在无长事务条件下绑定 Source Versions、Evidence Unit Manifests、Dataset Revisions、index generations、profile 和 validations。
- [ ] Publish 使用 one-use preparation + fencing token + exact digests 的短 CAS；stale、expired、consumed 和 competing preparations 全部拒绝。
- [ ] 测试 recommended pointer 不参与 runtime Query，old Release 保持 replayable。

**Exit：** 任一组件失败都不能产生部分 Release；Query 只接受 exact `knowledge_base_release_id`。

## Task 5：交付第一条文档 tracer bullet

**初始范围：** Markdown + text；随后扩展 PDF、DOCX、PPTX、HTML 和 scans。

- [ ] 先为 Quarantine → preflight → canonical structure → Evidence Unit Manifest → Release → Query → citation 编写 E2E failing test。
- [ ] 实现 service-generated object keys、signature/size/encoding checks 和 S3-first originals。
- [ ] 实现 Document Structure Graph、structural Evidence Unit、Source Version + Locator + Hash identity。
- [ ] 实现 Lexical lane 的最小可运行 projection 和 exact citation replay。
- [ ] 通过同一 API 把 Candidate Evidence 返回 Proof Agent fake Admission。

**Exit：** 一份 Markdown 和一份 plain text 可以完整摄取、发布、查询、引用和旧 Release 重放。

## Task 6：扩展布局文档与 OCR

**Create/Modify：**

- PDF Docling adapter、PaddleOCR escalation adapter
- DOCX/PPTX/HTML parser adapters
- PNG/JPEG/TIFF OCR adapter
- parser quality/review contracts and fixtures

- [ ] 覆盖 native、multi-column、complex table、cross-page table、OCR-only 和 mixed PDF。
- [ ] 覆盖 DOCX heading/list/table、PPTX slide/shape/table、HTML safe DOM anchor。
- [ ] 所有 vendor output 映射到 provider-neutral structure；vendor class 不进入 public/storage contracts。
- [ ] low-confidence、parser disagreement、missing rule-bearing page 进入 review_required 或失败，不静默发布。
- [ ] Derived Summary 只能 routing，不能成为 Candidate Evidence。

**Exit：** V1 全部非结构化格式通过 structure、manifest、citation、security 和 replay tests。

## Task 7：实现 Structured Dataset 与有界查询

**Initial slice：** CSV → Dataset Revision → typed filter/aggregate → Structured Evidence Group。

- [ ] 先写 schema/types/null/decimal/date/stable-record-id round-trip tests。
- [ ] 实现 versioned typed AST、operator allowlist、projection、sort、group-by、count/sum/avg/min/max。
- [ ] 实现 deterministic ordering、overflow、timezone、collation 和 input-set manifest。
- [ ] 拒绝 arbitrary SQL、dynamic table/field、unbounded group、window/UDF 和 ad hoc cross-Dataset join。
- [ ] 扩展 XLSX、mapped JSON、JSONL 和 Parquet，验证宏、公式、external link 和 deep-nesting rejection。

**Exit：** Structured Candidate 保留 typed content、record/aggregate lineage 和独立 group，不进入 RRF/Reranker。

## Task 8：实现 PostgreSQL、HTTP JSON 与 object-manifest snapshots

- [ ] PostgreSQL connector 使用独立只读 Secret Handle、allowlisted table/view 和 repeatable snapshot；测试 row/byte/time bounds 和 upstream watermark。
- [ ] HTTP connector 使用 static HTTPS allowlist、no proxy/redirect/retry、DNS/IP validation、bounded body 和 declared mapping。
- [ ] Object manifest 只读取 service-controlled exact members，不递归发现或解压。
- [ ] 每次 sync 产生 immutable Materialized Source Revision；existing Release 不随 sync 变化。
- [ ] Scheduler 只创建 bounded sync commands；worker 使用同一 queue、lease、fencing 和 idempotency。

**Exit：** 三类 external data 均在 Query 前物化；runtime integration tests 证明 Agent Query 不触发 upstream call。

## Task 9：实现 Lexical、Sparse、Dense 与 RRF

- [ ] 建立 Release-pinned analyzer、Sparse encoder、Dense embedding 和 index-generation fingerprints。
- [ ] 为三 lane 编写同一 Access Scope 预过滤和 manifest/attestation verification tests。
- [ ] 实现 exact Evidence Unit dedup 和 Weighted RRF deterministic formula/tie-break。
- [ ] Retrieval Lineage 记录 native score、lane rank、weight、RRF contribution 和 fused rank；禁止 universal score。
- [ ] 加入 optional private Reranker，验证 authorized input、pinned revision、rank transition 和 result bounds。
- [ ] 实现 independently cited context expansion 和 per-context Access Scope。

**Exit：** Gold retrieval fixtures、zero unauthorized exposure、citation resolution 和 per-lane degradation tests 通过。

## Task 10：实现 Query Planner、Plan Gate 与 Agentic

- [ ] 先写 strict Knowledge Query Plan schema 和 deterministic Plan Gate tests。
- [ ] Gate 检查 Grant、Release、scope、schema、operator、lane、budget、physical projection 和 degradation profile。
- [ ] `single_pass` 保持默认；`agentic` 仅显式启用。
- [ ] Agentic 每轮重新过 Gate，并冻结 Release/Space/scope；实现 round/model/candidate/token/duration hard budgets。
- [ ] Planner/Evaluator 无 tool/network/storage 权限，只产生 query/coverage actions。
- [ ] 覆盖 source prompt injection、invalid output、model timeout、explicit fallback、cancel 和 complete lineage。

**Exit：** Agentic 可改善 retrieval coverage，但 schema 和 security tests 证明它无法输出 Admission、truth、conflict 或 answer authority。

## Task 11：实现独立管理 API 与 Source operations

- [ ] 实现 Space、Client Grant、Source、Version、Synchronization、Base、Base Version、Release Preparation 和 Release resources。
- [ ] Binary intake 使用 single-file multipart、bounded stream 和 Idempotency-Key；无 Base64 或 browser S3 credential。
- [ ] Collections 使用 opaque keyset cursor、bounded sort 和 server-owned aggregate summary。
- [ ] 长命令返回明确领域资源，不把 Query 命名为 generic operation。
- [ ] Operator OIDC permission、optimistic concurrency、safe Problem Details 和 configuration audit 测试。

**Exit：** 服务可以在没有 Proof Agent Dashboard 的情况下完整管理 Source → Base → Release；Dashboard adapter 只调用 API。

## Task 12：接入 Proof Agent

**Create：**

- provider-neutral `KnowledgeCandidateService` port
- `KnowledgeSourceServiceClient` adapter
- Published Agent binding contract variant
- controlled run-state Query resume fields

**Modify：**

- `proof_agent/control/knowledge/` orchestration boundary
- bootstrap composition、Agent validation/publication、trace and tests

- [ ] Adapter contract tests验证 exact release、schema version、group discrimination、hash/citation/lineage 和 unknown-field rejection。
- [ ] Idempotency-Key 从 run + retrieval action + semantic attempt 稳定生成。
- [ ] 202 路径持久化 `knowledge_query_id` 并在 process restart 后继续 poll。
- [ ] Structured Groups 类型化进入 Evidence Admission；不扁平化或重算 score。
- [ ] Query failure/integrity/auth denial 产生稳定 governed failure；不调用 local Hybrid/latest/alternate provider。

**Exit：** 一个 Published Agent Version 通过独立服务完成 cited answer；network/database tests 证明 Proof Agent 无服务存储权限。

## Task 13：Shadow migration 与 pilot

- [ ] 建立 explicit export/re-admission migrator；不复制 cached index、credential values 或 mutable file store。
- [ ] 对批准 originals 生成 new Source/Base/Release，并输出 migration manifest/digest。
- [ ] 运行 parser shadow 与 retrieval shadow，比较 recall、coverage、ACL、citation、latency 和 failure，不混入 runtime evidence。
- [ ] 建立 visible tuning、sealed acceptance 和 structured/format/security slices。
- [ ] 发布一个 pilot Agent Version，保留旧 Published Agent Version 作为唯一即时 rollback。

**Exit：** pilot gates、trace-safe feedback、capacity 和 operator runbook 通过；无 hidden dual read/write。

## Task 14：Hardening、cutover 与删除旧 authority path

- [ ] 运行 real PostgreSQL/S3/OpenSearch/model integration、failure injection、complete rebuild、restore 和 Blue/Green tests。
- [ ] 冻结 formal capacity envelope、SLO、retention、model revisions、lane budgets 和 deployment manifest。
- [ ] 按 Agent Version 显式切换 bindings，验证 old Release/old Agent replay 和 rollback。
- [ ] 删除 Proof Agent runtime 对目标 Hybrid PostgreSQL/S3/OpenSearch 的直接读取和 local exception fallback。
- [ ] 把 Dashboard Source/Base 管理切到 service API adapter，只保留 Proof Agent binding ownership。
- [ ] 更新 active technical design、developer/operations/migration docs，但只记录已验证实现事实。

**Exit：** 总设计“完成定义”的所有项目与同一 release candidate 绑定；否则不得宣称生产就绪。

## 每个 Task 的最小验证

```bash
python3 scripts/check-domain-contexts.py
git diff --check
```

[FRAME | HIGH] 实现阶段还必须为新增独立 distribution 定义自己的 lock、pytest、ruff、mypy、OpenAPI compatibility、migration、container、security 和 integration commands，并把它们加入根 release gate。现有 Proof Agent 完整验证仍需执行，但不能替代服务自己的独立验证。
