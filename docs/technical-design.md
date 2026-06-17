# Proof Agent Technical Design

> Authoritative technical design document. Proof Agent is a Controlled Agent Harness Framework: it uses Harness Engineering to manage the Agent lifecycle and connects remote models, LangChain/LangGraph, governed knowledge providers, real MCPs, Dashboard, CLI, and Docker through adapters.

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
3. Support adapters for remote models, LangChain/LangGraph, governed local and remote knowledge sources, real MCPs, and the Dashboard.
4. Provide CLI and Docker execution entry points.
5. Maintain contract-first design; third-party SDK types must not leak into public contracts.

Current deterministic demo acceptance results, backed by the React Enterprise QA baseline:
```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

The `react-demo` command remains as a compatibility regression command with the same expected outcomes:
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
      LangGraph Runner | future LangChain Adapter
      state execution | checkpoint | interrupt/resume | streaming
                                  |
                                  v
                          Capability Layer
      Model | Knowledge/Retrieval | Memory | Tool/MCP | Skill Packs
      provider adapters | local/remote implementations | registries
                                  |
                                  v
                           Infrastructure
      OpenAI-compatible | Azure | Anthropic | local markdown | local index | remote retrieval
      MCP stdio/http | local tools | session/remote memory stores

Contracts & Ports:
  AgentManifest | ModelRequest/Response | EvidenceChunk | ToolRequest/Result
  PolicyDecision | ApprovalState | TraceEvent | RunResult | provider protocols

Audit & Observability side channel:
  Control/Runtime/Capability events -> TraceWriter -> JSONL Trace
    -> RunStore -> Governance Receipt
    -> Dashboard API / inspect / stats read projections
```

Enterprise QA current main chain:

```text
CLI / Docker
  -> run_with_langgraph
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
  -> load react_enterprise_qa_v2 Agent Contract
  -> resolve intent into an audit-safe summary
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

Workflow Stage Prompt Configuration is a governed extension to the Agent Contract, not a
new execution path. The backend-owned Workflow Template Descriptor publishes the fixed
public stage graph for Dashboard rendering, including stage ids, labels, predecessor and
successor relationships, branch conditions, model-bearing status, editable Prompt fields,
and allowlisted context options. The Dashboard can configure only `workflow.stages[]`
business context and selected context options for registered stages. It cannot freely edit
topology, disable stages, or replace Harness-owned control prompts.

At runtime, stage Prompt text is appended only as a sanitized Business Context Addendum
after Harness control prompts and structured control context. Model-bearing stages can
receive addendum content in their model request user payload; review subagents receive
only trace-safe stage context summaries. Non-model governed stages can record configured
context summaries and deterministic wording context, but do not alter Harness logic.
Trace and receipts record `workflow_stage_context_applied` summary events and never store
full stage Prompt text.

Autonomous Customer Service Mode adds a customer-facing delivery path around the same Harness:

```text
Unified Chat Frontend `/customer` mode
  -> Customer Run API
  -> mock customer session context
  -> customer authorization guard for account data
  -> optional policy-authorized read-only tool
  -> governed Harness run for evidence-backed answers
  -> Customer-Safe Response Projection
  -> Customer Response Snapshot
  -> optional internal customer_handoff_created trace event
  -> Internal Handoff Monitor projection
```

The customer path is deliberately separate from the operator-facing Chat API even though both modes are delivered by the unified Chat SPA. Customer responses must not contain trace links, receipt links, policy decisions, review results, approval state, raw tool parameters, or internal handoff state. Handoff remains an internal trace/projection concept, not a customer-visible `ESCALATED_TO_HUMAN` outcome.

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
| Delivery | `delivery/cli.py` exposes `demo`, `run`, `doctor`, `inspect`, `compare`, `dev`, `server`, continuous `knowledge-worker`, and bounded `knowledge-worker --once` |
| Docker | `Dockerfile`, `docker-compose.yml` runs demo by default |
| Contracts | Pydantic v2 frozen models |
| Bootstrap | `bootstrap/` owns YAML loading, path resolution, secret-looking params rejection, Shared Model Connection resolution, and `HarnessInvocation` composition |
| Workflow | `control/workflow/` owns Enterprise QA and Controlled ReAct Enterprise QA Harness behavior plus the workflow template registry |
| Runtime | `runtime/langgraph_runner.py` executes supported `StateGraph` templates through resolved Harness dependencies |
| Policy | `control/policy/` owns retrieval, ReAct review, answer, tool, memory, and model call enforcement points |
| Knowledge | `control/knowledge/` owns Control Plane retrieval orchestration; `capabilities/knowledge/` owns Markdown deterministic retrieval, Local Index runtime load, source-owned ingestion/routing model resolution, asynchronous Local Index ingestion, and remote adapter boundaries |
| Model | `capabilities/models/` owns `deterministic`, `openai_compatible`, `openai`, `deepseek`; Azure/Anthropic placeholders; Dashboard Configuration > Models owns reusable Shared Model Connections |
| Tools | `capabilities/tools/` owns ToolGateway, local handler loading, approval state |
| Memory | `capabilities/memory/` owns session memory with denylist |
| Validators | `control/validators/` owns schema, evidence, safety, citations, tool result |
| Audit | `observability/audit/` owns JSONL trace, redaction, Governance Receipt, Model Usage, and model connection resolution events |
| Storage/API | `observability/storage/` and `observability/api/` own RunStore, FastAPI health/runs/stats routes; `configuration/local_store.py` and `delivery/configuration_api.py` own Shared Model Connection configuration routes |
| Customer Service | `delivery/customer_api.py`, `delivery/customer_adapters.py`, `observability/storage/customer_store.py`, `contracts/customer.py`, and `contracts/handoff.py` own customer-safe projections, the Customer Run Adapter seam, and internal handoff monitoring |
| Tests/CI | pytest, Ruff, mypy, GitHub Actions |

## 5. Developer Lifecycle

AI Agent owners using Proof Agent should start from the Agent package, not from bare LangGraph/LangChain code. Standard development deployment path:

```text
copy or create Agent package
  -> configure agent.yaml / policy.yaml / tools.yaml / knowledge
  -> run deterministic local validation
  -> inspect trace and Governance Receipt
  -> compare Plain RAG vs Harness RAG on unsupported questions
  -> optionally switch to a Shared Model Connection or custom remote model provider
  -> package with Docker or Python runtime
  -> operate through RunStore, Dashboard API, Configuration > Models, trace, and receipt
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
  evaluation/       deterministic demo, Plain RAG comparison, and post-run Evaluation Analyzer
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
| Delivery / Entry | `delivery/cli.py`, compatibility shim `cli.py`, Docker assets, and public packages under `examples/` |
| Bootstrap / Composition | `bootstrap/`, provider registries, Shared Model Connection resolution, current dependency resolution inside `control/workflow/orchestrator.py` |
| Control Plane | `control/workflow/`, `control/policy/`, `control/validators/`, approval state used by ToolGateway, memory policy checks |
| Runtime Plane | `runtime/` |
| Capability Layer | `capabilities/models/`, `capabilities/knowledge/`, `capabilities/memory/`, `capabilities/tools/`, future Skill packs |
| Contracts & Ports | `contracts/`, provider protocols |
| Audit & Observability | `observability/audit/`, `observability/storage/`, `observability/api/`, configuration audit records |
| Evaluation / Demo | `evaluation/demo/`, `evaluation/compare/`, internal fixtures under `evaluation/demo/fixtures/`, public packages under `examples/insurance_customer_service/` and `examples/institution_insurance_specialist/`, and the post-run Evaluation Analyzer described in `docs/evaluation-system.md` |

