# Proof Agent 技术设计方案

> 权威技术设计文档。Proof Agent 是 Controlled Agent Harness Framework：用 Harness Engineering 管理 Agent 生命周期，并通过 adapter 接入远程模型、LangChain/LangGraph、向量库、真实 MCP、Dashboard、CLI 和 Docker。

## 1. 核心定位

Proof Agent 的核心不是 RAG demo，也不是某个 Agent runtime 的封装，而是 **Controlled Agent Harness Framework**。

它把 Agent 执行放入 Control Envelope：

```text
Workflow decides.
Policy permits.
Tools wait for approval.
Evidence supports.
Validators block unsafe output.
Memory stays bounded.
Trace records.
Receipt proves.
```

当前 deterministic demo 是回归基线，不是产品边界。项目必须支持生产集成，但所有集成都要服从同一套 Harness 生命周期。

核心目标：

1. 管理完整 Agent lifecycle：config、workflow、policy、retrieval、model、tool、memory、validation、trace、receipt。
2. 保留无 API key 的 deterministic demo，证明治理链路可复现。
3. 支持远程模型、LangChain/LangGraph、向量库、真实 MCP 和 Dashboard adapter。
4. 提供 CLI 与 Docker 运行入口。
5. 保持 contract-first，第三方 SDK 类型不能泄漏到公共合约。

当前 demo 验收结果：

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

## 2. 设计原则

### 2.1 Harness 控制流程

LLM 只生成候选内容。是否检索、是否调用工具、是否写记忆、是否调用远程模型、是否接受输出，都由 Workflow、PolicyEngine、ToolGateway 和 Validators 决定。

### 2.2 Contract-first

公共边界由 `proof_agent/contracts/` 定义。LangGraph、LangChain、MCP、Chroma、OpenAI、Azure、Anthropic 等 SDK 类型只能存在于 adapter 层。

### 2.3 Deterministic baseline

本地 deterministic path 必须始终可运行，用于回归测试和企业评估。它不限制远程模型或平台能力的发展。

### 2.4 远程输出默认不可信

ModelProvider 返回的是候选输出。候选输出必须经过 schema、safety、citation/evidence validators，才能成为 final output。

### 2.5 Trace 是事实源

JSONL Trace 是执行事实源。Governance Receipt 是 trace 的可读投影。Receipt 不能反向推断未记录事实。

### 2.6 配置显式，不携带 secret

`agent.yaml` 可以声明 env var 名称、provider、model、timeout、temperature、token limit。不得写入 raw API key、bearer token、password、connection string 或 provider secret。

### 2.7 Adapter 可替换

Runtime、model、knowledge、tool、memory、dashboard 都可以替换实现，但不能改变 Harness 语义。

## 3. 总体架构

```text
CLI / Docker / Dashboard API / Template
        |
        v
Agent Contract Layer
  - agent.yaml
  - config loader
  - Pydantic contracts
        |
        v
Control Envelope Layer
  - Workflow Orchestrator
  - PolicyEngine
  - ToolGateway
  - Memory Boundary
  - Validators
        |
        v
Adapter Layer
  - Model Providers
  - Knowledge / Vector Providers
  - LangChain / LangGraph Runtime Adapters
  - MCP / Tool Adapters
        |
        v
Governance Layer
  - JSONL Trace
  - RunStore
  - Governance Receipt
  - Dashboard API
```

Enterprise QA 当前主链路：

```text
agent.yaml
  -> load_agent_manifest
  -> run_enterprise_qa
  -> PolicyEngine(before_retrieval)
  -> KnowledgeProvider.retrieve
  -> evaluate_evidence
  -> PolicyEngine(before_answer)
  -> build ModelRequest
  -> PolicyEngine(before_model_call)
  -> ModelProvider.generate
  -> validators
  -> optional ToolGateway approval path
  -> SessionMemory policy/write
  -> final_output
  -> TraceWriter
  -> RunStore
  -> Governance Receipt
```

## 4. 当前实现基线

