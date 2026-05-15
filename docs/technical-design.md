# Proof Agent Technical Design

> Authoritative technical design document. Proof Agent is a Controlled Agent Harness Framework: it uses Harness Engineering to manage the Agent lifecycle and connects remote models, LangChain/LangGraph, vector stores, real MCPs, Dashboard, CLI, and Docker through adapters.

## 1. Core Positioning

The core of Proof Agent is neither a RAG demo nor a wrapper for an Agent runtime, but a **Controlled Agent Harness Framework**.

It places Agent execution into a Control Envelope:
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

The current deterministic demo is a regression baseline, not a product boundary. The project must support production integration, but all integrations must submit to the same Harness lifecycle.

Core goals:
1. Manage the complete Agent lifecycle: config, workflow, policy, retrieval, model, tool, memory, validation, trace, receipt.
2. Preserve a no-API-key deterministic demo to prove that the governance chain is reproducible.
3. Support adapters for remote models, LangChain/LangGraph, vector stores, real MCPs, and the Dashboard.
4. Provide CLI and Docker execution entry points.
5. Maintain contract-first design; third-party SDK types must not leak into public contracts.

Current demo acceptance results:
```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

Current ReAct demo acceptance results:
```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

## 2. Design Principles

### 2.1 Harness Control Flow
The LLM only generates candidate content. Decisions on whether to retrieve, call a tool, write to memory, call a remote model, or accept an output are entirely determined by the Workflow, PolicyEngine, ToolGateway, and Validators.

### 2.2 Contract-first
Public boundaries are defined by `proof_agent/contracts/`. SDK types from LangGraph, LangChain, MCP, Chroma, OpenAI, Azure, Anthropic, etc., may only exist in the adapter layer.

### 2.3 Deterministic baseline
The local deterministic path must always be runnable for regression testing and enterprise evaluation. It does not limit the evolution of remote models or platform capabilities.

### 2.4 Remote output defaults to untrusted
ModelProvider returns candidate outputs. Candidate outputs must pass schema, safety, and citation/evidence validators before becoming the final output.

### 2.5 Trace is the source of truth
JSONL Trace is the execution source of truth. Governance Receipt is a readable projection of the trace. The Receipt cannot reverse-infer unrecorded facts.

### 2.6 Explicit configuration, no secrets
`agent.yaml` can declare env var names, providers, models, timeouts, temperatures, and token limits. It MUST NOT contain raw API keys, bearer tokens, passwords, connection strings, or provider secrets.

### 2.7 Replaceable Adapters
Runtime, model, knowledge, tool, memory, and dashboard implementations can be replaced, but they cannot change the Harness semantics.

## 3. Overall Architecture

The overall architecture of Proof Agent is not a simple top-down pipeline, but a controlled Agent Harness centered around the Control Plane:

- Delivery / Entry exposes the execution entry points.
- Bootstrap / Composition handles reading configs, validating configs, and assembling dependencies.
- Control Plane owns Harness Engineering semantics and all governance decisions.
- Runtime Plane handles Agent framework runtimes, state progression, checkpoints, interrupt/resume, and streaming mechanics.
- Capability Layer owns orchestratable capabilities like models, knowledge bases, memory, tools, MCP, and Skills.
- Contracts & Ports provide the vertical foundation, defining the common language and replaceable ports between all layers.
- Audit & Observability is the side-channel fact system, continuously recording execution facts and providing Receipt, RunStore, and Dashboard read models.

```text
                         Delivery / Entry
             CLI | Docker | Template | future Execution API
                                  |
                                  v
                       Bootstrap / Composition
          agent.yaml loader | config validation | registry | wiring
                                  |
                                  v
+------------------------------------------------------------------+
|                           Control Plane                          |
|                                                                  |
|  Workflow | Orchestrator | Policy Gates | Approval State Machine |
|  Evidence Evaluation | Validators | Memory Policy | Outcome      |
+------------------------------------------------------------------+
                                  |
                                  v
                           Runtime Plane
      Plain Python Runner | LangGraph Adapter | LangChain Adapter
      state execution | checkpoint | interrupt/resume | streaming
                                  |
                                  v
                          Capability Layer
      Model | Knowledge/Retrieval | Memory | Tool/MCP | Skill Packs
      provider adapters | local/remote implementations | registries
                                  |
                                  v
                           Infrastructure
      OpenAI-compatible | Azure | Anthropic | local markdown | vector DB
      MCP stdio/http | local tools | session/remote memory stores

Contracts & Ports:
  AgentManifest | ModelRequest/Response | EvidenceChunk | ToolRequest/Result
  PolicyDecision | ApprovalState | TraceEvent | RunResult | provider protocols

Audit & Observability side channel:
  Control/Runtime/Capability events -> TraceWriter -> JSONL Trace
    -> RunStore -> Governance Receipt
    -> Dashboard API / inspect / stats read projections
```

