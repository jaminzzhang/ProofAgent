# Proof Agent Developer Guide

> Audience: AI Agent Owners, Agent Platform Owners, Enterprise AI Engineering Leads.
>
> Goal: Use Proof Agent to quickly develop, validate, and deploy a governed Agent, rather than implementing policy gates, tool approvals, evidence checks, auditing, and observability from scratch.

## 1. Usage Overview

The development entry point for Proof Agent is a governed Agent package, not bare Agent code.

An Agent package typically includes:
```text
agent.yaml          # Agent Contract: declares workflow, runtime, model, knowledge, tools, memory, audit
policy.yaml         # Control Plane policy: declares when to allow, deny, approve, or escalate
tools.yaml          # Tool / MCP declaration: tool allowlist, risk levels, parameter boundaries, approval requirements
knowledge/          # Business knowledge sources; v1 defaults to supporting local Markdown knowledge bases
questions.yaml      # Optional: Evaluation question set
expected/           # Optional: Expected trace / receipt examples
```

The current runnable reference implementations are the [Enterprise QA Template](examples/enterprise-qa.md), corresponding to `examples/enterprise_qa/`, and the [Controlled ReAct Enterprise QA Template](examples/react-enterprise-qa.md), corresponding to `examples/react_enterprise_qa/`.

## 2. Quick Start

Run the local deterministic demo from the repository root:
```bash
uv run --extra dev proof-agent demo
```

Run the Enterprise QA Template:
```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml
```

Run the deterministic Controlled ReAct Enterprise QA demo:
```bash
uv run --extra dev --extra dashboard proof-agent react-demo
```

If Proof Agent is already installed with the required extras, use:
```bash
proof-agent react-demo
```

Compare Plain RAG vs Controlled Harness RAG:
```bash
uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
```

View the latest Governance Receipt:
```bash
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

View the latest trace:
```bash
uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
```

Start the Dashboard API:
```bash
uv run --extra dashboard proof-agent server --host 127.0.0.1 --port 8000
```

The Dashboard API reads the existing run history. It is not a secondary execution path for the Agent.

## 3. Architecture Mental Model

When using Proof Agent, think in terms of the following layers:

```text
Delivery / Entry
  CLI | Docker | Template | future Execution API

Bootstrap / Composition
  agent.yaml loader | config validation | registry | dependency wiring

Control Plane
  Workflow | Orchestrator | Policy Gates | Approval State Machine
  Evidence Evaluation | Validators | Memory Policy | Outcome

Runtime Plane
  Plain Python Runner | LangGraph Adapter | LangChain Adapter
  state execution | checkpoint | interrupt/resume | streaming

Capability Layer
  Model | Knowledge/Retrieval | Memory | Tool/MCP | Skill Packs

Contracts & Ports
  Stable DTOs and provider protocols used across layers

Audit & Observability
  TraceWriter -> JSONL Trace -> RunStore -> Governance Receipt -> Dashboard API
```

Core boundaries:
- Control owns decisions.
- Runtime owns execution mechanics.
- Capability owns concrete abilities.
- Contracts define the language.
- Audit records facts.

## 4. Current v1 Capability Boundaries

| Area | v1 status |
| --- | --- |
| Entry | CLI, Docker demo, Run Execution API, Dashboard API |
| Workflow template | `enterprise_qa`, `react_enterprise_qa` |
| Runtime config | `workflow.runtime: langgraph`; Enterprise QA and Controlled ReAct Enterprise QA run through LangGraph `StateGraph` templates using composed Harness dependencies |
| Knowledge | `knowledge.provider: local_markdown`, local Markdown retrieval |
| Retrieval | `retrieval.strategy: single_step`, top-k and evidence thresholds |
| Model | `deterministic`, `openai_compatible`, `openai`, and `deepseek` implemented; `azure_openai`, `anthropic` are clean-failure placeholders |
| Policy | `before_retrieval`, `before_retrieval_plan`, `before_retrieval_step`, `before_answer`, `before_tool_call`, `before_memory_write`, `before_model_call` |
| Tools / MCP | ToolGateway, mock `customer_lookup`, approval state; real MCP transport is the extension direction |
| Memory | `memory.provider: session`, with sensitive field denylist |
| Validators | schema, evidence, safety, citations, tool result |
| Audit | JSONL trace, Governance Receipt, RunStore, ConversationStore, Dashboard read API |

The v1 deterministic path must always operate without requiring API keys, network models, or external services.

The ReAct deterministic demo adds these expected outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

## 5. Configuring the Agent Contract

`agent.yaml` is the primary public interface for Proof Agent. Minimal reference:

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

Current v1 config constraints:
- `workflow.runtime` must be `langgraph`.
- `workflow.template` must be `enterprise_qa` or `react_enterprise_qa`.
- `knowledge.provider` must be one of `local_markdown`, `local_vector`, `remote_search`, or `pageindex`.
- `retrieval.strategy` supports `single_step` and `agentic`.
- `memory.provider` must be `session`.
- `model.provider` supports `deterministic`, `openai_compatible`, `openai`, `deepseek`, `azure_openai`, `anthropic` (Azure and Anthropic are placeholders).
- `policy.file`, `tools.file`, and provider-specific paths under `knowledge.params` must exist.
- The parent directories of `audit.trace_path` and `audit.receipt_path` must be writable.

Controlled ReAct adds these sections to `agent.yaml`:

```yaml
workflow:
  runtime: langgraph
  template: react_enterprise_qa
  checkpointer:
    provider: sqlite
    uri: memory

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

