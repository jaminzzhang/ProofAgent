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

The current runnable reference implementation is the [Enterprise QA Template](examples/enterprise-qa.md), corresponding to the `examples/enterprise_qa/` directory.

## 2. Quick Start

Run the local deterministic demo from the repository root:
```bash
uv run --extra dev proof-agent demo
```

Run the Enterprise QA Template:
```bash
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml
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
uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000
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
| Entry | CLI, Docker demo, Dashboard API |
| Workflow template | `enterprise_qa` |
| Runtime config | `workflow.runtime: langgraph`; adapter boundary exists, but MVP main flow delegates to plain Python orchestrator |
| Knowledge | `knowledge.provider: local_markdown`, local Markdown retrieval |
| Retrieval | `retrieval.strategy: single_step`, top-k and evidence thresholds |
| Model | `deterministic` and `openai_compatible` implemented; `azure_openai`, `anthropic` are clean-failure placeholders |
| Policy | `before_retrieval`, `before_retrieval_step`, `before_answer`, `before_tool_call`, `before_memory_write`, `before_model_call` |
| Tools / MCP | ToolGateway, mock `customer_lookup`, approval state; real MCP transport is the extension direction |
| Memory | `memory.provider: session`, with sensitive field denylist |
| Validators | schema, evidence, safety, citations, tool result |
| Audit | JSONL trace, Governance Receipt, RunStore, Dashboard read API |

The v1 deterministic path must always operate without requiring API keys, network models, or external services.

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
- `workflow.template` must be `enterprise_qa`.
- `knowledge.provider` must be one of `local_markdown`, `local_vector`, or `remote_search`.
- `retrieval.strategy` must be `single_step` for executable first-stage runs.
- `retrieval.strategy: agentic` is a reserved contract and fails with `PA_RETRIEVAL_001`.
- `memory.provider` must be `session`.
- `model.provider` supports `deterministic`, `openai_compatible`, `azure_openai`, `anthropic` (Azure and Anthropic are placeholders).
- `policy.file`, `tools.file`, and provider-specific paths under `knowledge.params` must exist.
- The parent directories of `audit.trace_path` and `audit.receipt_path` must be writable.

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

Run example:
```bash
OPENAI_API_KEY=... uv run --extra openai proof-agent run examples/enterprise_qa/agent.yaml --question "What is the reimbursement rule for travel meals?"
```

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

## 7. Configuring the Runtime Plane

The Runtime Plane handles execution mechanics, not governance decisions.

Current config:
```yaml
workflow:
  runtime: langgraph
  template: enterprise_qa
```

In the current MVP, `runtime/langgraph_runner.py` is the LangGraph adapter boundary, but the main flow is still executed by the Enterprise QA orchestrator. Future real LangGraph runtimes should assume responsibility for StateGraph, checkpoint, interrupt/resume, and streaming hooks, but MUST NOT alter the Control Plane's governance semantics.

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
uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000
```

When deploying, deliver:
```text
Agent package
Docker image or Python runtime
environment variable configuration
runs/ storage volume
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
- Governance Receipt can explain the final outcome.
- Dashboard API only reads run history, not creating a new execution path.