Enterprise QA current main chain (In MVP, some Bootstrap/Composition is still done internally by the orchestrator, and will be pulled out as an independent assembly entry later):

```text
CLI / Docker
  -> run_enterprise_qa
      -> load_agent_manifest
      -> resolve current dependencies from manifest
      -> emit run_started / manifest_loaded
      -> PolicyEngine(before_retrieval)
      -> PolicyEngine(before_retrieval_step)
      -> retrieval_step through KnowledgeProvider
      -> evaluate_evidence
      -> PolicyEngine(before_answer)
      -> build ModelRequest
      -> PolicyEngine(before_model_call)
      -> ModelProvider.generate
      -> validators
      -> optional ToolGateway approval path
      -> SessionMemory policy/write
      -> final_output
  -> persist trace and run metadata
  -> render Governance Receipt
  -> expose Dashboard API read projections
```

Controlled ReAct Enterprise QA adds a planner loop around the same Control Plane:

```text
CLI / API / Conversation turn
  -> load react_enterprise_qa Agent Contract
  -> ReAct planner proposes a fixed action
  -> emit reasoning_summary and action_proposal
  -> Harness Review Subagent suggests a decision for reviewed points
  -> PolicyEngine/Harness makes the final decision
  -> execute allowed retrieval/model/tool/clarification behavior
  -> deterministic before_answer evidence and citation gate
  -> final_output with answer, refusal, approval wait, clarification wait, or escalation
  -> persist trace and Governance Receipt
```

The planner and review subagent are inputs to governance, not governance authorities.

Layer boundary rules:
- Control Plane owns decisions. Runtime and Capability layers cannot bypass PolicyEngine, Approval, Validators, or Outcome mapping.
- Runtime Plane owns execution mechanics. LangGraph/LangChain can provide graph execution, checkpoint, interrupt/resume, and streaming hooks, but cannot redefine Harness governance semantics.
- Capability Layer owns concrete abilities. Model, knowledge, memory, tools, MCP, and Skills are exposed through Proof Agent ports and contracts.
- Skills are capability packs. A Skill may include prompts, tool schemas, retrieval recipes, policy rules, validators, or workflow fragments, but it must be registered into the Control/Runtime/Capability model rather than becoming a separate execution path.
- Contracts & Ports are not an execution layer. They define stable DTOs, public contracts, and provider protocols used across layers.
- Audit & Observability is a side-channel only. Trace is written throughout execution; Receipt and Dashboard API are read projections and must not create a second workflow or tool execution path.

## 4. Current Implementation Baseline

| Area | Current implementation |
| --- | --- |
| Delivery | `delivery/cli.py` exposes `demo`, `run`, `doctor`, `inspect`, `compare`, `server` |
| Docker | `Dockerfile`, `docker-compose.yml` runs demo by default |
| Contracts | Pydantic v2 frozen models |
| Bootstrap | `bootstrap/` owns YAML loading, path resolution, secret-looking params rejection, and `HarnessInvocation` composition |
| Workflow | `control/workflow/` owns Enterprise QA and Controlled ReAct Enterprise QA Harness behavior plus the workflow template registry |
| Runtime | `runtime/langgraph_runner.py` executes supported `StateGraph` templates through resolved Harness dependencies |
| Policy | `control/policy/` owns retrieval, ReAct review, answer, tool, memory, and model call enforcement points |
| Knowledge | `capabilities/knowledge/` owns Markdown deterministic retrieval; vector stack optional |
| Model | `capabilities/models/` owns `deterministic`, `openai_compatible`; Azure/Anthropic placeholders |
| Tools | `capabilities/tools/` owns ToolGateway, mock `customer_lookup`, approval state |
| Memory | `capabilities/memory/` owns session memory with denylist |
| Validators | `control/validators/` owns schema, evidence, safety, citations, tool result |
| Audit | `observability/audit/` owns JSONL trace, redaction, Governance Receipt, Model Usage |
| Storage/API | `observability/storage/` and `observability/api/` own RunStore, FastAPI health/runs/stats routes |
| Tests/CI | pytest, Ruff, mypy, GitHub Actions |