`react_enterprise_qa` requires `react`. `review.mode: auto` requires `review.subagent`. `response` controls optional governance details returned by Run Execution and Conversation APIs; the caller can request `include_governance_details`, but the Agent Contract caps the response through `response.include_reasoning_summary` and `response.include_review_results`.

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

The planner proposes actions from this set. The Harness still owns execution, policy, approval, validation, trace, and receipt behavior. Store only audit-safe Reasoning Summary fields; raw chain-of-thought must not be recorded, stored, or exposed.

Remote model configuration must use environment variable names; do not write raw secrets into the YAML:
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

OpenAI-compatible named providers reuse the same adapter with provider-specific defaults:

```yaml
model:
  provider: deepseek
  name: deepseek-v4-flash
  params:
    api_key_env: DEEPSEEK_API_KEY
    temperature: 0
    max_output_tokens: 800
```

`deepseek` defaults to `DEEPSEEK_API_KEY` and `https://api.deepseek.com`; set `base_url` or `base_url_env` only when routing through a compatible proxy.

### Configuring LLM-Backed Planning And Review

Use the existing provider names to configure each model role. Provider names describe the external model channel; role semantics come from the Agent Contract section.

```yaml
model:
  provider: openai_compatible
  name: qwen-plus
  params:
    api_key_env: OPENAI_COMPATIBLE_API_KEY
    base_url_env: OPENAI_COMPATIBLE_BASE_URL

react:
  planner:
    provider: openai_compatible
    name: qwen-plus
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0

review:
  mode: auto
  subagent:
    provider: openai_compatible
    name: qwen-plus
    fail_closed: true
    params:
      api_key_env: OPENAI_COMPATIBLE_API_KEY
      base_url_env: OPENAI_COMPATIBLE_BASE_URL
      temperature: 0
```

Planner and reviewer prompts are Harness Control Prompts maintained by Proof Agent. Agent Contracts configure provider channel, model name, and provider parameters, but do not replace the control prompts in V1.

See `examples/react_enterprise_qa/agent.llm.yaml` for a runnable Agent Contract that configures final answer, planner, and reviewer roles with an OpenAI-compatible model provider. Planner and reviewer outputs are parsed as Harness JSON contracts before they affect routing, policy, tool, or answer behavior; provider-native tool calls are not executed in V1.

Run example:
```bash
OPENAI_COMPATIBLE_API_KEY=... \
OPENAI_COMPATIBLE_BASE_URL=... \
uv run --extra openai proof-agent run examples/react_enterprise_qa/agent.llm.yaml --question "What is the reimbursement rule for travel meals?"
```

PageIndex self-hosted retrieval can be used as a remote agentic evidence source while Proof Agent keeps the Control Envelope, policy decisions, evidence evaluation, and final answer validation:

```yaml
knowledge:
  provider: pageindex
  params:
    endpoint_env: PAGEINDEX_BASE_URL
    document_id: doc_enterprise_policy
    thinking: true
    timeout_seconds: 10

retrieval:
  strategy: agentic
  top_k: 5
  min_score: 0.2
  max_steps: 3
```

For a default local PageIndex deployment, set `PAGEINDEX_BASE_URL=http://127.0.0.1:8000`. If the deployment requires auth, add `api_key_env: PAGEINDEX_API_KEY` under `knowledge.params` and set that environment variable.

## 6. Configuring the Control Plane

The Control Plane decides whether the Agent is allowed to proceed. It does not trust model outputs, nor does it allow Runtime or Tools to bypass governance directly.

Common policy files:
```yaml
rules:
  - rule_id: answering.require_retrieval
    enforcement_point: before_answer
    condition:
      require_retrieval: true
      min_evidence_count: 1
      require_citations: true
    decision:
      on_pass: allow
      on_fail: deny
    reason_template: "Answers require accepted evidence and citations."

  - rule_id: tools.customer_lookup.approval
    enforcement_point: before_tool_call
    condition:
      tool_name: customer_lookup
      risk_level: medium
    decision:
      on_match: require_approval
    reason_template: "Customer policy lookup requires explicit approval."
```