| Area | Current implementation |
| --- | --- |
| CLI | `demo`、`run`、`doctor`、`inspect`、`compare`、`dashboard` |
| Docker | `Dockerfile`、`docker-compose.yml` 默认运行 demo |
| Contracts | Pydantic v2 frozen models |
| Config | YAML loading、path resolution、secret-looking params rejection |
| Workflow | `workflow/orchestrator.py` 执行 Enterprise QA Harness |
| Runtime | `runtime/langgraph_runner.py` 是 adapter boundary，当前委托 orchestrator |
| Policy | retrieval、answer、tool、memory、model call enforcement points |
| Knowledge | Markdown deterministic retrieval；vector stack optional |
| Model | `deterministic`、`openai_compatible`；Azure/Anthropic placeholders |
| Tools | ToolGateway、mock `customer_lookup`、approval state |
| Memory | Session memory with denylist |
| Validators | schema、evidence、safety、citations、tool result |
| Audit | JSONL trace、redaction、Governance Receipt、Model Usage |
| Storage/API | RunStore、FastAPI health/runs/stats routes |
| Tests/CI | pytest、Ruff、mypy、GitHub Actions |

## 5. 目录边界

```text
proof_agent/
  api/          Dashboard API and serializers
  audit/        trace, redaction, receipt
  compare/      plain RAG vs harness RAG
  config/       manifest loading and validation
  contracts/    public frozen contracts
  demo/         deterministic scenarios
  knowledge/    retrieval and evidence providers
  memory/       memory boundary implementations
  policy/       policy engine and rules
  providers/    model provider adapters
  runtime/      LangGraph/LangChain runtime adapters
  storage/      run history and latest compatibility
  tools/        ToolGateway, approval, MCP adapters
  validators/   schema/evidence/safety/citation/tool validators
  workflow/     Harness workflow semantics
```

Boundary rules:

- `contracts/` cannot import adapter SDKs.
- `workflow/` owns Harness order and calls protocols, not SDK clients.
- `providers/` owns model SDK integration.
- `knowledge/` returns `EvidenceChunk`; it does not decide final answer.
- `tools/` is the only tool execution entry.
- `validators/` decide whether candidate output may proceed.
- `audit/` records facts and renders receipts; it does not control workflow.
- `api/` and `storage/` expose read-only observability and must not create a second execution path.

## 6. Agent Contract

`agent.yaml` is the public delivery artifact.

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local
  path: ./knowledge

model:
  provider: deterministic
  name: demo

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

OpenAI-compatible example:

```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
    base_url_env: OPENAI_BASE_URL
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 30
```

Config rules:

- Allow env var names such as `api_key_env`, `base_url_env`, `organization_env`, `project_env`.
- Reject secret-looking fields such as `api_key`, `authorization`, `bearer`, `password`, `secret`, `access_token`.
- Unsupported provider fails with `PA_MODEL_001`.
- Provider runtime errors should emit `model_error` once trace exists.

## 7. Core Contracts

| Contract | Purpose |
| --- | --- |
| `AgentManifest` | Agent config entry point |
| `PolicyRule` / `PolicyDecision` | rule declaration and decision |
| `EvidenceChunk` | retrieved evidence and citation source |
| `ModelRequest` / `ModelResponse` | provider-neutral model call |
| `ToolRequest` / `ToolResult` | tool request/result semantics |
| `ApprovalState` | tool approval lifecycle |
| `TraceEvent` | JSONL event envelope |
| `ReceiptOutcome` | final outcome enum |
| `RunResult` | CLI-facing result |
| `RunSummary` / `RunDetail` | Dashboard-facing read contracts |

Evolution rules:

- Add fields as optional/defaulted when possible.
- Treat public enum changes as compatibility decisions.
- Never store SDK objects or secrets in contracts.
- Dashboard contracts are read projections, not workflow state.

## 8. Workflow And Runtime

Workflow is the Harness semantic layer. It decides state order and owns failure behavior.

Runtime adapter strategy:

- LangGraph StateGraph, checkpoint, and interrupt belong in `runtime/`.
- LangChain integration can connect ecosystem model/retriever/tool abstractions, but must adapt into Proof Agent contracts.
- Runtime details must not leak into config, policy, trace, receipt, or dashboard contracts.

Future templates should use a workflow registry or separate workflow modules. Do not keep adding template-specific branches to Enterprise QA orchestrator.