## 5. Developer Lifecycle

AI Agent owners using Proof Agent should start from the Agent package, not from bare LangGraph/LangChain code. Standard development deployment path:

```text
copy or create Agent package
  -> configure agent.yaml / policy.yaml / tools.yaml / knowledge
  -> run deterministic local validation
  -> inspect trace and Governance Receipt
  -> compare Plain RAG vs Harness RAG on unsupported questions
  -> optionally switch to remote model provider
  -> package with Docker or Python runtime
  -> operate through RunStore, Dashboard API, trace, and receipt
```

Agent package is the developer-facing unit:
```text
agent.yaml
policy.yaml
tools.yaml
knowledge/
questions.yaml      optional evaluation set
expected/           optional expected trace or receipt examples
```

This lifecycle is documented for users in `docs/developer-guide.md`. This technical design document defines the architecture and boundaries that make that lifecycle safe: configuration enters through Bootstrap / Composition, decisions stay in Control Plane, execution mechanics stay in Runtime Plane, concrete integrations stay in Capability Layer, and Audit & Observability remains a side channel.

## 6. Directory Boundaries

```text
proof_agent/
  bootstrap/        manifest loading, validation, and future composition
  capabilities/     concrete model, knowledge, memory, tool, MCP, and Skill adapters
    knowledge/
    memory/
    models/
    tools/
  contracts/        public frozen contracts
  control/          workflow, policy, validators, and governed decisions
    policy/
    validators/
    workflow/
  delivery/         CLI and future execution entry points
  evaluation/       deterministic demo and Plain RAG vs Harness comparison
    compare/
    demo/
  observability/    trace, receipt, storage, and Dashboard read API
    api/
    audit/
    storage/
  runtime/          LangGraph/LangChain runtime adapters
  cli.py            backward-compatible CLI shim
  errors.py         shared error type
```

Architecture layer mapping:

| Architecture layer | Current modules |
| --- | --- |
| Delivery / Entry | `delivery/cli.py`, compatibility shim `cli.py`, Docker assets, templates under `examples/` |
| Bootstrap / Composition | `bootstrap/`, provider registries, current dependency resolution inside `control/workflow/orchestrator.py` |
| Control Plane | `control/workflow/`, `control/policy/`, `control/validators/`, approval state used by ToolGateway, memory policy checks |
| Runtime Plane | `runtime/` |
| Capability Layer | `capabilities/models/`, `capabilities/knowledge/`, `capabilities/memory/`, `capabilities/tools/`, future Skill packs |
| Contracts & Ports | `contracts/`, provider protocols |
| Audit & Observability | `observability/audit/`, `observability/storage/`, `observability/api/` |
| Evaluation / Demo | `evaluation/demo/`, `evaluation/compare/`, `examples/enterprise_qa/`, `examples/react_enterprise_qa/` |

Boundary rules:
- `contracts/` cannot import adapter SDKs.
- `control/workflow/` owns Harness order and calls protocols, not SDK clients.
- `capabilities/models/` owns model SDK integration.
- `capabilities/knowledge/` returns `EvidenceChunk`; it does not decide final answer.
- `capabilities/tools/` is the only tool execution entry.
- `control/validators/` decide whether candidate output may proceed.
- `observability/audit/` records facts and renders receipts; it does not control workflow.
- `observability/api/` and `observability/storage/` expose read-only observability and must not create a second execution path.

## 7. Agent Contract

`agent.yaml` is the public delivery artifact.

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

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

Controlled ReAct example:

```yaml
name: react_enterprise_qa
purpose: "Answer enterprise knowledge questions through a governed ReAct workflow."

workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

react:
  max_steps: 5
  max_tool_calls: 1
  record_reasoning_summary: true
  planner:
    provider: deterministic
    name: react-planner-demo

review:
  mode: auto
  subagent:
    provider: deterministic
    name: harness-review-demo
    timeout_seconds: 5
    max_output_tokens: 500
    fail_closed: true

response:
  include_reasoning_summary: false
  include_review_results: false
```

`react` defines planner limits and adapter selection. `review` defines the advisory Harness Review Subagent. `response` caps optional governance details returned by execution APIs; callers may request `include_governance_details`, but the response only includes details allowed by `response.include_reasoning_summary` and `response.include_review_results`.