Control Plane development steps:
1. Identify when the Agent MUST refuse to answer.
2. Identify how much evidence is required before answering.
3. Identify which tools require approval.
4. Identify which fields cannot be written to memory.
5. Identify provider, token, cost, or risk policies before model calls.
6. Verify with trace and receipt that every policy gate was recorded.

For Controlled ReAct, Auto Review Scope covers:

```text
before_retrieval_plan
before_retrieval_step
before_tool_call
before_model_call
```

`before_answer` remains deterministic evidence and citation governance.

The Harness Review Subagent is advisory. It may suggest `allow`, `deny`, `require_approval`, or `escalate`, but PolicyEngine and the Harness make the final policy decision. Review failures fail closed: tool call review failures require approval, model call review failures deny the call, and retrieval plan or step failures deny unless an explicit fallback exists.

## 7. Configuring the Runtime Plane

The Runtime Plane handles execution mechanics, not governance decisions.

Current config:
```yaml
workflow:
  runtime: langgraph
  template: enterprise_qa
```

In the current MVP, `bootstrap/composition.py` resolves a `HarnessInvocation`, and `runtime/langgraph_runner.py` executes the Enterprise QA LangGraph `StateGraph` with those composed dependencies. Future runtime work should extend checkpoint, interrupt/resume, and streaming hooks, but MUST NOT alter the Control Plane's governance semantics.

Development principles:
- Runtime can advance state, but cannot skip PolicyEngine.
- Runtime can implement human interrupt, but approval facts are still recorded by ApprovalState and trace.
- Runtime can stream tokens, but trace must not record raw secrets or unredacted provider payloads.
- LangChain/LangGraph SDK types must not leak into contracts, policy, trace, receipt, or dashboard contracts.

## 8. Configuring the Capability Layer

The Capability Layer provides the callable abilities for the Agent.

### Model
Use the deterministic provider for local regression:
```yaml
model:
  provider: deterministic
  name: demo
```

Use the OpenAI-compatible provider for remote model validation:
```yaml
model:
  provider: openai_compatible
  name: gpt-4o-mini
  params:
    api_key_env: OPENAI_API_KEY
```

When extending a new model provider:
- Implement the `ModelProvider` protocol.
- Return provider-neutral `ModelResponse`.
- Register in the provider registry.
- Provider SDK errors must be mapped to Proof Agent error codes.
- Traces can only record safe summaries like provider, model, token usage, content length, finish reason, etc.

### Knowledge
Current v1 uses a local Markdown knowledge base:
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

When extending vector or enterprise search:
- Provider must return candidate `EvidenceChunk`.
- Provider-specific config belongs under `knowledge.params`.
- `top_k` and `min_score` belong under `retrieval`.
- Retrieval cannot determine the final answer.
- Whether evidence is sufficient is determined by evaluators, PolicyEngine, and validators.
- Vector database SDK types must not enter contracts.

### Memory
Current v1 uses session memory:
```yaml
memory:
  provider: session
```

Before extending persistent memory, you must define:
- retention policy
- deletion behavior
- redaction behavior
- tenant boundary
- `before_memory_write` policy

### Tools / MCP
Tools are registered via `tools.yaml`:
```yaml
tools:
  - name: customer_lookup
    description: "Mock customer policy status lookup."
    transport: stdio
    command: python
    args:
      - -m
      - proof_agent.capabilities.tools.mcp_mock
    risk_level: medium
    requires_approval: true
    allowed_parameters:
      - customer_id
      - policy_id
    denied_parameters:
      - access_token
      - customer_phone
      - provider_api_key
```

Tool development principles:
- All tool calls must pass through ToolGateway.
- High-risk tools must enter the approval state.
- Parameters must have allowlists / denylists.
- Tool results must pass through validators.
- Real MCP stdio/http transports should be adapters behind ToolGateway, not new execution paths.

### Skills
A Skill is a capability pack, not a shortcut around Control. A Skill can contain:
- prompt pattern
- tool schema
- retrieval recipe
- policy rule
- validator
- workflow fragment

When a Skill is imported, it should be registered or compiled into the existing Control, Runtime, and Capability models. It cannot call models, tools, or memory directly to bypass PolicyEngine, Approval, or Trace.

## 9. Developing a New Agent