Boundary rules:
- `contracts/` cannot import adapter SDKs.
- `control/workflow/` owns Harness order and calls protocols, not SDK clients.
- `capabilities/models/` owns model SDK integration.
- `capabilities/knowledge/` returns `EvidenceChunk`; it does not decide final answer.
- `capabilities/tools/` is the only tool execution entry.
- `control/validators/` decide whether candidate output may proceed.
- `observability/audit/` records facts and renders receipts; it does not control workflow.
- `observability/api/` and `observability/storage/` expose read-only observability and must not create a second execution path.
- Evaluation Analyzer is post-run analysis only. It reads Evaluation Subject Manifest, Trace, Governance Receipt, run metadata, and audience-safe response projection artifacts; it must not start runs, call models, retrieve knowledge, execute tools, invoke PolicyEngine, or import Runtime/Control Workflow/Capability/Bootstrap execution paths.
- Evaluation Run Producer is a future helper, separate from Analyzer. It may create sample subjects only through existing execution surfaces and must not own gate logic or evaluation semantics.

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

capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: true
    provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
```

Controlled ReAct V2 example:

```yaml
name: react_enterprise_qa_v2
purpose: "Answer enterprise knowledge questions through a governed ReAct workflow with Intent Resolution."

workflow:
  runtime: langgraph
  template: react_enterprise_qa_v2
  template_descriptor_version: react_enterprise_qa.v2
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
    fail_closed: true
    params:
      timeout_seconds: 5
      max_output_tokens: 500

response:
  include_reasoning_summary: false
  include_review_results: false
```

`react` defines planner limits and adapter selection. For `react_enterprise_qa_v2`, the same planner configuration also powers Intent Resolution before ReAct planning. `review` defines the advisory Harness Review Subagent. `response` caps optional governance details returned by execution APIs; callers may request `include_governance_details`, but the response only includes details allowed by `response.include_reasoning_summary` and `response.include_review_results`.

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

### LLM Role Boundaries

Proof Agent integrates real LLM behavior through role-specific model calls rather than a single autonomous model loop. The final answer model, LLM ReAct Planner, and LLM Harness Review Subagent all resolve providers through the shared Model Provider Registry, but each role is configured independently in `model`, `react.planner`, or `review.subagent`.

Planner and reviewer outputs must satisfy the Model Output JSON Contract. The Harness parses model output into `ReActActionProposal` or `ReviewDecision` before any output can affect workflow routing, policy review, tool execution, or final answer behavior. Provider-native tool calls are not executable control actions in V1; future provider-native payloads must first be converted into Harness-governed action proposals.

Model role config supports three shapes:

- `model_source: shared` references a live Dashboard-managed Shared Model Connection by `connection_id`.
- `model_source: custom` stores provider, model name, base URL, and env credential reference directly on the Agent or Knowledge Source.
- Legacy inline `provider/name/params` remains accepted for deterministic fixtures and standalone packages.

Shared Model Connections are live references, not pinned versions. They store reusable connection parameters: display name, provider, model identifier, optional clear-text `base_url`, environment credential reference, optional account-scope env refs, and optional default `timeout_seconds`. Agent roles and Knowledge Sources keep usage parameters such as `temperature`, `max_output_tokens`, retrieval budgets, routing budgets, and reviewer controls. A role or Source-owned `params.timeout_seconds` overrides the Shared Model Connection default.

Shared reference example:
```yaml
model:
  model_source: shared
  connection_id: model_deepseek_default
  params:
    temperature: 0
    max_output_tokens: 800
    timeout_seconds: 10
```

Custom model example:
```yaml
model:
  model_source: custom
  provider: deepseek
  name: deepseek-chat
  base_url: https://api.deepseek.com
  credential_ref:
    type: env
    name: DEEPSEEK_API_KEY
  params:
    temperature: 0
    max_output_tokens: 800
```

Legacy OpenAI-compatible example:
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
- Allow `credential_ref: {type: env, name: ...}` for shared/custom model source configuration.
- Reject secret-looking fields such as `api_key`, `authorization`, `bearer`, `password`, `secret`, `access_token`.
- Unsupported provider fails with `PA_MODEL_001`.
- Missing shared model connection fails with `PA_MODEL_CONNECTION_001`.
- Archived shared model connection is allowed for existing runtime resolution with a publish-blocking warning, but production publication fails with `PA_MODEL_CONNECTION_002`.
- Provider runtime errors should emit `model_error` once trace exists.
- `react_enterprise_qa` and `react_enterprise_qa_v2` require the `react` section.
- `react_enterprise_qa_v2` adds Intent Resolution before ReAct planning; it reuses `react.planner` model configuration while emitting a distinct `intent_resolution` model-call role and audit event.
- `review.mode: auto` requires `review.subagent`.
- `review.low_risk_fast_path` defaults to `true`; low-risk retrieval and evidence-backed answer enforcement points may skip the reviewer model only after deterministic policy returns `allow`, and the runtime must still emit review/policy trace events with the fast-path reason.
- Reviewer model usage settings belong under `review.subagent.params`; old top-level reviewer usage fields are rejected instead of dual-read.
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
| `ModelConnectionResolutionRecord` | trace-safe record of shared/custom/inline model source resolution |
| `ToolRequest` / `ToolResult` | tool request/result semantics |
| `ApprovalState` | tool approval lifecycle |
| `TraceEvent` | JSONL event envelope |
| `ReceiptOutcome` | final outcome enum |
| `RunResult` | CLI-facing result |
| `RunSummary` / `RunDetail` | Dashboard-facing read contracts |
| `WorkflowRunProjection` | Dashboard-facing Workflow stage read projection for Run Detail |

Evolution rules:
- Add fields as optional/defaulted when possible.
- Treat public enum changes as compatibility decisions.
- Never store SDK objects or secrets in contracts.
- Dashboard contracts are read projections, not workflow state.
- `WorkflowRunProjection` is derived by RunStore from trace-safe Workflow Template
  execution facts. It may expose stage ids, labels, status, outcome, safe
  summaries, context application summaries, produced fact refs, and related event
  ids, but must not expose continuation state, raw runtime state, raw Prompt or
  context, raw evidence/tool payloads, provider responses, or chain-of-thought.

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
- knowledge store handles
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
| Knowledge / Retrieval | local Markdown, local index, trusted remote adapters | candidate `EvidenceChunk` |
| Memory | session memory, future persistent memory | memory contract plus `before_memory_write` policy |
| Tool / MCP | local tools, mock MCP, real MCP stdio/http | `ToolRequest` / `ToolResult` through ToolGateway |
| Skill Packs | prompt, tool schema, retrieval recipe, policy rule, validator, workflow fragment | registered into Control/Runtime/Capability model |

Rules:
- Capabilities cannot decide final outcome.
- Capabilities cannot call tools, models, or memory outside Control Plane.
- Provider SDK objects must stay inside Capability adapters.
- A Skill is a capability pack, not a second execution path.
- Capability implementations must emit or allow Control Plane to emit trace-safe facts.

## 14. Knowledge Hub And Retrieval Providers

Current baseline:
- Markdown heading-aware chunking for deterministic demos and local development.
- source and line-range citation.
- token-overlap deterministic retrieval.
- `EvidenceChunk` output.
- evidence threshold validation.
- shared Control Plane Knowledge Retrieval Service for Enterprise QA and Controlled ReAct.
- deterministic binding metadata routing for single-step, reviewed/fallback, and planner/evaluator-backed agentic retrieval.
- binding-level provider coordination, required/advisory failure handling, exact deduplication, WRRF ordering, no-evidence reason codes, and provider-call trace summaries for blended retrieval.
- explicit `package_knowledge_sources[]` plus `knowledge_bindings[].source_ref` Agent Contract shape.
- Configuration Store Source publication validation and Published Agent binding resolution for shared `local_index` snapshots and shared `http_json` remote configuration versions.
- Configuration Store Source lifecycle management with required `lifecycle_state`, archive, restore, deletion eligibility, narrow physical deletion, and global configuration audit for deletion records.
- Source-owned `local_index` ingestion and routing model config can reference Shared Model Connections or store custom provider config.

Knowledge Hub target shape:
- Knowledge Sources own provider configuration and publication lifecycle.
- Knowledge Sources expose exactly `ACTIVE` or `ARCHIVED`; physical deletion is a guarded removal operation, not a visible Source state.
- Draft Agents store Agent Knowledge Bindings, not provider credentials or endpoints.
- Published Agent Versions execute with a Resolved Knowledge Binding Set pinned to source snapshot or configuration versions.
- Knowledge Retrieval Service in the Control Plane owns source routing, provider coordination, cross-source fusion, citation enforcement, and evidence admission for both Enterprise QA and Controlled ReAct workflows.

Agent package deterministic shape:
```yaml
package_knowledge_sources:
  - source_id: enterprise_qa_knowledge
    name: Enterprise QA Knowledge
    provider: local_markdown
    params:
      path: ./knowledge