The fixed ReAct Action Set is:

```text
ASK_CLARIFICATION
PLAN_RETRIEVAL
RUN_RETRIEVAL_STEP
PROPOSE_TOOL_CALL
GENERATE_FINAL_ANSWER
ESCALATE
STOP
```

Planner output is a proposed action from this closed set. The planner cannot execute retrieval, tools, models, memory writes, or final answers directly.

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
- `react_enterprise_qa` requires the `react` section.
- `review.mode: auto` requires `review.subagent`.
- Raw chain-of-thought must not be recorded, stored, or exposed; only audit-safe Reasoning Summary fields may enter trace, receipt, RunStore, Dashboard API, Conversation API, or response governance details.

## 8. Bootstrap / Composition

Bootstrap / Composition turns an Agent package into a runnable harness instance.

Responsibilities:
- load and validate `agent.yaml`
- resolve relative paths for policy, tools, knowledge, trace, and receipt
- reject raw secrets or secret-looking configuration
- select workflow template and runtime adapter
- resolve model, knowledge, memory, tool, and future Skill registries
- construct Control Plane dependencies without importing provider SDK types into contracts
- fail fast before execution when required files, providers, runtime, or writable audit paths are invalid

Current MVP note:
- `bootstrap/composition.py` exposes `HarnessInvocation`, the thin composition entry point that resolves the Agent Contract into template metadata and governed capabilities.
- The Enterprise QA orchestrator and LangGraph runner consume the resolved invocation rather than independently constructing provider dependencies.
- Future templates should extend the workflow template registry and composition boundary instead of adding template-specific dependency assembly to the Enterprise QA orchestrator.

Rules:
- Bootstrap may read config and instantiate adapters, but it must not make policy decisions.
- Bootstrap may select a Runtime Plane implementation, but it must not redefine workflow semantics.
- Bootstrap may register Capability Layer implementations, but all calls still pass through Control Plane and Proof Agent contracts.

## 9. Contracts & Ports

Contracts & Ports are the vertical foundation used by Control, Runtime, Capability, Audit, and public read models. They define the language between layers; they are not an execution layer.

| Contract | Purpose |
| --- | --- |
| `AgentManifest` | Agent config entry point |
| `PolicyRule` / `PolicyDecision` | rule declaration and decision |
| `ReActActionProposal` / `ReasoningSummary` | governed ReAct action proposal and audit-safe reasoning summary |
| `ReviewDecision` | advisory review result; final authority remains with PolicyEngine/Harness |
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

## 10. Control Plane

Control Plane is the Harness semantic layer. It decides what the Agent is allowed to do, when it must stop, and how a final outcome is produced.

It owns:
- workflow state order
- orchestration semantics
- policy enforcement points
- approval state transitions
- evidence evaluation requirements
- output admission through validators
- memory write policy
- outcome mapping and refusal behavior

It does not own:
- SDK clients
- vector database handles
- MCP sessions
- LangGraph internals
- Dashboard read APIs
- provider-specific error payloads

Current MVP:
- `control/workflow/orchestrator.py` preserves the plain Python Enterprise QA Harness behavior.
- `control/workflow/templates.py` registers the supported workflow templates.
- `control/policy/` evaluates policy rules.
- `control/validators/` admit or block candidate outputs and tool results.
- `capabilities/tools/approval.py` defines approval state, while `capabilities/tools/gateway.py` is the governed tool entry.

Future templates should use a workflow registry or separate workflow modules. Do not keep adding template-specific branches to Enterprise QA orchestrator.

## 11. Runtime Plane

Runtime Plane owns execution mechanics. It may use Agent frameworks, but it must execute Proof Agent Control Plane semantics rather than replacing them.

Runtime responsibilities:
- graph or node execution
- state persistence and checkpointing
- interrupt/resume for approval or human-in-the-loop
- streaming hooks
- retry mechanics where policy allows them
- adapter boundaries for LangGraph or LangChain Agent runtimes

Runtime adapter strategy:
- LangGraph StateGraph, checkpoint, interrupt, and resume belong in `runtime/`.
- LangChain may be used as a runtime adapter when it drives Agent execution, but must still adapt into Proof Agent contracts.
- LangChain model, retriever, or tool wrappers belong in Capability Layer when they provide concrete abilities.
- Runtime details must not leak into config, policy, trace, receipt, dashboard contracts, or public DTOs.
- Runtime cannot bypass PolicyEngine, ApprovalState, Validators, ToolGateway, or trace emission.

