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
export HYBRID_POSTGRES_DSN='postgresql://proof:proof-test-only@127.0.0.1:55432/proof'
export HYBRID_S3_BUCKET='proof-agent-test'
export HYBRID_S3_KEY_PREFIX='local-production/'
export HYBRID_S3_ENDPOINT='http://127.0.0.1:59000'
export HYBRID_S3_REGION='us-east-1'
export HYBRID_S3_ALLOW_INSECURE_ENDPOINT='1'
export AWS_ACCESS_KEY_ID='proof'
export AWS_SECRET_ACCESS_KEY='proof-test-secret'
export HYBRID_OPENSEARCH_ENDPOINT='http://127.0.0.1:19200'
export HYBRID_OPENSEARCH_ALLOWED_HOSTS='127.0.0.1'
export HYBRID_OPENSEARCH_NUMBER_OF_REPLICAS='0'

uv run proof-agent hybrid-migrate
```

[KNOWN | HIGH] `hybrid-migrate` 在 PostgreSQL transaction-scoped advisory lock 内执行幂等 DDL，并输出实际 schema 文件 SHA-256；应用进程不会静默改库。

## 2. 配置真实私有模型与发布身份

所有模型服务 origin 必须是无凭据的 HTTPS origin，并落在显式 host/CIDR 白名单内：

```bash
export PA_HYBRID_KNOWLEDGE_MODELS_ENABLED=1
export PA_HYBRID_PRODUCTION_RUNTIME_ENABLED=1
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
export HYBRID_RETRIEVAL_PROFILE_REVISION='insurance-profile-2026-07-15'
export HYBRID_CONDITION_TAXONOMY_JSON='{"taxonomy_id":"insurance","taxonomy_revision_id":"insurance-2026-07","allowed_values":{"region":["SHANGHAI"]}}'
export HYBRID_APPROVED_VISIBILITY_JSON='{"visibility":"INTERNAL","revision_id":"visibility-internal-2026-07"}'
```

[KNOWN | HIGH] 可见性没有隐式 `PUBLIC` 默认值；`HYBRID_APPROVED_VISIBILITY_JSON` 必须是业务已批准的精确 scope。Embedding instruction、模型修订、维度、mapping 和 analyzer 共同生成内容寻址的 Index Generation。

[KNOWN | HIGH] OpenSearch 认证使用间接变量名。例如先设置 `OPENSEARCH_AUTHORIZATION`，再设置 `HYBRID_OPENSEARCH_AUTHORIZATION_ENV=OPENSEARCH_AUTHORIZATION`；不要把 token 放进 endpoint 或普通配置 JSON。mTLS/CA 对应变量见 `.env.example`。

## 3. 启动 API 与 worker

两个进程必须共享同一个 `--config-dir`：

```bash
uv run proof-agent server \
  --host 127.0.0.1 --port 8000 \
  --history-dir runs/local-prod/history \
  --config-dir runs/local-prod/config \
  --no-seed-example-agent
```

```bash
uv run proof-agent knowledge-worker \
  --config-dir runs/local-prod/config \
  --poll-interval 1
```

[KNOWN | HIGH] API 与 worker 会各自组合真实私有模型客户端；worker 把原 PDF、vendor 输出、canonical JSON、preview、build identity 和保险元数据写入同一个版本化 S3。API 使用同一个 S3 authority 导入工作簿并发布 manifest；PG 是 Source publication 和 retrieval profile 的唯一在线指针。

## 4. PDF 到 Source publication

1. 创建 `hybrid_index` Source，`params` 可使用 `{}` 或显式 intake 上限。
2. 调用 `POST /api/config/knowledge-sources/{source_id}/documents`，JSON 包含 `filename`、`content_type: application/pdf` 和 `content_base64`。
3. 轮询 quarantined upload、document 和 ingestion-job API，直到 document/job 都为 `ready`。`review_required`、`failed` 或未完成文档会阻止候选发布。
4. 按 `insurance-rule-metadata.v1` 工作簿格式导入业务元数据；逐条读取 metadata review 的 `review_version` 与 `review_identity`，再 approve/correct。未批准、冲突或多重不同 authority 会失败关闭。
5. 调用 Source publication validate，取得 `validation_id`；随后 publish。

```text
POST /api/config/knowledge-sources/{source_id}/publication/validate
{"smoke_query":"该产品的保险责任是什么？"}

POST /api/config/knowledge-sources/{source_id}/publication/publish
{"validation_id":"...","change_note":"首次类生产发布"}
```

[KNOWN | HIGH] publish 会在提交 PG 当前指针前完成：候选防漂移校验、PG fencing、S3 manifest 精确写入、真实 embedding、OpenSearch bulk/read-back、受治理 smoke retrieval、投影 attestation 和短事务 CAS。任一环节失败都不会发布 Source 指针。

[KNOWN | HIGH] 升级到本版本后，旧代码生成但尚未发布的 validation 必须重新 validate；候选摘要 v2 新增了 OpenSearch index identity 和原始 smoke query，旧摘要不会被隐式接受。

## 5. Agent 在线检索与引用回答

1. 在 Draft Agent 的 `knowledge_bindings` 中引用该 shared Source，并固定/继承 Retrieval Profile。
2. 执行 Draft validation；其 `resolved_knowledge_bindings` 应包含 `source_publication_id`、snapshot、generation、publication sequence、profile、manifest exact ref 和 attestation id。
3. Phase F 通过后注册 Knowledge Release Record，再发布 Agent Version。
4. 调用 `/api/agents/{agent_id}/runs` 或 Operator Chat。

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

把 `evidence-refs.json` 内容作为 `evidence` 调用：

```text
POST /api/config/agents/{agent_id}/drafts/{draft_id}/knowledge-release-records
{
  "record_id":"knowledge-release-<candidate>",
  "validation_run_id":"<passed-run-id>",
  "evidence": { ...evidence-refs.json... }
}
```

最后调用 Draft publish，并传回上一步 `record_id`：

```text
POST /api/config/agents/{agent_id}/drafts/{draft_id}/publish
{"validation_run_id":"<passed-run-id>","knowledge_release_record_id":"knowledge-release-<candidate>"}
```

[KNOWN | HIGH] 服务端从 validation record 重新计算 candidate digest，并由独立 Release Evidence Authority 验证四个不同的 exact artifact ref；客户端不能用自报 aggregate、CI 标签或可变 latest URL 自我授权。

## 7. 验证与故障定位

基础代码门：

```bash
uv run ruff check .
uv run mypy proof_agent
uv run pytest -q
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

[INFERRED | HIGH] 如果真实闭环失败，优先按边界定位：job 未 ready 看 parser/scheduler；S3 exact-ref 错误看 versioning、key prefix 和 digest；publish 409 看 stale validation/fence/review；在线无结果看冻结 binding、ACL/applicability、manifest 与 attestation；有 evidence 但无答案看 citation/adequacy gate 和回答模型输出。

[FRAME | HIGH] 正式 Phase F 不能由仓库内的模拟测试替代。必须使用真实 300/200 业务查询资产、100–200 解析样本、私有 evaluator、独立 verifier、五并发容量证据、恢复演练和人工 assisted pilot；任一 hard-zero gate 未通过时不得发布。