knowledge_bindings:
  - binding_id: enterprise_qa_knowledge_binding
    source_ref:
      scope: package
      source_id: enterprise_qa_knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2
```

Knowledge Hub V1 provider set:
- `local_markdown` retrieves candidate evidence from local Markdown files for deterministic demos and development fixtures.
- `local_index` retrieves from published local LlamaIndex TreeIndex artifacts built by Knowledge Source Ingestion.
- `http_json` is the trusted generic remote adapter with a default Remote Retrieval Protocol and bounded declarative mappings for non-standard remote APIs.
- trusted typed remote adapters may be added through code installation and adapter descriptors.
- `pageindex` and `local_vector` are outside the target provider set and are rejected rather than retained as hidden compatibility entries.

Rules:
- Knowledge Provider Adapters retrieve one selected source and return candidate `EvidenceChunk` objects only.
- Provider-specific config lives in package-local Knowledge Sources or Configuration Store Knowledge Sources, not in shared Agent binding entries.
- Source-owned `ingestion_model` and `routing_model` use the same shared/custom model source shapes as Agent model roles. Agent Knowledge Bindings cannot override them.
- `routing_model` inherits `ingestion_model` when omitted. Source-owned `params.timeout_seconds` overrides the Shared Model Connection default, while retrieval `top_k` remains on the Agent retrieval policy.
- Dashboard-managed shared Source bindings use `source_ref: {scope: shared, source_id: ...}` and do not copy provider params into the Agent Contract.
- Dashboard-managed shared Source bindings require an active published Source. Archived shared Sources are excluded from new binding and rejected during validation and publication resolution.
- Archive is the default delete-like Source action. It blocks Source writes and new Agent binding while preserving documents, snapshots, publications, audit, and pinned Published Agent Version execution.
- Physical Source deletion is allowed only for archived empty Sources with no Draft Agent bindings, Published Agent Version references, publications, snapshots, managed documents, quarantined uploads, ingestion jobs, or audit-retention blocker. The deletion audit is written outside the Source directory before removal.
- Local Configuration Store data missing `KnowledgeSource.lifecycle_state` is invalid and must be reset/rebuilt rather than silently upgraded in place.
- Retrieval orchestration policy lives under the required top-level `retrieval` section and the Control Plane Knowledge Retrieval Service.
- `top_k` and `min_score` belong to `retrieval`, not provider params.
- Control Plane evidence evaluation creates accepted or rejected evidence.
- Trace and receipt record evidence summaries by default, not raw evidence content.
- Agentic RAG is a `retrieval.strategy`, not a Knowledge Provider and not a workflow template.
- Controlled ReAct may invoke agentic retrieval as a nested retrieval loop, but `react.max_steps` and `retrieval.max_rounds` remain separate budgets.
- ReAct planners may propose Retrieval Intent only; Knowledge Source Routing remains a Control Envelope step.
- Each RetrievalPlanner query rewrite re-enters service-owned bounded Knowledge Source Routing; RetrievalPlanner cannot select a binding or provider directly.
- Empty routing, selected required source failure, or zero Accepted Evidence produces No Accepted Evidence Outcome and must not call a free-form final-answer model.
- Multiple bound sources require deterministic routing metadata such as binding alias or `routing_metadata` terms before provider calls; the Control Plane does not silently query every binding when routing is ambiguous.
- Selected advisory source failure may continue only when remaining selected bindings produce Accepted Evidence, and degraded retrieval remains visible in Trace, Receipt, and RunStore.

Local Index strategy:
- LlamaIndex TreeIndex construction happens in Knowledge Source Ingestion before source publication.
- Runtime retrieval performs Local Index Runtime Load against an explicitly configured READY `local_index.snapshot.v2` manifest; it must not build indexes on demand inside an Agent run.
- Runtime load resolves `snapshot_path + artifact_root`, validates `snapshot.json` before opening storage, and rejects historical `params.index_path` runtime configuration. Every POSIX-relative revision artifact reference must remain contained beneath `artifact_root` after resolution.
- Runtime routing projects trace-safe filename and allowlisted metadata fields, prefers matching documents when the soft filter finds matches, and falls back to the full snapshot when it does not. It sends at most `100` stable candidates to the Source-owned routing model.
- The routing model returns a strict JSON document-id selection. `params.document_selection_budget` defaults to `8` and accepts integers from `1` through `20`. Runtime loads only the selected immutable revision artifacts, merges candidate evidence deterministically, and fails closed without partial evidence when any selected document cannot be loaded or searched.
- The Control Plane applies `before_model_call` policy and safe model request/response tracing to Source-owned routing-model calls. Retrieval traces consume the provider's one-shot summary through an allowlisted projection and record bounded `document_candidates[]` plus `selected_documents[]` without raw document content.
- Local Index uses stable internal citation URIs and permission-protected citation preview rather than storage paths.
- The current ingestion foundation stages single-file requests and atomic batches as Quarantined Knowledge Upload records before creating document revisions or ingestion jobs. Batch upload accepts at most 50 files, reserves capacity for the full batch before publishing quarantine records, and then validates each staged file independently and asynchronously. Continuous `knowledge-worker` polling performs housekeeping, advances queued quarantine-validation and artifact-build tasks until stopped, and sleeps after idle polls; `knowledge-worker --once` remains available for bounded scripts and tests.
- Accepted originals are UTF-8 Markdown or text-based PDF. The default PDF adapter is `pypdf`, which handles font encoding and CMap extraction while failing closed for malformed PDFs, encrypted PDFs, PDFs above 500 pages, and PDFs without meaningful extracted text.
- Parser identity participates in artifact compatibility. A default PDF identity such as `pypdf:v1@{installed_version}` makes parser upgrades explicit rebuild boundaries.
- Docling is a future layout-aware parser adapter for tables, formulas, images, OCR, and richer structure recovery. It is not the default foundation adapter because ordinary text-based PDF ingestion does not justify its larger pipeline and model-weight concerns.
- Recoverable artifact-build failures persist bounded retry state with 30-second then 120-second backoff. Artifact-key contention defers without consuming the retry budget.
- Source claim concurrency is configured through `params.worker_concurrency`, defaults to `2`, and is bounded from `1` through `8`.
- The snapshot-freeze foundation derives a mutable Candidate Knowledge Source Snapshot from READY active document revisions and a lightweight Source Draft version token. It persists `foundation` freeze-readiness validation, freezes an immutable `local_index.snapshot.v2` manifest of revision artifact references without copying artifacts or rebuilding a merged index, and atomically advances `latest_snapshot_id`.
- Dashboard and API operators may edit the allowlisted routing-only fields `title`, `description`, `tags`, `document_type`, and `business_category` on managed Knowledge Documents. Edits advance the Source Draft version and candidate digest without reingesting the document or rebuilding immutable revision artifacts.
- Source publication validation records an explicit published resource. `local_index` runs smoke retrieval against the latest frozen snapshot and publishes a `local_index_snapshot`; `http_json` runs smoke retrieval against the remote adapter configuration and publishes a `remote_config`. Publishing either validation creates an immutable publication record and advances the legacy `published_snapshot_id` pointer to the published resource id.
- Dashboard-managed Draft Agents may bind only active published shared Sources. Agent validation resolves shared bindings to a `ResolvedKnowledgeBindingSet`, and Published Agent Versions persist that resolved set so production runs use the vetted snapshot path or remote provider configuration version. Agent publication rejects missing, incomplete, source-mismatched, or archived resolved shared bindings.
- Remaining Knowledge Hub gaps include richer remote retrieval preview/health-check UX and hierarchical routing beyond the bounded first `100` candidates.

Remote adapter strategy:
- `http_json` is registered as a trusted remote runtime adapter with a preferred default Remote Retrieval Protocol.
- Non-standard remote APIs may use bounded request and response mappings; mappings are declarative configuration, not executable code.
- Response mappings use JSON Pointer and must yield content plus citation or an adequate structured source reference before evidence can enter Accepted Evidence Context.
- Evidence Admission Score may come only from an approved calibrated adapter descriptor or approved admission scorer.

Implementation sequence:
1. Clean up contracts, loader validation, examples, fixtures, and provider registry so `pageindex` and `local_vector` are no longer target provider entries.
2. Add the Control Plane Knowledge Retrieval Service and route Enterprise QA plus Controlled ReAct retrieval through it; the current service centralizes policy-gated or reviewed provider calls, deterministic binding metadata routing for single-step and reviewed/fallback retrieval, binding-level provider coordination, required/advisory failure handling, exact deduplication, WRRF ordering, no-evidence reason codes, and evidence admission.
3. Complete initial `local_index` runtime load so Agent execution reads READY LlamaIndex-backed Knowledge Source Snapshots without building indexes on demand.
4. Extend planner/evaluator-backed agentic retrieval with the same service-routed provider adapter; each round now re-enters bounded source routing and records round-correlated provider summaries. Add richer retrieval plan summaries and citation enforcement next.
5. Add the Local Index ingestion worker foundation; the current slice stages and validates quarantined uploads, promotes accepted document revisions, builds immutable revision artifacts, persists bounded retries, and exposes continuous worker polling, bounded one-shot CLI execution, and status APIs.
6. Add the Local Index snapshot-freeze foundation; the current slice derives candidate snapshots, persists foundation validation, freezes immutable `local_index.snapshot.v2` manifests, advances the preview-only latest snapshot pointer, and exposes management APIs.
7. Add `local_index.snapshot.v2` multi-document runtime routing; the current runtime validates the immutable manifest, routes over bounded trace-safe document projections, loads selected revision artifacts read-only, fails closed on selected-document errors, and records one-shot routing summaries through the Control Plane.
8. Source publication and production binding resolution are implemented for Configuration Store Sources; the current slice validates publication smoke retrieval, publishes local Source snapshots or remote `http_json` configuration versions, rejects unpublished shared Source bindings, and persists resolved bindings on Published Agent Versions.
9. Add the trusted `http_json` remote adapter with default Remote Retrieval Protocol support and bounded declarative request and response mappings; the current adapter is package-local/runtime-ready and Configuration API creation-ready.
10. Add a Remote Source Publication Contract so shared `http_json` Knowledge Sources can be validated, versioned, published, and bound without masquerading as Local Index snapshots; the current contract records `resource_kind: remote_config`, a stable `ksremote_*` resource id, and the smoke validation evidence counts used for publication.
11. Add richer remote retrieval preview and health-check surfaces, then extend contract, loader, provider, retrieval service, ReAct, trace, receipt, and regression tests before removing legacy compatibility assumptions from documentation examples.

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
| `openai` | implemented OpenAI-compatible named alias with `OPENAI_API_KEY` default |
| `deepseek` | implemented OpenAI-compatible named alias with `DEEPSEEK_API_KEY` and `https://api.deepseek.com` defaults |
| `azure_openai` | placeholder with clear failure |
| `anthropic` | placeholder with clear failure |

