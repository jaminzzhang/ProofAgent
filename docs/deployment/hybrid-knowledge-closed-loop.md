# Hybrid Knowledge 类生产闭环部署与 Phase F 验收

[KNOWN | HIGH] 本指引对应生产 Hybrid 路径：PDF 隔离上传 → 私有 Docling/Paddle 解析 → PostgreSQL/S3/OpenSearch 发布 → Published Agent 冻结绑定 → 在线 Hybrid 检索 → 引用回答 → Phase F 证据封存与 Agent 发布。

[KNOWN | HIGH] `docker-compose.hybrid-test.yml` 只提供一次性 PostgreSQL、MinIO 和 OpenSearch；真实 Docling、Paddle、Embedding、Reranker、调度器、回答模型以及独立验收服务必须由部署方在公司信任边界内提供。不要把测试凭据、测试 bucket 或关闭安全插件的 OpenSearch 用于生产。

## 1. 安装和启动数据服务

```bash
uv sync --extra dashboard --extra ingestion --extra hybrid --extra production --extra openai
docker compose -f docker-compose.hybrid-test.yml up -d --wait
```

本地类生产数据面变量：

```bash
export PROOF_AGENT_MODE='production'
export PROOF_AGENT_POSTGRES_DSN='postgresql+psycopg://proof:proof-test-only@127.0.0.1:55432/proof'
export HYBRID_POSTGRES_DSN='postgresql://proof:proof-test-only@127.0.0.1:55432/proof'

export HYBRID_S3_BUCKET='proof-agent-test'
export HYBRID_S3_KEY_PREFIX='local-production/knowledge/'
export HYBRID_S3_ENDPOINT='http://127.0.0.1:59000'
export HYBRID_S3_REGION='us-east-1'
export HYBRID_S3_ALLOW_INSECURE_ENDPOINT='1'
export PROOF_AGENT_ARTIFACT_S3_BUCKET='proof-agent-test'
export PROOF_AGENT_ARTIFACT_S3_KEY_PREFIX='local-production/runs/'
export PROOF_AGENT_ARTIFACT_S3_ENDPOINT='http://127.0.0.1:59000'
export PROOF_AGENT_ARTIFACT_S3_REGION='us-east-1'
export AWS_ACCESS_KEY_ID='proof'
export AWS_SECRET_ACCESS_KEY='proof-test-secret'

export HYBRID_OPENSEARCH_ENDPOINT='http://127.0.0.1:19200'
export HYBRID_OPENSEARCH_ALLOWED_HOSTS='127.0.0.1'
export HYBRID_OPENSEARCH_NUMBER_OF_REPLICAS='0'

uv run proof-agent database upgrade
uv run proof-agent hybrid-migrate
uv run proof-agent database check
```

[KNOWN | HIGH] `database upgrade` 安装应用 Alembic schema；`hybrid-migrate` 在同一 PostgreSQL authority 上安装幂等 Hybrid DDL，并输出 schema SHA-256。API/worker 启动只检查 schema，不会静默改库。两个 DSN 必须指向同一个数据库。

## 2. 配置真实私有模型与发布身份

所有模型服务 origin 必须是无凭据的 HTTPS origin，并落在显式 host/CIDR 白名单内：

```bash
export PA_HYBRID_KNOWLEDGE_MODELS_ENABLED=1
export PA_HYBRID_PRODUCTION_RUNTIME_ENABLED=1
export PA_KNOWLEDGE_REQUIRE_INSURANCE_METADATA_DRAFTS=1
export PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT='https://scheduler.knowledge.internal'
export PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE='proof-agent-local-prod'
export PA_KNOWLEDGE_DOCLING_ENDPOINT='https://docling.knowledge.internal'
export PA_KNOWLEDGE_PADDLE_ENDPOINT='https://paddle.knowledge.internal'
export PA_KNOWLEDGE_EMBEDDING_ENDPOINT='https://embedding.knowledge.internal'
export PA_KNOWLEDGE_RERANKER_ENDPOINT='https://reranker.knowledge.internal'
export PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS='scheduler.knowledge.internal,docling.knowledge.internal,paddle.knowledge.internal,embedding.knowledge.internal,reranker.knowledge.internal'
export PA_KNOWLEDGE_MODEL_ALLOWED_CIDRS='10.0.0.0/8'
export PA_KNOWLEDGE_PARSER_REVISION='docling@sha256:<approved-revision>'
export PA_KNOWLEDGE_MODEL_DIGESTS='docling@sha256:<digest>,paddle@sha256:<digest>'
export PA_KNOWLEDGE_PARSER_CONFIGURATION_SHA256='<64-hex>'

export HYBRID_EMBEDDING_INSTRUCTION='Represent the insurance rule query for retrieval.'
export HYBRID_EMBEDDING_MODEL_REVISION='embedding@sha256:<digest>'
export HYBRID_EMBEDDING_DIMENSION='1024'
export HYBRID_RERANKER_REVISION='reranker@sha256:<digest>'
export HYBRID_RETRIEVAL_PROFILE_REVISION='insurance-profile-v1'
export HYBRID_CONDITION_TAXONOMY_JSON='{"taxonomy_id":"insurance","taxonomy_revision_id":"insurance-2026-07","allowed_values":{"region":["SHANGHAI"]}}'
export HYBRID_APPROVED_VISIBILITY_JSON='{"visibility":"INTERNAL","revision_id":"visibility-internal-2026-07"}'
export PROOF_AGENT_OPENSEARCH_SECRET_HANDLE='knowledge/opensearch/proof-agent'
```