## 9. PolicyEngine

Enforcement points:

```text
before_retrieval
before_answer
before_tool_call
before_memory_write
before_model_call
```

Decision types:

```text
allow
deny
require_approval
escalate
```

Rules:

- Policy consumes context and contracts only.
- Every handled enforcement point emits `policy_decision`.
- `require_approval` is a workflow state, not an exception.
- `escalate` must appear as a governed outcome.
- Model policy context includes provider, model, estimated tokens, stream, cost class, evidence count, and question metadata.

## 10. Knowledge And Vector Providers

Current baseline:

- Markdown heading-aware chunking.
- source and line-range citation.
- token-overlap deterministic retrieval.
- `EvidenceChunk` output.
- evidence threshold validation.

Vector strategy:

- Vector stores live behind adapters.
- `[vector]` optional dependency can include Chroma and sentence-transformers.
- Milvus、pgvector、remote enterprise search 等实现必须 still return `EvidenceChunk`.
- Retrieval never decides final answer.

## 11. Model Providers

Protocol:

```python
class ModelProvider(Protocol):
    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self: ...
    def estimate_tokens(self, request: ModelRequest) -> int | None: ...
    def generate(self, request: ModelRequest) -> ModelResponse: ...
```

Providers:

| Provider | Status |
| --- | --- |
| `deterministic` | implemented regression baseline |
| `openai_compatible` | implemented optional remote provider |
| `azure_openai` | placeholder with clear failure |
| `anthropic` | placeholder with clear failure |

Trace safety:

- `model_request` stores provider/model/message counts/prompt lengths/token estimate, not raw prompt.
- `model_response` stores finish reason/content length/token usage, not raw response.
- `model_error` stores normalized error class/code/message, not raw provider body or headers.

## 12. Tool Gateway And MCP

ToolGateway is the governed tool entry point.

Current behavior:

- `tools.yaml` declares allowlist and risk level.
- parameter allowlist/denylist is enforced.
- high-risk tool calls require approval.
- mock `customer_lookup` proves requested/granted/denied/timeout paths.

Real MCP strategy:

- MCP stdio/HTTP transport is an adapter behind ToolGateway.
- MCP schemas map into Proof Agent tool config and result contracts.
- LangGraph interrupt may implement pause/resume, but `ApprovalState` and trace remain the facts.

## 13. Memory Boundary

Current baseline is session memory.

Rules:

- All writes pass `before_memory_write`.
- Sensitive fields are denied or redacted.
- memory read/write emits trace events.
- Persistent memory providers require retention, deletion, redaction, and tenant boundary design before adoption.

## 14. Validators

Validators are the admission layer for candidate outputs and tool results.

| Validator | Purpose |
| --- | --- |
| schema | final output shape |
| evidence | evidence threshold |
| safety | secret and unsafe string detection |
| citations | final citations supported by accepted evidence |
| tool result | tool output shape |

Standard candidate path:

```text
ModelResponse.content
  -> validate_final_output_schema
  -> validate_no_secret_strings
  -> validate_citations_supported_by_evidence
  -> final_output or governed refusal
```

LLM-as-judge can become a later audited validator. It must not replace deterministic gates.

## 15. Trace, Receipt, RunStore

Core trace events:

```text
run_started
manifest_loaded
policy_decision
retrieval_started
retrieval_result
evidence_evaluation
model_request
model_response
model_error
approval_requested
approval_granted
approval_denied
approval_timeout
tool_request
tool_result
memory_read
memory_write_requested
memory_write_decision
final_output
redaction_applied
artifact_written
run_failed
```

Receipt sections:

- final outcome
- policy decisions
- evidence summary
- tool approval status
- memory status
- model usage or model error
- audit artifacts
- redaction summary

RunStore:

- saves `trace.jsonl`, `governance_receipt.md`, `run_meta.json`
- maintains `runs/latest`
- writes per-run history under `runs/history/{run_id}`
- powers Dashboard API read projections

## 16. Dashboard API

Dashboard API is observability, not execution.

Routes:

| Route | Purpose |
| --- | --- |
| `/api/health` | service health |
| `/api/runs` | run list, filters, pagination |
| `/api/runs/{run_id}` | run detail |
| `/api/runs/{run_id}/trace` | trace events |
| `/api/runs/{run_id}/receipt` | receipt markdown |
| `/api/stats` | outcome distribution and pending approvals |

Rules:

- API serializers define public response shapes.
- API cannot bypass CLI/workflow.
- Static SPA may be mounted when built assets exist.
- Approval Console is a future UI on top of approval state, not a new tool execution path.

## 17. CLI And Docker

CLI commands:

| Command | Purpose |
| --- | --- |
| `proof-agent demo` | deterministic three-scenario demo |
| `proof-agent run` | run one Enterprise QA question |
| `proof-agent doctor` | local, Docker, sample, provider readiness |
| `proof-agent inspect` | summarize trace or receipt |
| `proof-agent compare` | Plain RAG vs Harness RAG |
| `proof-agent dashboard` | start Dashboard API / SPA |

Docker:

- `docker compose up` runs deterministic demo by default.
- Docker path must not require API keys.
- Remote provider env vars can be passed at runtime.

## 18. Dependencies

Core dependencies:

```toml
dependencies = [
  "typer>=0.12.0",
  "pydantic>=2.7.0",
  "pyyaml>=6.0.1",
  "jinja2>=3.1.0",
  "langgraph>=1.1.0",
  "langchain-mcp-adapters>=0.1.0",
  "mcp[cli]>=1.27.0",
]
```

Optional extras:

```toml
dev = ["pytest", "ruff", "mypy", "httpx"]
dashboard = ["fastapi", "uvicorn"]
openai = ["openai"]
vector = ["sentence-transformers", "chromadb"]
```

Dependency rules:

- deterministic demo cannot require optional extras.
- provider SDKs belong in provider-specific extras.
- vector dependencies belong in `[vector]`.
- dashboard runtime belongs in `[dashboard]`.

## 19. Error Codes

| Code | Subsystem | Purpose |
| --- | --- | --- |
| `PA_CONFIG_001` | Config | missing field, invalid shape, missing path |
| `PA_CONFIG_002` | Config | unsupported runtime/template/memory |
| `PA_SCHEMA_001/002` | Schema | contract/schema validation |
| `PA_KNOWLEDGE_001/002` | Knowledge | provider/path/retrieval errors |
| `PA_MODEL_001` | Model | unsupported provider, placeholder, missing SDK |
| `PA_MODEL_002` | Model | provider API error |
| `PA_MODEL_003` | Model | auth failure or missing API key env |
| `PA_MODEL_004` | Model | provider timeout |
| `PA_POLICY_001` | Policy | policy file or rule error |
| `PA_TOOL_001` | Tool | unregistered tool or invalid parameters |
| `PA_APPROVAL_001` | Approval | invalid approval state |
| `PA_AUDIT_001` | Audit | trace write/read error |
| `PA_RECEIPT_001` | Receipt | receipt render error |
| `PA_SECRET_001` | Secret | secret-looking config or content |

## 20. Tests And Verification

Runtime changes should run:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
uv run --extra dev proof-agent demo
```

Documentation-only changes should run:

```bash
git diff --check
```

Remote provider tests must mock SDK clients and never require real API keys.

## 21. Roadmap

| Phase | Goal |
| --- | --- |
| 0 | contract and positioning baseline |
| 1 | deterministic Harness MVP with CLI/Docker |
| 2 | remote model governance and model trace |
| 3 | RunStore and Dashboard API |
| 4 | production adapters: LangChain/LangGraph, real MCP, vector stores, Azure/Anthropic, streaming |
| 5 | Agent Control Platform: Dashboard UI, Approval Console, RBAC, multi-template, external observability |

## 22. Stability Rules

1. New capabilities define contracts before adapters.
2. New providers cannot break deterministic demo.
3. New runtime adapters cannot leak SDK types into public contracts.
4. New tools must go through ToolGateway.
5. New trace events must define redaction and receipt projection.
6. New API routes must not create alternate execution semantics.
7. New memory providers must define retention, deletion, redaction, and tenant boundary.
8. New evaluators must define the control path for failure.