Shared Model Connection behavior:
- Configuration > Models is a Dashboard workspace backed by `/api/config/model-connections`.
- Create/update/archive/restore/delete eligibility, reference summaries, validation records, manual smoke tests, and configuration audit are handled in the Local Agent Configuration Store.
- Active connections can be newly selected by Agent and Knowledge Source editors. Archived connections remain readable for existing references but are hidden from new selections and block production publication.
- Shared connection updates affect future resolutions because V1 uses live references rather than published connection versions.
- No raw API keys are stored. The only credential shape in V1 is an environment credential reference; model smoke tests check whether that environment variable is present without persisting the value.

Trace safety:
- `model_request` stores provider/model/message counts/prompt lengths/token estimate, not raw prompt.
- `model_response` stores finish reason/content length/token usage, not raw response.
- `model_error` stores normalized error class/code/message, not raw provider body or headers.
- `model_connection_resolution` stores role, model source, connection id when present, provider, model identifier, lifecycle warning, and override metadata, not credentials or raw provider params.

## 16. Tool Gateway And MCP

ToolGateway is the governed tool entry point.

Current behavior:
- `tools.yaml` declares allowlist and risk level.
- `tools.yaml` can reference an Agent-package Local Tool Handler with `handler: ./module.py:function_name`.
- parameter allowlist/denylist is enforced.
- high-risk tool calls require approval.
- example Agent packages provide deterministic local handlers to prove requested/granted/denied/timeout paths.