[KNOWN | HIGH] 可见性没有隐式 `PUBLIC` 默认值；`HYBRID_APPROVED_VISIBILITY_JSON` 必须是业务已批准的精确 scope。Embedding instruction、模型修订、维度、mapping 和 analyzer 共同生成内容寻址的 Index Generation。

[KNOWN | HIGH] 生产 OpenSearch 认证必须通过 `PROOF_AGENT_OPENSEARCH_SECRET_HANDLE` 解析；Secret 内容是仅含 `authorization` 的 JSON。不要把 token 放进 endpoint、普通配置 JSON 或浏览器。环境变量认证选择器仅供非生产测试组合。

生产进程还必须完成 OIDC、Vault、active Egress Policy、Session key 和部署身份配置；变量模板见 `.env.example`。尤其需要：

```bash
export PROOF_AGENT_STABLE_ORIGIN='https://proof-agent.internal.example'
export PROOF_AGENT_SECRET_PROVIDER_COMPATIBILITY_INPUT='deploy/production/compatibility-input.json'
export PROOF_AGENT_SECRET_HANDLE_LOCATORS_JSON='<opaque-handle-to-vault-locator-json>'
export PROOF_AGENT_VAULT_AGENT_TOKEN_FILE='/run/secrets/vault-agent-token'
export PROOF_AGENT_MODEL_CREDENTIAL_KEYRING_FILE='/run/secrets/model-credential-keyring.json'
export PROOF_AGENT_PUBLISHED_AGENT_CACHE_DIR="$PWD/var/production-agent-cache"
export PROOF_AGENT_EXECUTOR_WORK_DIR="$PWD/var/executor"
export PROOF_AGENT_RELEASE_WORK_DIR="$PWD/var/release-validation"
```

[KNOWN | HIGH] API 组合会先从 PostgreSQL 读取 active Egress Policy，再访问 Vault/OIDC/模型服务；因此部署迁移 Job 必须在 API 启动前原子安装并激活初始 Permission Mapping 与 Egress Policy。当前仓库尚未提供 S6 的通用生产 bootstrap/Blue-Green Job，类生产验证可沿用测试中的 PostgreSQL security repository 初始化方式；该缺口会阻止正式 Deployment Gate，但不允许改成 allow-all 或绕过 guarded egress。

## 3. 启动 API 与 worker

生产 API、Knowledge Worker 和 Run Executor 共享 PostgreSQL/S3 authority，不使用共享本地 `--config-dir`：

```bash
uv run proof-agent server \
  --host 127.0.0.1 --port 8000 \
  --no-seed-example-agent
```

```bash
export PROOF_AGENT_KNOWLEDGE_WORKER_ID='knowledge-worker-local-1'
uv run proof-agent knowledge-worker --poll-interval 1

export PROOF_AGENT_RELEASE_ID='local-candidate-1'
export PROOF_AGENT_IMAGE_DIGEST='sha256:<candidate-image-digest>'
export PROOF_AGENT_EXECUTOR_ID='executor-local-1'
uv run proof-agent run-executor --slot 1 --concurrency 5
```

[KNOWN | HIGH] 三个角色没有 production→local fallback。worker 把原 PDF、vendor 输出、canonical JSON、preview、build identity 和保险元数据写入版本化 S3；API 只接收 multipart admission、review CAS、异步 publication preparation 与短事务 publication commit；PG 是 Source publication、Agent、队列和 Retrieval Profile 的在线 authority；Executor 只执行冻结快照。

## 4. PDF 到 Source publication

