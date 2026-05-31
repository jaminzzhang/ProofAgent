# Agent Contract

`agent.yaml` is the first public interface of Proof Agent.

It describes the Agent as an enterprise delivery artifact: purpose, workflow, knowledge, model provider, policy, tools, memory, and audit output. Users should understand what the Agent is allowed to do before they read implementation code.

## v1 Shape

```yaml
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

knowledge_sources:
  - source_id: enterprise_qa_knowledge
    name: Enterprise QA Knowledge
    provider: local_markdown
    params:
      path: ./knowledge

knowledge_bindings:
  - binding_id: enterprise_qa_knowledge_binding
    source_id: enterprise_qa_knowledge

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

model:
  provider: deterministic
  name: demo
  params: {}

policy:
  file: ./policy.yaml

tools:
  file: ./tools.yaml

memory:
  provider: session

audit:
  trace_path: ./runs/latest/trace.jsonl
  receipt_path: ./runs/latest/governance_receipt.md
```

The base schema is intentionally small. It is enough to run the Enterprise QA template while leaving room for ReAct planning, review, remote model, vector store, MCP, and dashboard integrations through explicit sections and adapter-specific params.

Long-term memory keeps the same top-level `memory` section but exposes Proof Agent scopes explicitly. Case Memory can be enabled for Customer Run API, and Stage 3 enables Customer Persistent User Memory for Customer Service conversations with customer memory consent, `agent_id + subject_ref` isolation, and lifecycle export/delete controls. Shared Memory may be declared only as disabled until its governance rules are implemented.

```yaml
memory:
  provider: local  # or mem0
  scopes:
    case:
      enabled: true
      retention_days: 30
      max_records: 5
      allow_restricted: false
    user:
      enabled: false
    shared:
      enabled: false
```

## ReAct Shape

The `react_enterprise_qa` template adds `react`, `review`, and `response` sections. These sections are part of the Agent Contract, not hidden runtime knobs.

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

`workflow.template: react_enterprise_qa` requires a `react` section. `review.mode: auto` requires `review.subagent`. `response` controls what governance details may be returned to API callers; it does not change what the trace records.

## Responsibilities

`agent.yaml` should answer:

- what this Agent is for
- which workflow template it uses
- which shared Knowledge Sources are available
- which Knowledge Sources this Agent binds
- how retrieval is orchestrated and thresholded
- which model provider mode it uses
- which policy controls it
- which tools are available
- what memory scope is allowed
- where audit artifacts are written
- for ReAct templates, which planner, review, and response disclosure settings apply

The supported v1 model providers are:

- `deterministic`: local demo provider, no SDK or API key required.
- `openai_compatible`: Chat Completions-compatible remote provider.
- `openai`: OpenAI-compatible named provider with `OPENAI_API_KEY` default.
- `deepseek`: OpenAI-compatible named provider with `DEEPSEEK_API_KEY` and `https://api.deepseek.com` defaults.
- `azure_openai`: configuration contract and validation placeholder only.
- `anthropic`: configuration contract and validation placeholder only.

Provider settings live under `model.params`. They may name environment variables such as `api_key_env`, `base_url_env`, `organization_env`, or `project_env`, but must not contain raw secret values.

Knowledge provider settings live on `knowledge_sources[].params` and in the Dashboard Knowledge Source store. Supported provider names are `local_markdown`, `local_vector`, `remote_search`, and `pageindex`. Agents bind one or more Sources through `knowledge_bindings[]`; they do not own provider credentials or ingestion settings. Retrieval settings such as `strategy`, `top_k`, `min_score`, and `max_steps` live under the required top-level `retrieval` section. Executable runs blend bound Sources, normalize candidate evidence, and then apply admission and citation validation before any answer is generated. The `pageindex` provider uses a PageIndex deployment for retrieval and still returns candidate evidence only.

## ReAct Section

`react` configures planner behavior for the governed ReAct workflow.

| Field | Purpose |
| --- | --- |
| `max_steps` | Maximum planner/action loop count before the Harness stops. |
| `max_tool_calls` | Maximum governed tool proposals allowed in the run. |
| `record_reasoning_summary` | Whether to emit audit-safe `reasoning_summary` trace events. This must never mean storing raw chain-of-thought. |
| `planner.provider` / `planner.name` | Planner adapter selection. The deterministic provider supports local demos and tests. |
| `planner.params` | Provider-specific planner settings. Secret-looking fields are rejected like model params. |

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

Planner implementations propose actions from this closed set. They do not directly retrieve, call tools, call models, write memory, or finalize output outside the Harness.

## Review Section

`review` configures the Harness Review Subagent. The subagent is advisory. It may suggest:

```text
allow
deny
require_approval
escalate
```

PolicyEngine and the Harness make the final policy decision. Deterministic rules can override a less strict review suggestion, invalid review output fails closed, and every handled review path is recorded in trace.

Auto Review Scope covers:

```text
before_retrieval_plan
before_retrieval_step
before_tool_call
before_model_call
```

`before_answer` remains deterministic evidence and citation governance. The review subagent does not decide whether unsupported evidence can become an answer.

Review failure policy is fail closed:

- tool call review failure -> `require_approval`
- model call review failure -> `deny`
- retrieval plan or retrieval step review failure -> `deny` unless the context declares an explicit allowed fallback

## Response Section

`response` caps optional governance details returned by Run Execution and Conversation API responses.

| Field | Behavior |
| --- | --- |
| `include_reasoning_summary` | Allows API response details to include the audit-safe ReAct Reasoning Summary when the caller also requests governance details. |
| `include_review_results` | Allows API response details to include review decision summaries when the caller also requests governance details. |

API callers request details with `include_governance_details`, but the response is capped by this Agent Contract. If a caller asks for governance details and both response flags are false, the response omits `governance_details`.

Trace and receipt behavior is separate: trace records governed events, receipts summarize trace events, and API response disclosure follows the `response` section.

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

Adapter fields are allowed only when they remain provider-neutral at the contract boundary. Raw SDK clients, auth objects, LangChain objects, LangGraph objects, MCP session objects, or vector store handles must not appear in `agent.yaml` or contract models.

## Failure Behavior

Invalid contracts must fail before execution starts. Errors should name the missing or invalid field and the file that caused it.

Examples:

- missing `policy.file` -> fail fast with config guidance
- missing provider-specific knowledge params -> fail fast before model call
- retrieval strategy recognized by the contract but unavailable in the current runtime -> fail fast with `PA_RETRIEVAL_001`
- unsupported model provider -> fail fast; v1 defaults to deterministic demo mode
- missing remote model SDK or API key -> emit `model_error` after trace initialization when possible
- unsupported runtime -> fail fast; the public workflow contract stays stable even when LangGraph/LangChain adapters evolve
- `react_enterprise_qa` without `react` config -> fail fast with config guidance
- `review.mode: auto` without `review.subagent` -> fail fast with config guidance
- unwritable audit path -> fail before answering

The contract is part of trust. If configuration is ambiguous, the Agent should not run.

## Customer Service Agent Contract

`insurance_customer_service` uses the same `agent.yaml` contract as other Published Agents. Customer-specific behavior lives beside the contract in package fixtures:

- `customers.yaml` for V1 mock authenticated sessions
- `tools.yaml` plus local handlers for policy-authorized read-only status tools
- `customer_adapter.py` for insurance-specific Customer Run Adapter behavior
- `journeys.yaml` for customer journey acceptance
- `agent.pageindex.yaml` for the PageIndex knowledge variant

Customer API callers still reference a Published Agent id. They must not submit arbitrary manifest paths.