Real MCP strategy:
- MCP stdio/HTTP transport is an adapter behind ToolGateway.
- MCP schemas map into Proof Agent tool config and result contracts.
- LangGraph interrupt may implement pause/resume, but `ApprovalState` and trace remain the facts.

## 17. Memory Boundary

Current baseline is session memory.

Long-term memory planning uses three Proof Agent memory scopes:
- Case Memory for one case, task, customer issue, or conversation journey.
- Persistent User Memory for long-lived user or customer facts that can cross conversations.
- Shared Memory for long-lived organizational or Agent-shared facts.

These scopes are product and governance semantics, not storage choices. Mem0, LangGraph Store, databases, vector indexes, graph memory engines, or other external systems may be used as Memory Provider Adapters for any scope. Provider-native taxonomies must not replace Proof Agent memory contracts.

The first implementation stage should focus on Case Memory because it extends existing conversation context, customer journeys, and run audit facts without introducing cross-user long-term profiling. Persistent User Memory and Shared Memory should follow only after Memory Admission, deletion, retention, redaction, and tenant controls are proven on Case Memory.

Case Memory must be generated from governed run facts, such as conversation turns, customer-safe response snapshots, outcomes, accepted evidence summaries, authorized tool result summaries, clarification requests, handoff reasons, and policy decisions. Raw transcripts and unvalidated model text must not be written directly as Case Memory.

Case Memory may include Case Focus: active topics, report dimensions, filters, requested views, and unresolved areas of interest within the current case. Case Focus is not a cross-session user interest profile. Long-term user interests belong to future Persistent User Memory and require separate consent, deletion, and profiling controls.

For report-style questions, Case Memory stores report intent and view context, such as topic, dimensions, filters, requested view, and missing fields. It must not store report result snapshots, raw query output, metric values, rankings, or stale business numbers as memory. Report data must be fetched again through authorized tools or knowledge providers before it can support an answer.

Case Memory writes should happen after the governed run finishes and after trace, receipt, and RunStore artifacts are available. The write produces memory for future runs only; it must not modify the current run's policy decisions, evidence admission, or final output.

Admitted Case Memory can enter Structured Control Context for follow-up resolution, missing-field tracking, and state continuity. It is not Accepted Evidence and cannot support customer-facing business claims. Such claims still require Accepted Evidence or an authorized tool result.

The first Case Memory implementation should define Proof Agent memory contracts and a local memory store before adding external adapters. Mem0 or similar systems should be integrated afterward through a Memory Provider Adapter so external framework behavior cannot shape the Proof Agent memory contract.

A Mem0 adapter may provide storage, retrieval, summarization enhancement, and similarity recall after the local contract is stable. It must not decide whether memory can be written, whether memory can enter a run, how retention works, or whether a remembered fact may support an answer. Those decisions remain in Proof Agent policy, redaction, retention, tenant boundary, and Memory Admission logic. The adapter maps Proof Agent Case Memory to Mem0 `add`, `search`, and filtered deletion calls while preserving `case_id`, `agent_id`, source ids, expiration, sensitivity, status, and facts in metadata.

`memory.provider: mem0` is optional. The deterministic baseline and local Case Memory path do not require Mem0, network access, API keys, or external services. Deployments that enable the Mem0 provider must install the `mem0ai` package in their environment or inject a compatible Mem0 client into the application factory.

The first MemoryCandidate generation path should be deterministic. It should extract candidates only from governed run facts such as outcome, clarification missing fields, handoff reason, accepted evidence summaries, authorized tool result summaries, Customer Response Snapshot, and Case Focus. LLM-based memory summarization is a later extension and must emit a validated JSON MemoryCandidate, fail closed on invalid output, and still pass `before_memory_write` plus sensitive-field validation.

The first MemoryRecord contract should stay minimal:
- `memory_id`
- `scope`, initially `case`
- `case_id`
- `agent_id`
- `summary`
- `facts`
- `source_run_id`
- `source_turn_id`
- `created_at`
- `expires_at`
- `sensitivity`
- `status`

Embeddings, graph edges, confidence sub-scores, provider-native ids, and ranking metadata are adapter concerns until the core admission contract requires them.

The first Case Memory read path should use same-case bounded recall:
- query by `case_id` and `agent_id`
- include only `status: active`
- exclude expired records
- return at most the most recent five records by default
- pass returned records through Memory Admission before any context injection

Cross-case semantic recall is out of the first Case Memory stage because it increases tenant, privacy, and false-transfer risk.

The first Case Memory retention behavior should require `expires_at`, default to 30 days, support deletion by `case_id`, and exclude deleted or expired records from recall. The local adapter marks records as `deleted`; the Mem0 adapter deletes records with `delete_all(agent_id=agent_id, run_id=case_id)`. Both behaviors satisfy the same Proof Agent lifecycle contract: deleted Case Memory must not enter future Memory Admission. Delete operations must be audit-linked. Expired records may remain until cleanup, but they must not be admitted.

The first Memory Admission rules are deterministic:
- `scope` is `case`
- `case_id` matches the current case or conversation
- `agent_id` matches the current Published Agent
- `status` is `active`
- the record is not expired
- `sensitivity` is not `restricted` unless the Agent Contract explicitly allows restricted memory

The admission output should include `admitted`, `included_memory_ids`, `summary`, `facts`, `rejected_memory_ids`, and `rejection_reasons`. LLMs may not decide Memory Admission in the first implementation stage.

The memory audit loop uses these events:
- `memory_candidate_generated` records trace-safe candidate ids, source run id, scope, and case id after a run completes.
- `memory_write_requested` records the write attempt with field names, sensitivity, and expiration metadata.
- `memory_write_decision` records policy and validator allow/deny results.
- `memory_admission` records which memory ids were admitted or rejected for a later run and why.
- `memory_export_decision` records lifecycle export by scope, Agent id, subject reference, provider, and exported count without exposing provider payloads.
- `memory_delete_decision` records lifecycle deletion by scope, case id or subject reference, Agent id, provider, and deleted count without exposing memory contents.

`memory_read` may remain provider-level read metadata; `memory_admission` is the event that records whether memory can enter context.

The planned Agent Contract shape keeps memory under `capabilities.memory` while exposing all scopes explicitly:

```yaml
capabilities:
  memory:
    enabled: true
    provider: local  # or mem0
    scopes:
      case:
        enabled: true
        retention_days: 30
        max_records: 5
        allow_restricted: false
      user:
        enabled: true  # Customer Persistent User Memory for Customer Run API
      shared:
        enabled: false
```

Stage 1 allowed only Case Memory to be enabled. Stage 3 enables Customer Persistent User Memory for Customer Run API through the `user` scope. Shared Memory may appear as disabled config entries, but enabling it still fails until its governance behavior is implemented.

Case Memory should be integrated first with the Customer Run API, using the customer conversation id as `case_id`. Assisted Chat may reuse the same design with its conversation id. CLI single-run execution does not enable Case Memory unless a future entry point supplies an explicit `case_id`.

Memory roadmap:

| Stage | Goal | Key deliverables |
| --- | --- | --- |
| 1 | Local Case Memory | memory contracts, local store, same-case recall, Memory Admission, deterministic post-run extractor, Customer Run API integration, trace events |
| 2 | Mem0 Adapter | Mem0-backed storage, retrieval, filtered Case Memory deletion, summarization enhancement, and similarity recall behind the same Proof Agent contracts |
| 3 | Customer Persistent User Memory | cross-conversation customer interest memory with consent, delete/export, retention, sensitivity policy, and restricted-memory handling |
| 4 | Shared Memory | organization or Agent-shared memory with clear separation from Knowledge Provider and no bypass around evidence requirements |

Stage 1 Local Case Memory acceptance:
- Customer Run API second and later turns can recall Case Memory by the same `conversation_id`.
- Recalled memory passes `memory_admission` before entering Structured Control Context.
- Case Memory can carry `policy_id`, `claim_id`, missing fields, Case Focus, and report view context.
- Case Memory does not store full report results, raw transcripts, raw tool payloads, or raw evidence content.
- Case Memory is not Accepted Evidence; business claims still require Accepted Evidence or authorized tool results.
- Expired, deleted, wrong-case, wrong-Agent, and disallowed restricted memory are not admitted.
- Trace includes `memory_candidate_generated`, `memory_write_requested`, `memory_write_decision`, `memory_admission`, and lifecycle `memory_delete_decision` when deletion is requested after an audited run.
- The deterministic demo remains runnable without network access, API keys, Mem0, or external memory services.

Stage 1 module boundaries:
- `proof_agent/contracts/memory.py` owns `MemoryRecord`, `MemoryCandidate`, `MemoryQuery`, `MemoryAdmission`, scope, status, and sensitivity contracts.
- `proof_agent/capabilities/memory/local_store.py` owns local append, read, and soft-delete mechanics without admission authority.
- `proof_agent/control/memory/extractor.py` owns deterministic MemoryCandidate generation from governed run facts.
- `proof_agent/control/memory/admission.py` owns deterministic Memory Admission.
- `proof_agent/bootstrap/manifest.py` and `proof_agent/contracts/manifest.py` own Agent Contract memory config parsing and validation.
- `proof_agent/delivery/customer_api.py` integrates run-before recall/admission and run-after candidate/write behavior for Customer Run API.
- `proof_agent/observability/audit/trace.py` emits memory candidate, write, and admission events.

Stage 3 Customer Persistent User Memory design:
- Stage 3 targets Customer Persistent User Memory for Customer Run API only. It does not introduce operator or staff user profiles.
- The stored subset is a Customer Memory Interest Profile: durable attention areas, preferred report views, interaction preferences, and cross-conversation follow-up context.
- It must not store report result values, rankings, policy status, claim status, balances, raw customer identity data, raw transcripts, raw tool payloads, raw evidence, or model-inferred marketing personas.
- The user memory isolation key is `agent_id + subject_ref`, where `subject_ref` is the provider-neutral Memory Subject Reference and equals the customer reference for the first Customer Service implementation.
- `case_id` remains the Case Memory key and must not be reused as a Persistent User Memory key.
- Customer Persistent User Memory requires Customer Memory Consent for both read and write. No consent means no read, no write, and no context injection.
- The first consent shape is runtime consent on Customer Conversation creation or Customer Run creation, not a platform-wide privacy preference store.
- Customer Memory Lifecycle Controls operate at the customer reference boundary in Stage 3: export all admitted customer interest memories for an `agent_id + subject_ref`, delete all customer interest memories for that boundary, and audit both operations.
- Single-memory editing, customer-visible memory management UI, and cross-Agent customer memory sharing are deferred.
- Read admission uses the same Control Plane Memory Admission concept but extends the deterministic rules for `scope: user`: matching `agent_id`, matching `subject_ref`, active status, not expired, consent present, and restricted memory disallowed unless the Agent Contract allows it.
- Admitted Customer Persistent User Memory may enter Structured Control Context for intent understanding, preference-aware follow-up, missing-field prompts, and next-step suggestions. It is not Accepted Evidence and cannot support customer-facing business claims.
- It must not automatically trigger sensitive data retrieval. If a remembered interest suggests a report or account-data direction, the run must still ask for required fields or use authorized tools under normal policy.
- Writes happen after a governed run completes, using deterministic extraction from customer-safe run facts and Case Focus-style signals. LLM summarization remains deferred until it can emit validated JSON and fail closed.
- Stage 3 should support the same provider boundary as Case Memory. The local adapter should support `scope: user` using `agent_id + subject_ref`; the Mem0 adapter should map `subject_ref` into provider metadata while leaving admission and lifecycle decisions in Proof Agent.

Stage 3 acceptance:
- Enabling `memory.scopes.user.enabled: true` succeeds only when Customer Persistent User Memory governance is implemented; `shared.enabled: true` remains rejected.
- A customer conversation or run without memory consent neither reads nor writes Customer Persistent User Memory.
- A consented customer run can write a Customer Memory Interest Profile from governed facts such as recurring focus topics, report view preferences, and interaction preferences.
- A later consented conversation for the same `agent_id + subject_ref` can admit that profile into Structured Control Context.
- A different `agent_id` or different `subject_ref` cannot admit the profile.
- Admitted user memory never appears as Accepted Evidence and never replaces retrieval, tool authorization, evidence evaluation, or final-output validation.
- Export returns only trace-safe memory summaries, facts, ids, scope, subject reference, sensitivity, expiration, and source ids; it does not expose provider raw payloads.
- Delete removes or marks inactive all Customer Persistent User Memory for the `agent_id + subject_ref` boundary and prevents later admission.
- Trace includes lifecycle events for user-memory candidate generation, write request/decision, admission, `memory_export_decision`, and `memory_delete_decision` without raw transcript, raw evidence, report result values, or provider payloads.

Rules:
- All writes pass `before_memory_write`.
- Retrieved memory passes Memory Admission before it enters Structured Control Context or a model request.
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

LLM-as-judge can become a later audited diagnostic capability. It must not replace deterministic gates or become a V1 release blocker.
`docs/evaluation-system.md` defines how the post-run Evaluation Analyzer layers deterministic gates, artifact sufficiency, node results, diagnostic judge fields, release thresholds, curation, and evaluation analysis artifacts on top of Trace, Governance Receipt, RunStore metadata, and audience-safe response projections.

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
model_connection_resolution
approval_requested
approval_granted
approval_denied
approval_timeout
tool_request
tool_result
memory_read
memory_candidate_generated
memory_write_requested
memory_write_decision
memory_admission
memory_export_decision
memory_delete_decision
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
- model connection resolution summary
- audit artifacts
- redaction summary

RunStore:
- saves `trace.jsonl`, `governance_receipt.md`, `run_meta.json`
- maintains `runs/latest`
- writes per-run history under `runs/history/{run_id}`
- powers Dashboard API read projections

## 20. Execution API, Agent Configuration API, And Dashboard API

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
- Published Agent resolution can use the local Agent Configuration Store. When
  an Active Agent Version exists, execution uses that immutable version package
  and records `agent_id` and `agent_version_id` in RunStore metadata.