1. 先读取 `GET /api/config/knowledge-source-capabilities`，再创建 `source_id=insurance-rules`、`provider=hybrid_index` 的 Source。该 ID 必须与生产候选包一致；Dashboard 不配置私有服务 endpoint、凭据或模型 digest。
2. 调用 `POST /api/config/knowledge-sources/{source_id}/documents`，使用 `multipart/form-data` 传递原始 `file` 和当前 `expected_revision`，并提供 `Idempotency-Key`。浏览器不上传 Base64，也不持有 S3 authority。
3. 通过响应中的 `operation_id` 轮询 `/operations/{operation_id}`，再读取 cursor document projection；`review_required`、`failed` 或未完成文档会阻止候选发布。
4. 按 `insurance-rule-metadata.v1` 工作簿格式调用 `/metadata-imports`，同样使用 multipart、精确 `document_id`/`revision_id`、Source revision 与幂等键。操作完成后逐条读取 metadata review 的 `review_version` 与 `review_identity`，再 approve/correct。未批准、冲突或多重不同 authority 会失败关闭。
5. 调用 `/publication-validations` 创建异步 preparation operation；轮询成功后读取 `prepared` validation 的 `validation_id` 与 `fencing_token`，最后调用 `/publications` 做短 PostgreSQL CAS。

```bash
curl -fsS -X POST \
  -H 'Idempotency-Key: upload-001' \
  -F 'expected_revision=1' \
  -F 'file=@policy.pdf;type=application/pdf' \
  "$BASE_URL/api/config/knowledge-sources/$SOURCE_ID/documents"

curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: prepare-001' \
  -d '{"smoke_query":"该产品的保险责任是什么？","expected_revision":2}' \
  "$BASE_URL/api/config/knowledge-sources/$SOURCE_ID/publication-validations"

curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: publish-001' \
  -d '{"validation_id":"...","expected_fencing_token":7,"change_note":"首次类生产发布","expected_revision":2}' \
  "$BASE_URL/api/config/knowledge-sources/$SOURCE_ID/publications"
```

[KNOWN | HIGH] 异步 preparation worker 在 authority commit 前完成候选防漂移校验、PG fencing、S3 manifest 精确写入、真实 embedding、OpenSearch bulk/read-back、受治理 smoke retrieval 和投影 attestation。最终 publish 只验证幂等性、权限、新鲜度、validation/fence 与当前 Source revision，然后做短 PostgreSQL CAS；它不会调用私有模型、S3 或 OpenSearch。任一环节失败都不会发布 Source 指针。

[KNOWN | HIGH] 升级到本版本后，旧代码生成但尚未发布的 validation 必须重新 validate；候选摘要 v2 新增了 OpenSearch index identity 和原始 smoke query，旧摘要不会被隐式接受。

## 5. Agent 在线检索与引用回答

1. 使用 `deploy/production/agent_management_insurance_specialist/agent.yaml` 作为生产候选，而不是 `examples/` 下的 deterministic 开发示例。
2. 候选固定 `source_id=insurance-rules`、`retrieval_profile_revision_id=insurance-profile-v1` 和共享连接 `model_production_primary`；部署前必须通过 Models API 配置真实模型 URL、模型名和一次性写入的 API Key。API Key 以 PostgreSQL 密文保存，候选 YAML 不包含凭据。
3. Phase F 四门通过后，使用 `production-publish-agent`。服务端解析当前 PG Hybrid publication，冻结 publication/snapshot/generation/sequence/profile/manifest/attestation，并执行一次真实在线引用回答。
4. 发布成功后调用 `POST /api/agents/{agent_id}/runs` 或 Operator Chat；Run Request 的机构授权只从服务端 OIDC claim mapping 注入，客户端不能自报 ACL。

[KNOWN | HIGH] 在线运行不会重新跟随 Source 的 latest pointer；它按 Published Agent Version 冻结的历史 publication 读取 PG/S3 authority，验证 OpenSearch UUID/attestation，先做授权和适用性过滤，再运行 BM25+dense+RRF+真实 reranker。最终回答的可见引用必须绑定到已准入 evidence citation；无合格证据时失败关闭。

## 6. Phase F 四门验收、证据封存和发布

先配置私有 evaluator、独立 acceptance verifier、operations provider 与 release authority（变量完整清单见 `.env.example`），再执行：