Current MVP:
- `runtime/langgraph_runner.py` executes the Enterprise QA LangGraph `StateGraph` with a composed `HarnessInvocation`.
- This keeps runtime mechanics in the Runtime Plane while deterministic Harness behavior remains the regression baseline.

## 12. PolicyEngine

Enforcement points:
```text
before_retrieval
before_retrieval_plan
before_retrieval_step
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

Auto Review Scope for Controlled ReAct:
```text
before_retrieval_plan
before_retrieval_step
before_tool_call
before_model_call
```

`before_answer` remains deterministic evidence and citation governance.

Harness Review Subagent boundary:
- The subagent suggests `allow`, `deny`, `require_approval`, or `escalate`.
- PolicyEngine and the Harness make the final policy decision.
- Invalid review output fails closed.
- Deterministic policy overrides less strict review suggestions and emits `review_overridden`.

Review failure policy:
- tool call -> `require_approval`
- model call -> `deny`
- retrieval plan/step -> `deny` unless explicit fallback exists

## 13. Capability Layer

Capability Layer provides the concrete abilities that an Agent can use. Capabilities are selected by configuration and registries, then invoked through Proof Agent ports under Control Plane governance.

Capability categories:

| Category | Examples | Required boundary |
| --- | --- | --- |
| Model | deterministic, OpenAI-compatible, Azure, Anthropic | `ModelRequest` / `ModelResponse` |
| Knowledge / Retrieval | local Markdown, local vector, remote search | candidate `EvidenceChunk` |
| Memory | session memory, future persistent memory | memory contract plus `before_memory_write` policy |
| Tool / MCP | local tools, mock MCP, real MCP stdio/http | `ToolRequest` / `ToolResult` through ToolGateway |
| Skill Packs | prompt, tool schema, retrieval recipe, policy rule, validator, workflow fragment | registered into Control/Runtime/Capability model |

Rules:
- Capabilities cannot decide final outcome.
- Capabilities cannot call tools, models, or memory outside Control Plane.
- Provider SDK objects must stay inside Capability adapters.
- A Skill is a capability pack, not a second execution path.
- Capability implementations must emit or allow Control Plane to emit trace-safe facts.

## 14. Knowledge And Vector Providers

Current baseline:
- Markdown heading-aware chunking.
- source and line-range citation.
- token-overlap deterministic retrieval.
- `EvidenceChunk` output.
- evidence threshold validation.

Agent Contract shape:
```yaml
knowledge:
  provider: local_markdown
  params:
    path: ./knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
```

Provider names:
- `local_markdown` retrieves candidate evidence from local Markdown files.
- `local_vector` queries an existing local vector index; index build is a separate lifecycle.
- `remote_search` normalizes remote-search-shaped evidence through a first-stage fixture adapter; production HTTP is future work.
- `pageindex` calls a self-hosted PageIndex retrieval endpoint and normalizes `retrieved_nodes` into candidate evidence.

Rules:
- Knowledge providers return candidate `EvidenceChunk` objects only.
- Provider-specific config lives under `knowledge.params`.
- Retrieval orchestration policy lives under the required top-level `retrieval` section.
- `top_k` and `min_score` belong to `retrieval`, not provider params.
- Control Plane evidence evaluation creates accepted or rejected evidence.
- Trace and receipt record evidence summaries by default, not raw evidence content.
- Agentic RAG is a `retrieval.strategy`, not a Knowledge Provider and not a workflow template. With PageIndex, Proof Agent emits a governed retrieval plan and delegates the remote reasoning-based retrieval step to the PageIndex provider while keeping final answer governance local.

Vector strategy:
- Vector stores live behind adapters.
- `[vector]` optional dependency can include Chroma and sentence-transformers.
- Milvus, pgvector, remote enterprise search implementations must still return `EvidenceChunk`.
- Retrieval never decides final answer.

## 15. Model Providers

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

## 16. Tool Gateway And MCP

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

## 17. Memory Boundary

Current baseline is session memory.

Rules:
- All writes pass `before_memory_write`.
- Sensitive fields are denied or redacted.
- memory read/write emits trace events.
- Persistent memory providers require retention, deletion, redaction, and tenant boundary design before adoption.

## 18. Validators

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

## 19. Trace, Receipt, RunStore

Core trace events:
```text
run_started
manifest_loaded
reasoning_summary
action_proposal
review_requested
review_decision
review_error
review_overridden
clarification_requested
policy_decision
retrieval_plan
retrieval_step
retrieval_result
evidence_evaluation
context_admission
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