- Execution still goes through Bootstrap / Composition, Runtime Plane, PolicyEngine, ToolGateway, Validators, Trace, Receipt, and RunStore.
- Chat run requests cannot carry inline approval decisions. Approval decisions are recorded against the original run through Run History approval endpoints. The local runtime persists approval resume metadata and LangGraph checkpoint files under the run storage root, so a restarted app process can resume the original thread. A per-run atomic local lock prevents concurrent local approval resumes from executing the same checkpoint twice. Multi-instance production deployments still require a shared transactional checkpointer and lock backend.
- Approval endpoints must enforce the durable `PendingApproval.expires_at` boundary. Late approve or deny attempts record `approval_timeout` and must not resume tool execution.
- Conversation runs admit a trace-safe summary of recent turns as Controlled Conversation Context; prior turns can resolve follow-ups but cannot replace current-turn evidence retrieval.

Agent Configuration API is Delivery behavior for Dashboard configuration
workflows. It is separate from the Run Execution API and does not let application
surfaces submit arbitrary manifests for production execution.

Configuration routes:
| Route | Purpose |
| --- | --- |
| `GET /api/config/agents` | list locally configured Agent identities; requires `agent.view` |
| `POST /api/config/agents/import` | import an existing Agent Package into Draft Agent state; requires `agent.edit` |
| `GET /api/config/agents/{agent_id}/drafts/{draft_id}` | read Draft Agent metadata; requires `agent.view` |
| `PATCH /api/config/agents/{agent_id}/drafts/{draft_id}` | update Draft Agent display fields; requires `agent.edit` |
| `GET /api/config/workflow-templates` | list backend-owned Workflow Template Descriptors; requires `agent.view` |
| `GET /api/config/workflow-templates/{template_id}` | read one Workflow Template Descriptor; requires `agent.view` |
| `GET /api/config/agents/{agent_id}/drafts/{draft_id}/contract` | read preserved Contract View files; requires `agent.view` |
| `PATCH /api/config/agents/{agent_id}/drafts/{draft_id}/contract` | update Contract View files after validation; requires `agent.edit` |
| `POST /api/config/agents/{agent_id}/drafts/{draft_id}/knowledge-bindings` | bind a published shared Knowledge Source into a Draft Agent; requires `agent.edit` |
| `DELETE /api/config/agents/{agent_id}/drafts/{draft_id}/knowledge-bindings/{binding_id}` | unbind a shared Knowledge Source from a Draft Agent; requires `agent.edit` |
| `PATCH /api/config/agents/{agent_id}/drafts/{draft_id}/workflow-stages` | update descriptor-backed Workflow Stage Prompt settings; requires `agent.edit` |
| `POST /api/config/agents/{agent_id}/drafts/{draft_id}/workflow-stages/{stage_id}/preview` | render a redacted Workflow Stage Context Preview; requires `agent.validate` |
| `GET /api/runs/{run_id}/validation-capture` | read a Sensitive Validation Capture Artifact for validation runs only; requires `agent.validate` |
| `POST /api/config/agents/{agent_id}/drafts/{draft_id}/validate` | run a Draft Agent as `run_purpose: validation`; requires `agent.validate` |
| `POST /api/config/agents/{agent_id}/drafts/{draft_id}/publish` | publish a validated Draft Agent as an immutable version; requires `agent.publish` |
| `GET /api/config/agents/{agent_id}/versions` | list Published Agent Versions; requires `agent.view` |
| `POST /api/config/agents/{agent_id}/versions/{version_id}/rollback` | switch the Active Agent Version pointer; requires `agent.publish` |
| `GET /api/config/model-connections` | list Shared Model Connections for Configuration > Models and selector dropdowns; requires `model_connection.view` |
| `POST /api/config/model-connections` | create a Shared Model Connection; requires `model_connection.edit` |
| `GET /api/config/model-connections/{connection_id}` | read one Shared Model Connection with reference summary; requires `model_connection.view` |
| `PATCH /api/config/model-connections/{connection_id}` | update a Shared Model Connection after impact confirmation; requires `model_connection.edit` |
| `POST /api/config/model-connections/{connection_id}/archive` | archive a connection and block new production references; requires `model_connection.archive` |
| `POST /api/config/model-connections/{connection_id}/restore` | restore an archived connection; requires `model_connection.archive` |
| `GET /api/config/model-connections/{connection_id}/references` | summarize Draft Agent, Published Agent Version, and Knowledge Source references; requires `model_connection.view` |
| `GET /api/config/model-connections/{connection_id}/deletion-eligibility` | check physical deletion blockers; requires `model_connection.view` |
| `DELETE /api/config/model-connections/{connection_id}` | physically delete only archived unreferenced connections; requires `model_connection.archive` |
| `POST /api/config/model-connections/{connection_id}/validate` | record credential/config validation without storing secrets; requires `model_connection.validate` |
| `POST /api/config/model-connections/{connection_id}/smoke-test` | record manual smoke-test status without raw responses; requires `model_connection.validate` |
| `GET /api/config/tool-source-descriptors` | list trusted built-in Tool Source descriptors; requires `tool_source.view` |
| `GET /api/config/tool-sources` | list reusable Tool Sources; requires `tool_source.view` |
| `POST /api/config/tool-sources` | create a reusable Tool Source; requires `tool_source.edit` |
| `GET /api/config/tool-sources/{source_id}` | read one reusable Tool Source; requires `tool_source.view` |
| `PATCH /api/config/tool-sources/{source_id}` | update one reusable Tool Source; requires `tool_source.edit` |
| `POST /api/config/tool-sources/{source_id}/archive` | archive a reusable Tool Source; requires `tool_source.archive` |
| `POST /api/config/tool-sources/{source_id}/restore` | restore an archived Tool Source; requires `tool_source.archive` |
| `GET /api/config/knowledge-sources` | list reusable Knowledge Sources; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources` | create a reusable Knowledge Source; requires `knowledge_source.edit` |
| `GET /api/config/knowledge-sources/{source_id}` | read one Knowledge Source; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources/{source_id}/archive` | archive a Knowledge Source; requires `knowledge_source.archive` |
| `POST /api/config/knowledge-sources/{source_id}/restore` | restore an archived Knowledge Source; requires `knowledge_source.edit` |
| `GET /api/config/knowledge-sources/{source_id}/deletion-eligibility` | check physical deletion blockers; requires `knowledge_source.view` |
| `DELETE /api/config/knowledge-sources/{source_id}` | physically delete only archived eligible Sources; requires `knowledge_source.archive` |
| `GET /api/config/knowledge-sources/{source_id}/documents` | list managed documents; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources/{source_id}/documents` | upload a single managed document; requires `knowledge_source.edit` |
| `PATCH /api/config/knowledge-sources/{source_id}/documents/{document_id}/routing-metadata` | update allowlisted document routing metadata; requires `knowledge_source.edit` |
| `POST /api/config/knowledge-sources/{source_id}/documents/batch` | upload a managed document batch; requires `knowledge_source.edit` |
| `GET /api/config/knowledge-sources/{source_id}/quarantined-uploads` | list quarantined uploads; requires `knowledge_source.view` |
| `GET /api/config/knowledge-sources/{source_id}/quarantined-uploads/{upload_id}` | read one quarantined upload record; requires `knowledge_source.view` |
| `GET /api/config/knowledge-sources/{source_id}/ingestion-jobs` | list ingestion jobs; requires `knowledge_source.view` |
| `GET /api/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}` | read one ingestion job; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}/retry` | retry a failed ingestion job; requires `knowledge_source.edit` |
| `GET /api/config/knowledge-sources/{source_id}/candidate-snapshot` | read the derived Local Index candidate snapshot; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/validate-foundation` | validate candidate freeze readiness; requires `knowledge_source.edit` |
| `POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/freeze` | freeze a validated development-stage snapshot manifest; requires `knowledge_source.edit` |
| `GET /api/config/knowledge-sources/{source_id}/snapshots` | list frozen Local Index snapshot manifests; requires `knowledge_source.view` |
| `GET /api/config/knowledge-sources/{source_id}/snapshots/{snapshot_id}` | read one frozen Local Index snapshot manifest; requires `knowledge_source.view` |
| `POST /api/config/knowledge-sources/{source_id}/publication/validate` | validate Source publication readiness; requires `knowledge_source.publish` |
| `POST /api/config/knowledge-sources/{source_id}/publication/publish` | publish a validated Source version; requires `knowledge_source.publish` |
| `GET /api/config/knowledge-sources/{source_id}/publication-validations` | list Source publication validations; requires `knowledge_source.view` |
| `GET /api/config/knowledge-sources/{source_id}/publications` | list Source publications; requires `knowledge_source.view` |

Rules:
- Draft Agents are editable configuration state and must not be executed as
  production agents directly.
- Validation runs are governed Harness runs persisted through RunStore with
  `run_purpose: validation`, `agent_id`, and `draft_id`.
- Published Agent Versions are immutable snapshots of the Contract Bundle and
  require a recorded validation run id.
- Agent Configuration, Knowledge Source, Model Connection, and Tool Source command requests do not carry
  `actor` fields. The API resolves Operator Identity Context server-side,
  requires the matching `agent.*`, `knowledge_source.*`, or
  `model_connection.*` or `tool_source.*` permission, and passes the resolved
  operator id to the configuration store or trace-safe command record instead
  of trusting frontend-supplied identity. Tool Source create, update, archive,
  and restore operations and Model Connection create, update, archive, restore,
  and physical delete operations write Configuration Operation Audit records
  with the resolved operator id.
- The Dashboard may show configuration and monitoring in one shell, but the
  Agent Configuration API, Run Execution API, and Dashboard read API remain
  separate boundaries.

Dashboard API is observability, not execution.

Dashboard routes:
| Route | Purpose |
| --- | --- |
| `/api/health` | service health |
| `/api/runs` | run list, filters, pagination, production/validation purpose filtering |
| `/api/runs/{run_id}` | run detail, including backend-owned `workflow_projection` when Workflow stage facts exist |
| `/api/runs/{run_id}/trace` | trace events |
| `/api/runs/{run_id}/receipt` | receipt markdown |
| `GET /api/approvals` | global pending approval queue projection sorted by expiry |
| `POST /api/runs/{run_id}/approvals/{approval_id}/approve` | append approval-granted decision to the original run trace; requires Operator Identity Context with `approval.resolve` |
| `POST /api/runs/{run_id}/approvals/{approval_id}/deny` | append approval-denied decision to the original run trace; requires Operator Identity Context with `approval.resolve` |
| `/api/stats` | outcome distribution and pending approvals |

Rules:
- API serializers define public response shapes.
- Dashboard API cannot start runs or bypass CLI/workflow.
- Static SPA may be mounted when built assets exist.
- Dashboard Run Detail uses the backend-owned Workflow projection for governed
  stage semantics. The JSONL Trace remains the source fact log and debug
  drilldown; frontend code must not reconstruct governed Workflow semantics by
  parsing trace events.
- Approval Console actions resolve `PendingApproval` state. Approved tool execution resume must use the runtime checkpoint rather than a new chat request; if the checkpoint is missing, the system may record the decision but must not claim tool execution resumed. Approval command requests resolve Operator Identity Context server-side, require `approval.resolve`, and terminal approval trace events record the resolved operator id. The global Approval Queue is a read projection over pending approvals, not a Run list filter or stats payload; it marks expired approvals without mutating trace. The Dashboard `/approvals` page consumes that projection for triage and links operators to Run Detail Approval Action for the actual approve or deny command.

## 21. CLI And Docker

CLI commands:
| Command | Purpose |
| --- | --- |
| `proof-agent demo` | deterministic React Enterprise QA baseline scenarios |
| `proof-agent react-demo` | compatibility command for deterministic React Enterprise QA scenarios |
| `proof-agent run` | run one Enterprise QA question |
| `proof-agent doctor` | local, Docker, sample, provider readiness |
| `proof-agent inspect` | summarize trace or receipt |
| `proof-agent compare` | Plain RAG vs Harness RAG |
| `proof-agent evaluate analyze` | planned post-run Evaluation Analyzer over an Evaluation Suite and Evaluation Subject Manifest; does not create Agent runs |
| `proof-agent dev` | start the local backend API and Knowledge Worker with `.env` loaded |
| `proof-agent server` | start only the Dashboard API |

Docker:
- `docker compose up` runs deterministic demo by default.
- Docker path must not require API keys.
- Remote provider env vars can be passed at runtime.

Deterministic React baseline demo:
```bash
uv run --extra dev proof-agent demo
```

When the package is already installed with required extras, `proof-agent demo` is equivalent.

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
tree = ["llama-index-core"]
```