```bash
uv run proof-agent evaluate knowledge-shadow \
  --suite var/knowledge-eval/shadow.yaml \
  --output var/knowledge-eval/shadow.json

uv run proof-agent evaluate knowledge-capacity \
  --suite var/knowledge-eval/capacity.yaml \
  --output var/knowledge-eval/capacity.json

uv run proof-agent evaluate knowledge-acceptance \
  --suite var/knowledge-eval/sealed-acceptance-envelope.json \
  --output var/knowledge-eval/acceptance.json

uv run proof-agent evaluate knowledge-recovery \
  --source-id "$SOURCE_ID" --generation-id "$GENERATION_ID" \
  --output var/knowledge-eval/recovery.json
```

四门都通过后封存到版本化 S3：

```bash
uv run proof-agent hybrid-seal-release-evidence \
  --shadow var/knowledge-eval/shadow.json \
  --capacity var/knowledge-eval/capacity.json \
  --acceptance var/knowledge-eval/acceptance.json \
  --recovery var/knowledge-eval/recovery.json \
  --output var/knowledge-eval/evidence-refs.json
```

配置独立 Release Authority、服务端验收 ACL 和审计身份后，原子发布 Agent：

```bash
export PA_KNOWLEDGE_EVALUATION_ENDPOINT='https://knowledge-evaluator.internal'
export PROOF_AGENT_KNOWLEDGE_EVALUATION_SECRET_HANDLE='evaluation/proof-agent/release'
export PROOF_AGENT_RELEASE_INSTITUTION_AUTHORIZATION_JSON='{"institutions":["branch-shanghai"],"regions":["SHANGHAI"],"public_only":false}'
export PROOF_AGENT_RELEASE_ACTOR_SUBJECT='release-operator'
export PROOF_AGENT_RELEASE_ACTOR_IDENTITY_PROVIDER='deployment-identity'
export PROOF_AGENT_RELEASE_ACTOR_SESSION_ID='release-session-local-1'

uv run proof-agent production-publish-agent \
  --agent deploy/production/agent_management_insurance_specialist/agent.yaml \
  --release-evidence var/knowledge-eval/evidence-refs.json \
  --smoke-question '该产品等待期如何解释？'
```

[KNOWN | HIGH] 发布器先让独立 Release Authority 验证四个不同的 exact artifact ref，再暂存 PG Draft，执行真实 Hybrid 检索/回答并把 trace 与 receipt 回写版本化 S3。只有 `ANSWERED_WITH_CITATIONS` 且至少一个引用被接纳时，才以 active-pointer CAS 原子写入不可变 Agent Version；并发候选、证据漂移、模型/Secret 不可用都会失败关闭。

## 7. 验证与故障定位

基础代码门：

```bash
uv run ruff check .
uv run mypy proof_agent
uv run pytest -q tests -m 'not postgres_integration and not hybrid_integration'
npm run build
npm test
```

真实 disposable 数据面门：

```bash
export HYBRID_TEST_POSTGRES_DSN='postgresql://proof:proof-test-only@127.0.0.1:55432/proof'
export HYBRID_TEST_S3_ENDPOINT='http://127.0.0.1:59000'
export HYBRID_TEST_S3_BUCKET='proof-agent-test'
export HYBRID_TEST_S3_ACCESS_KEY='proof'
export HYBRID_TEST_S3_SECRET_KEY='proof-test-secret'
export HYBRID_TEST_OPENSEARCH_URL='http://127.0.0.1:19200'
uv run pytest -m hybrid_integration tests/integration -q
```

应用 PostgreSQL/S3 回归：

```bash
export PROOF_AGENT_TEST_POSTGRES_DSN='postgresql+psycopg://proof:proof-test-only@127.0.0.1:55432/proof'
export PROOF_AGENT_REQUIRE_POSTGRES_TESTS=1
export PROOF_AGENT_TEST_S3_ENDPOINT='http://127.0.0.1:59000'
export PROOF_AGENT_TEST_S3_BUCKET='proof-agent-test'
export AWS_ACCESS_KEY_ID='proof'
export AWS_SECRET_ACCESS_KEY='proof-test-secret'
uv run pytest -m postgres_integration tests -q
```

[INFERRED | HIGH] 如果真实闭环失败，优先按边界定位：job 未 ready 看 parser/scheduler；S3 exact-ref 错误看 versioning、key prefix 和 digest；publish 409 看 stale validation/fence/review；在线无结果看冻结 binding、ACL/applicability、manifest 与 attestation；有 evidence 但无答案看 citation/adequacy gate 和回答模型输出。

[FRAME | HIGH] 正式 Phase F 不能由仓库内的模拟测试替代。必须使用真实 300/200 业务查询资产、100–200 解析样本、私有 evaluator、独立 verifier、五并发容量证据、恢复演练和人工 assisted pilot；任一 hard-zero gate 未通过时不得发布。