Recommended process:
1. Copy an Agent package from `examples/enterprise_qa/`.
2. Modify `name`, `purpose`, `knowledge.params`, `retrieval`, `model`, `audit` in `agent.yaml`.
3. Replace the business knowledge Markdown under `knowledge/`.
4. Modify `policy.yaml` to define answering, tool, memory, and model call policies.
5. Modify `tools.yaml`, registering only the tools this Agent needs.
6. Keep the deterministic provider and run local regressions first.
7. Switch to `openai_compatible` to verify that candidate outputs are still managed by validators using real models.
8. Run compare to confirm visible differences between Plain RAG and Harness RAG on unsupported questions.
9. Inspect `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`.
10. Only then enter the Docker or Dashboard API paths.

Suggested validation commands:
```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
uv run --extra dev --extra dashboard proof-agent react-demo
uv run --extra dev proof-agent run examples/insurance_service_qa/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml --question "Look up customer policy status before answering."
uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
```

## 10. Deployment

Local or CI smoke path:
```bash
uv run --extra dev proof-agent demo
```

Docker path:
```bash
docker compose up
```

Dashboard API path:
```bash
uv run --extra dashboard proof-agent server --host 127.0.0.1 --port 8000
```

Run Execution API path:
```bash
curl -X POST http://127.0.0.1:8000/api/chat/runs \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"insurance_service_qa","question":"What documents are required for inpatient claim reimbursement?"}'
```

The Run Execution API starts a configured Published Agent by `agent_id`; it does
not accept arbitrary manifest paths from application clients. The Dashboard API
continues to read run history, trace, receipt, evidence, model usage, and
approval state from persisted run artifacts.

Conversation API path:
```bash
curl -X POST http://127.0.0.1:8000/api/chat/conversations \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"enterprise_qa"}'

curl -X POST http://127.0.0.1:8000/api/chat/conversations/{conversation_id}/runs \
  -H "Content-Type: application/json" \
  -d '{"question":"What about travel meals again?"}'
```

Conversation runs automatically admit Controlled Conversation Context from
recent turns. The admitted context is a bounded, trace-safe summary used for
follow-up resolution; each turn still performs its own retrieval, evidence
evaluation, validation, trace, and receipt.

For ReAct conversations, `WAITING_FOR_USER_CLARIFICATION` is a controlled continuation state. The current run records `clarification_requested`, returns the missing-details prompt, and waits for the user to submit a follow-up turn. The follow-up still starts through the Conversation API and the same Control Envelope; no hidden continuation state may bypass policy or evidence checks.

Governance details can be requested from Run Execution and Conversation APIs with `include_governance_details`. The API returns details only when the request asks for them and the published Agent Contract allows them through `response.include_reasoning_summary` or `response.include_review_results`.

When deploying, deliver:
```text
Agent package
Docker image or Python runtime
environment variable configuration
runs/ storage volume
Published Agent configuration for execution surfaces
Dashboard API if observability is required
```

Do not commit:
- API keys
- bearer tokens
- passwords
- connection strings
- provider secrets
- generated files under `runs/latest/`

## 11. Operations Management

Every run should produce:
```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

When `RunStore` is enabled, each run is saved to:
```text
runs/history/{run_id}/trace.jsonl
runs/history/{run_id}/governance_receipt.md
runs/history/{run_id}/run_meta.json
```

AI Agent owners should regularly review:
- final outcome distribution
- if refusals behave as expected
- if unsupported questions are refused
- if tool approvals trigger correctly
- if memory writes are intercepted by policy
- if model usage is normal
- if traces are complete
- if receipts can explain the final outcome

## 12. When to Extend the Framework

When adding new capabilities, first determine which layer it belongs to:

| Need | Extension point |
| --- | --- |
| New model provider | Capability Layer: ModelProvider adapter |
| New knowledge or vector base | Capability Layer: KnowledgeProvider adapter |
| New tool or MCP server | Capability Layer: ToolGateway adapter |
| New approval mechanism | Control Plane: ApprovalState / approval provider |
| New Agent state machine | Runtime Plane: LangGraph/LangChain runtime adapter |
| New audit view | Audit & Observability: RunStore / Dashboard read projection |
| New Agent template | Control Plane + Runtime + Capability package |

Default rule: define the contract or port first, then implement the adapter. Do not let third-party SDK types enter public contracts, policies, traces, receipts, or dashboard contracts.

## 13. Owner Acceptance Checklist

Before launching, verify at least:
- Agent runs successfully with the deterministic provider.
- `agent.yaml` contains no raw secrets.
- Unsupported questions are refused or escalated.
- Supported questions have evidence and citations.
- High-risk tools wait for approval.
- Memory does not persist sensitive fields.
- Remote model output passes through validators.
- Traces record key policy, retrieval, model, tool, memory, and final output events.
- ReAct traces record `reasoning_summary`, `action_proposal`, review events, and `clarification_requested` when applicable.
- Governance Receipt can explain the final outcome.
- Dashboard API only reads run history, not creating a new execution path.