Dependency rules:
- deterministic demo cannot require optional extras.
- provider SDKs belong in provider-specific extras.
- local index dependencies belong in `[tree]`.
- dashboard runtime belongs in `[dashboard]`.

## 23. Error Codes

| Code | Subsystem | Purpose |
| --- | --- | --- |
| `PA_CONFIG_001` | Config | missing field, invalid shape, missing path |
| `PA_CONFIG_002` | Config | unsupported runtime/template/memory |
| `PA_SCHEMA_001/002` | Schema | contract/schema validation |
| `PA_KNOWLEDGE_001/002` | Knowledge | provider/params/retrieval errors |
| `PA_INGESTION_001/002/003/004/005` | Knowledge ingestion | configuration, upload parsing, artifact build, lock/claim ownership, and stale or conflicting snapshot freeze errors |
| `PA_RETRIEVAL_001` | Retrieval | recognized retrieval strategy not executable in this build |
| `PA_MODEL_001` | Model | unsupported provider, placeholder, missing SDK |
| `PA_MODEL_002` | Model | provider API error |
| `PA_MODEL_003` | Model | auth failure or missing API key env |
| `PA_MODEL_004` | Model | provider timeout |
| `PA_MODEL_CONNECTION_001` | Model connection | missing shared connection or invalid model source shape |
| `PA_MODEL_CONNECTION_002` | Model connection | archived shared connection blocks production publication |
| `PA_MODEL_CONNECTION_CREDENTIAL_MISSING` | Model connection | validation or smoke test cannot find the referenced credential environment variable |
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
| 4 | production adapters: LangChain/LangGraph, real MCP, local index, governed remote retrieval, Azure/Anthropic, streaming |
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
