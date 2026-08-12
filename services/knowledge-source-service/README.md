# Knowledge Source Service

[KNOWN | HIGH] Knowledge Source Service（KSS）是可独立构建、部署和扩缩容的异构知识服务。它负责知识源摄取、不可变版本、混合检索、受限结构化分析和 `Candidate Evidence` 返回；Evidence Admission、冲突裁决和最终答案仍由 ProofAgent 等调用 Agent 负责。

[KNOWN | HIGH] 当前状态为 `VERIFIED_LOCAL`，不是生产发布批准。生产前剩余门槛见 [`../../docs/features/knowledge-source-service/tdd-report.md`](../../docs/features/knowledge-source-service/tdd-report.md)。

## 运行角色

同一 OCI image 提供五个稳定角色：

| 角色 | 命令 | 职责 |
| --- | --- | --- |
| API | `knowledge-source-service api` | 健康检查、管理面、Knowledge Query 提交和轮询 |
| Query Executor | `knowledge-source-service query-executor` | 从 PostgreSQL 领取 Query，执行检索并发布结果 |
| Knowledge Worker | `knowledge-source-service knowledge-worker` | 执行外部源同步和 Release 完整性巡检 |
| Sync Scheduler | `knowledge-source-service sync-scheduler` | 清理过期 Query Result |
| Migration | `knowledge-source-service migrate` | 顺序执行 PostgreSQL schema migration |

`knowledge-source-service roles` 可列出角色。所有在线角色使用 PostgreSQL 作为可变权威、S3-compatible storage 保存不可变 artifact、OpenSearch 保存可重建检索投影；依赖缺失时失败关闭，不回退到本地文件或 ProofAgent 进程内知识实现。

## 支持的数据与查询

| 类型 | 输入格式 | 可查询能力 |
| --- | --- | --- |
| 非结构化文档 | Plain text、Markdown、HTML、PDF、DOCX、PPTX | Lexical、Dense、learned Sparse、weighted RRF；保留行、DOM、页、段落、表格单元、shape 等 typed locator |
| 扫描材料 | PNG、JPEG、TIFF、扫描 PDF | 经显式配置的私有 OCR；返回页码和 bounding-box locator |
| 结构化数据 | CSV、mapped JSON、JSONL、XLSX、Parquet | typed filter、projection、sort、group、`count/sum/avg/min/max/exact_distinct_count` 与可追溯结果 |
| 外部快照 | HTTPS JSON、PostgreSQL relation、S3 object manifest | 先物化为不可变 Source Version，再允许 Release 查询；Query 不直连上游 |

`strategy=single_pass` 是默认路径；`strategy=agentic` 需要 Client Grant 允许，并需要配置私有 Agentic controller。Agentic 执行受 Query budget、轮次、模型调用、候选数、token、deadline 和 lease 约束。

## 必需配置

所有角色都先校验四个公共变量：

```text
KSS_POSTGRES_DSN=postgresql://user:password@postgres:5432/knowledge
KSS_OBJECT_STORE_URI=s3://knowledge-artifacts/kss
KSS_SEARCH_ENDPOINT=http://opensearch:9200
KSS_RELEASE_IDENTITY=kss-2026-08-12.1
```

S3-compatible endpoint 可使用：

```text
KSS_S3_ENDPOINT=http://minio:9000
KSS_S3_REGION=us-east-1
KSS_S3_ACCESS_KEY_ID=<secret>
KSS_S3_SECRET_ACCESS_KEY=<secret>
KSS_S3_ALLOW_INSECURE_ENDPOINT=1
```

非 loopback HTTP S3 endpoint 只有在显式设置 `KSS_S3_ALLOW_INSECURE_ENDPOINT=1` 时才会被接受。静态 access key 必须成对提供；生产环境应使用工作负载身份或受管 secret 注入。

Dense/Sparse 投影必须配置私有 encoder：

```text
KSS_PROJECTION_ENCODER_ENDPOINT=https://encoder.internal.example/v1/encode
KSS_PROJECTION_ENCODER_BEARER_TOKEN=<secret>
KSS_DENSE_ENCODER_REVISION=dense-v1
KSS_SPARSE_ENCODER_REVISION=sparse-v1
KSS_DENSE_DIMENSION=384
```

本地测试可以显式设置 `KSS_DETERMINISTIC_ENCODER_ENABLED=1`；该 deterministic hash encoder 不是生产模型。

可选能力：

```text
KSS_AGENTIC_CONTROLLER_ENDPOINT=https://retrieval-controller.internal.example/v1/next
KSS_AGENTIC_CONTROLLER_BEARER_TOKEN=<secret>

KSS_OCR_ENDPOINT=https://ocr.internal.example/v1/extract
KSS_OCR_BEARER_TOKEN=<secret>
KSS_OCR_MODEL_REVISION=ocr-v1

KSS_OPERATOR_BEARER_TOKEN=<at-least-16-character-secret>
KSS_OPERATOR_ID=knowledge-operator
```

API 只有在配置 operator token 后才挂载管理路由；未配置时仍保留健康检查和 Agent Query API。

## 外部源同步

连接描述通过 `KSS_SNAPSHOT_CONNECTIONS_JSON` 声明，凭证只能通过匹配 `KSS_CONNECTION_SECRET_*` 的环境变量句柄引用。API 只读取 descriptor 和 connection ID；只有 Knowledge Worker 解析 secret 并访问上游。