ReAct trace safety:
- `reasoning_summary` stores audit-safe goal, observations, candidate actions, selected action, rationale summary, risk flags, and required evidence.
- `action_proposal` stores action metadata, redacted parameters, target tool name, and risk level.
- review events store request, suggestion, fail-closed error, override, and final-decision metadata.
- `clarification_requested` records the safe missing-details prompt for `WAITING_FOR_USER_CLARIFICATION`.
- No event may store raw chain-of-thought.

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

## 20. Execution API And Dashboard API

Run Execution API is Delivery behavior. It starts governed Harness runs for
application surfaces such as the Assisted QA Chat Frontend.

Execution routes:
| Route | Purpose |
| --- | --- |
| `POST /api/chat/runs` | start a Published Agent run from a chat surface |
| `POST /api/chat/conversations` | create an assisted chat conversation for a Published Agent |
| `GET /api/chat/conversations/{conversation_id}` | read a conversation timeline |
| `POST /api/chat/conversations/{conversation_id}/runs` | start a run with Controlled Conversation Context |

Rules:
- Application surfaces call Published Agents by stable `agent_id`.
- The request body must not accept arbitrary `agent.yaml` paths.
- Execution still goes through Bootstrap / Composition, Runtime Plane, PolicyEngine, ToolGateway, Validators, Trace, Receipt, and RunStore.
- The first approval continuation shape carries an explicit approval decision into a follow-up run; durable checkpoint resume is future Runtime Plane work.
- Conversation runs admit a trace-safe summary of recent turns as Controlled Conversation Context; prior turns can resolve follow-ups but cannot replace current-turn evidence retrieval.

Dashboard API is observability, not execution.

Dashboard routes:
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
- Dashboard API cannot start runs or bypass CLI/workflow.
- Static SPA may be mounted when built assets exist.
- Approval Console is a future UI on top of approval state, not a new tool execution path.

## 21. CLI And Docker

CLI commands:
| Command | Purpose |
| --- | --- |
| `proof-agent demo` | deterministic three-scenario demo |
| `proof-agent react-demo` | deterministic Controlled ReAct Enterprise QA scenarios |
| `proof-agent run` | run one Enterprise QA question |
| `proof-agent doctor` | local, Docker, sample, provider readiness |
| `proof-agent inspect` | summarize trace or receipt |
| `proof-agent compare` | Plain RAG vs Harness RAG |
| `proof-agent server` | start Dashboard API / SPA |

Docker:
- `docker compose up` runs deterministic demo by default.
- Docker path must not require API keys.
- Remote provider env vars can be passed at runtime.

Deterministic ReAct demo:
```bash
uv run --extra dev --extra dashboard proof-agent react-demo
```

When the package is already installed with required extras, `proof-agent react-demo` is equivalent.

## 22. Dependencies

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

## 23. Error Codes

| Code | Subsystem | Purpose |
| --- | --- | --- |
| `PA_CONFIG_001` | Config | missing field, invalid shape, missing path |
| `PA_CONFIG_002` | Config | unsupported runtime/template/memory |
| `PA_SCHEMA_001/002` | Schema | contract/schema validation |
| `PA_KNOWLEDGE_001/002` | Knowledge | provider/params/retrieval errors |
| `PA_RETRIEVAL_001` | Retrieval | recognized retrieval strategy not executable in this build |
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

## 24. Tests And Verification

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

## 25. Roadmap

| Phase | Goal |
| --- | --- |
| 0 | contract and positioning baseline |
| 1 | deterministic Harness MVP with CLI/Docker |
| 2 | remote model governance and model trace |
| 3 | RunStore and Dashboard API |
| 4 | production adapters: LangChain/LangGraph, real MCP, vector stores, Azure/Anthropic, streaming |
| 5 | Agent Control Platform: Dashboard UI, Approval Console, RBAC, multi-template, external observability |

## 26. Stability Rules

1. New capabilities define contracts before adapters.
2. New providers cannot break deterministic demo.
3. New runtime adapters cannot leak SDK types into public contracts.
4. New tools must go through ToolGateway.
5. New trace events must define redaction and receipt projection.
6. New API routes must not create alternate execution semantics.
7. New memory providers must define retention, deletion, redaction, and tenant boundary.
8. New evaluators must define the control path for failure.