```json
[
  {
    "connection_id": "policy-api",
    "kind": "http_json",
    "endpoint": "https://policy.internal.example/v1/snapshot",
    "bearer_token_environment_key": "KSS_CONNECTION_SECRET_POLICY_API",
    "allowed_networks": ["10.20.0.0/16"],
    "max_response_bytes": 8388608
  },
  {
    "connection_id": "claims-db",
    "kind": "postgresql",
    "dsn_environment_key": "KSS_CONNECTION_SECRET_CLAIMS_DB",
    "relation": "knowledge.claims",
    "columns": ["claim_id", "status", "amount"],
    "record_key": ["claim_id"],
    "max_rows": 100000,
    "max_response_bytes": 67108864,
    "statement_timeout_ms": 30000
  }
]
```

同步使用 `POST /v1/knowledge-source-synchronizations` 创建可轮询资源，要求 operator bearer token 和 `Idempotency-Key`。相同 operator、key 和 payload 精确重放；key 相同但 payload 不同返回冲突。

## 启动顺序

先构建镜像：

```bash
docker build \
  -t proofagent-knowledge-source-service:local \
  services/knowledge-source-service
```

部署时使用同一配置依次启动：

1. `migrate`，成功退出后再继续。
2. `api`。
3. 一个或多个 `query-executor`。
4. 一个或多个 `knowledge-worker`。
5. 一个 `sync-scheduler`。

API 默认监听 `0.0.0.0:8080`，可由 `KSS_API_HOST` 和 `KSS_API_PORT` 修改。生产入口应在受管 HTTPS gateway 后，并配置独立的 Agent client 身份和 exact-Release Client Grant。

## HTTP 接口

| 方法与路径 | 说明 |
| --- | --- |
| `GET /livez` | 进程存活与 release identity |
| `GET /readyz` | PostgreSQL、object storage、OpenSearch readiness |
| `POST /v1/knowledge-queries` | 创建 durable Knowledge Query；要求 Agent bearer token 和 `Idempotency-Key` |
| `GET /v1/knowledge-queries/{id}` | 轮询状态和可用 Result |
| `POST /v1/knowledge-queries/{id}:cancel` | 请求取消非终态 Query |
| `POST /v1/knowledge-spaces` | 创建 Knowledge Space |
| `POST /v1/knowledge-spaces/{space}/knowledge-sources` | 创建 Source |
| `POST /v1/knowledge-spaces/{space}/knowledge-sources/{source}/versions:ingest` | 上传并物化 Source Version |
| `POST /v1/knowledge-spaces/{space}/knowledge-bases` | 创建 Base |
| `POST /v1/knowledge-spaces/{space}/knowledge-bases/{base}/releases` | 发布 exact immutable Release |
| `POST /v1/knowledge-source-synchronizations` | 创建外部 Source 同步 |
| `GET /v1/knowledge-source-synchronizations/{id}` | 轮询同步状态 |

Agent Query 请求示例：

```json
{
  "knowledge_base_release_id": "release-policy-v17",
  "question": "航班延误可获得多少赔付？",
  "strategy": "agentic",
  "query_constraints": {},
  "execution_budget": {
    "max_rounds": 3,
    "max_model_calls": 3,
    "max_candidates": 20,
    "max_model_tokens": 4000,
    "max_duration_ms": 10000
  },
  "deadline_at": "2026-08-12T10:30:00+08:00"
}
```

一个 Knowledge Space 可配置多个 Agent client。每个 client 使用独立 bearer credential 和 Client Grant；Grant 固定 exact Release、允许的 strategy、最大 budget 和 access-scope digest，不能由请求扩大。当前 client/grant provisioning 通过受控部署代码调用 `PostgresKnowledgeAccessControl` 完成，尚未暴露为公共管理 API。

## ProofAgent 接入

[KNOWN | HIGH] ProofAgent 通过 provider-neutral `KnowledgeCandidateService` port 接入，不导入 KSS domain 或 repository。接入组件包括：

- `proof_agent.capabilities.knowledge.source_service_client.KnowledgeSourceServiceClient`：在 guarded HTTPS egress 上 create → poll，严格验证 Query/Result 和 exact Release。
- `proof_agent.control.knowledge.candidate_request.BoundKnowledgeCandidateQueryFactory`：把 Published Agent Version 固定到 exact Release，并生成稳定幂等键和有界 budget。
- `compose_harness_invocation(..., knowledge_candidate_service=..., knowledge_candidate_query_factory=...)`：将两者成对注入既有 retrieval/Admission 流程。

当前仓库提供显式组合注入点，不会从环境变量隐式启用远程路径。生产启用需要 deployment composition 提供 guarded HTTP client、credential reference、service endpoint、exact Release binding 和 Query factory；任一项缺失时不得回退到本地知识权威。

## 本地验证

启动依赖：

```bash
docker compose -f docker-compose.hybrid-test.yml up -d
```

运行 KSS contract suite：

```bash
KSS_TEST_POSTGRES_DSN='postgresql://proof:proof-test-only@127.0.0.1:55432/proof' \
KSS_TEST_S3_ENDPOINT='http://127.0.0.1:59000' \
KSS_TEST_S3_ACCESS_KEY='proof' \
KSS_TEST_S3_SECRET_KEY='proof-test-secret' \
KSS_TEST_SEARCH_ENDPOINT='http://127.0.0.1:19200' \
KSS_REQUIRE_POSTGRES_TESTS=1 \
KSS_REQUIRE_S3_TESTS=1 \
KSS_REQUIRE_SEARCH_TESTS=1 \
.venv/bin/pytest -q tests/contract/knowledge_service
```

完整 RED → GREEN → REFACTOR 记录、测试数量和生产剩余门槛见 [`../../docs/features/knowledge-source-service/tdd-report.md`](../../docs/features/knowledge-source-service/tdd-report.md)。
