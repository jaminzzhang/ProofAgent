# Technical Plan: Proof Agent v1

Status: APPROVED  
Source: `/plan-devex-review` decisions  
Product shape: CLI-first Python Controlled Agent Harness Framework

## 1. Technical Goal

Proof Agent v1 delivers a local-first **Controlled Agent Harness Framework** and proves it through a runnable, governed, and auditable enterprise knowledge Q&A reference template.

The long-term vision is an enterprise Agent Control Platform. The v1 implementation remains intentionally narrow: CLI-first, local-first, deterministic-demo capable, and template-verified.

The technical plan optimizes for two developer paths:

- **2-minute deterministic demo:** `proof-agent demo` runs without an LLM key and proves the value of Plain RAG vs Harness RAG, JSONL trace, and Governance Receipt.
- **30-minute enterprise evaluation:** `proof-agent run examples/enterprise_qa/agent.yaml` runs the full local enterprise Q&A path with policy, knowledge, memory, MCP mock approval, trace, and receipt.

The primary developer is an enterprise AI platform or Agent architect. They need a controlled Agent framework they can evaluate, test, and explain to security, compliance, and application teams before expanding into broader platform use cases.

## 2. Developer Experience Decisions

| Decision | Accepted direction |
| --- | --- |
| Product type | CLI-first Python Controlled Agent Harness Framework |
| Primary persona | Enterprise AI platform / Agent architect |
| Time to hello world | 2-minute deterministic demo, 30-minute full evaluation |
| Magical moment | `proof-agent demo` shows Harness control decisions, Plain RAG vs Harness RAG, and writes trace + receipt |
| DX mode | DX EXPANSION |

## 3. Public CLI Surface

```bash
proof-agent demo
proof-agent run examples/enterprise_qa/agent.yaml
proof-agent doctor
proof-agent inspect runs/latest/governance_receipt.md
proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"
```

### `proof-agent demo`

Runs the first magical moment:

- uses bundled sample knowledge
- uses a deterministic model/provider
- asks a supported question, unsupported question, and tool-required question
- compares Plain RAG and Harness RAG for the unsupported question
- writes `runs/latest/trace.jsonl`
- writes `runs/latest/governance_receipt.md`

This command must not require an LLM API key.

### `proof-agent run`

Runs a configured Agent from `agent.yaml`.

The v1 supported path is:

```bash
proof-agent run examples/enterprise_qa/agent.yaml
```

### `proof-agent doctor`

Checks local readiness:

- Python version
- package import
- Docker availability
- write access to `runs/`
- presence of `examples/enterprise_qa/agent.yaml`
- optional LLM provider environment variables
- required sample knowledge files

### `proof-agent inspect`

Reads a trace or receipt artifact and prints a concise summary. v1 should support:

```bash
proof-agent inspect runs/latest/governance_receipt.md
proof-agent inspect runs/latest/trace.jsonl
```

### `proof-agent compare`

Runs Plain RAG and Harness RAG for the same question and prints both outcomes.

This command exists to prove Proof Agent is not a plain RAG template.

## 4. Package Structure

```text
proof_agent/
  cli.py
  config/
    manifest.py
    validation.py
  workflow/
    orchestrator.py
    state.py
  policy/
    engine.py
    decisions.py
  validators/
    schema.py
    evidence.py
    tool_result.py
    safety.py
    quality.py
  knowledge/
    local_provider.py
    evidence.py
  runtime/
    langgraph_runner.py
  tools/
    gateway.py
    registry.py
    mcp_mock.py
    approval.py
  memory/
    session.py
  audit/
    trace.py
    receipt.py
    redaction.py
  demo/
    deterministic_provider.py
    scenarios.py
  compare/
    plain_rag.py
    harness_rag.py
examples/
  enterprise_qa/
    agent.yaml
    policy.yaml
    tools.yaml
    knowledge/
tests/
```

## 5. Core Data Models

The normative contracts live in:

- [Agent Contract](concepts/agent-contract.md)
- [Policy Engine](concepts/policy-engine.md)
- [Trace Event Contract](concepts/trace-event-contract.md)
- [Approval State Contract](concepts/approval-state-contract.md)
- [Governance Receipt Contract](concepts/governance-receipt-contract.md)

```text
AgentManifest
  name
  purpose
  workflow.runtime
  workflow.template
  knowledge.provider
  knowledge.path
  model.provider
  model.name
  policy.file
  tools.file
  memory.provider
  audit.trace
  audit.receipt

PolicyDecision
  decision: allow | deny | require_approval | escalate
  enforcement_point
  reason
  policy_rule_id
  metadata
  trace_event_id

EvidenceChunk
  source
  content
  score
  status: accepted | rejected

ApprovalState
  state: requested | granted | denied | timed_out
  tool_name
  reason
  trace_event_id

TraceEvent
  schema_version
  run_id
  event_id
  sequence
  timestamp
  event_type
  span_id
  parent_span_id
  status
  payload
  redaction

ReceiptOutcome
  ANSWERED_WITH_CITATIONS
  REFUSED_NO_EVIDENCE
  ESCALATED_WEAK_EVIDENCE
  WAITING_FOR_APPROVAL
  TOOL_APPROVAL_DENIED
  FAILED_WITH_TRACE
  FAILED_RECEIPT_UNAVAILABLE

RunResult
  final_output
  outcome
  trace_path
  receipt_path
```

Additional v1 framework contracts:

```text
WorkflowState
  run_id
  workflow_name
  current_node
  question
  evidence
  policy_decisions
  tool_requests
  approval_state
  memory_writes
  final_output

ToolRequest
  tool_name
  action
  parameters
  risk_level
  requested_by_node
  requires_approval

ValidationResult
  validator_name
  status: passed | failed
  reason
  metadata
```

## 6. Runtime Flow

The deterministic demo must use the same runtime contracts as the full enterprise evaluation. The deterministic provider replaces only the LLM response source. It must not bypass manifest validation, policy decisions, evidence evaluation, approval state, trace writing, or receipt generation.

```text
CLI command
  |
  v
Load and validate agent.yaml
  |
  v
Build Workflow Orchestrator
  |
  v
Run LangGraph implementation
  |
  v
PolicyEngine.before_retrieval
  |
  v
Local knowledge retrieval
  |
  v
Evidence evaluation
  |
  v
PolicyEngine.before_answer
  | allow                  | deny/escalate
  v                        v
Answer with citations      Refusal / escalation
  |
  v
Optional tool request
  |
  v
Tool Gateway
  |
  v
PolicyEngine.before_tool_call + parameter guard + risk check
  |
  v
Approval state
  | granted                | denied/timeout
  v                        v
MCP mock tool executes     Safe terminal response
  |
  v
PolicyEngine.before_memory_write
  |
  v
Write JSONL trace
  |
  v
Generate Governance Receipt
  |
  v
Print final output + artifact paths
```

## 7. Error Model

Every user-visible error must include:

- what failed
- why it failed
- how to fix it
- artifact path when available
- docs link when available

Initial error code set:

| Code | Trigger | User-visible fix |
| --- | --- | --- |
| `PA_CONFIG_001` | missing `policy.file` | Add `policy.file` to `agent.yaml` |
| `PA_CONFIG_002` | unsupported runtime | Use `workflow.runtime: langgraph` |
| `PA_SCHEMA_001` | unsupported manifest schema version | Update `agent.yaml` to the supported schema |
| `PA_SCHEMA_002` | invalid YAML syntax | Fix YAML syntax at the reported line |
| `PA_KNOWLEDGE_001` | knowledge path missing | Create the path or update `knowledge.path` |
| `PA_KNOWLEDGE_002` | sample index build failed | Rebuild the sample index or inspect source docs |
| `PA_MODEL_001` | missing model credentials for non-deterministic provider | Set the provider API key or use deterministic mode |
| `PA_POLICY_001` | evidence below threshold | Add evidence or change policy threshold |
| `PA_TOOL_001` | approval denied | Continue without tool result or rerun with approval |
| `PA_APPROVAL_001` | approval timed out | Rerun and answer the approval prompt before timeout |
| `PA_DOCKER_001` | Docker unavailable for full evaluation | Start Docker or run `proof-agent demo` |
| `PA_RUNS_001` | `runs/` path is not writable | Change permissions or configure a writable audit path |
| `PA_AUDIT_001` | trace write failed | Check `audit.trace` path permissions |
| `PA_RECEIPT_001` | receipt generation failed | Inspect preserved `trace.jsonl` |
| `PA_SECRET_001` | sensitive value redacted | Check redaction summary, not raw secret output |

Example:

```text
PA_CONFIG_001: missing policy.file
Cause: examples/enterprise_qa/agent.yaml does not reference a policy file.
Fix: add:
  policy:
    file: ./policy.yaml
Docs: docs/concepts/agent-contract.md
```

## 8. Testing Strategy

### Unit Tests

- manifest schema accepts valid `agent.yaml`
- manifest schema rejects missing policy, knowledge, model, tools, memory, or audit fields
- policy decisions cover `allow`, `deny`, `require_approval`, and `escalate`
- evidence evaluator accepts enough evidence and rejects weak evidence
- redaction removes secrets and unnecessary personal data
- receipt generator maps required sections to trace events

### Integration Tests

- enterprise QA workflow returns cited answer for supported question
- unsupported question refuses or escalates
- MCP mock approval requested state persists in workflow state
- approval granted executes mock tool
- approval denied or timed out returns safe response
- failed receipt generation preserves trace and reports `FAILED_RECEIPT_UNAVAILABLE`
- fixed prompt-injection fixtures cannot bypass policy
- deterministic demo uses the same policy, evidence, approval, trace, and receipt code paths as full runs

### E2E Tests

- `proof-agent demo`
- `proof-agent run examples/enterprise_qa/agent.yaml`
- `proof-agent compare examples/enterprise_qa/agent.yaml --question "..."`
- Docker Compose first-run path
- README launch path smoke test

### CI Gates

- lint
- type check
- pytest
- CLI smoke tests
- artifact existence checks for `trace.jsonl` and `governance_receipt.md`

## 9. Implementation Phases

### Phase 1: Package And CLI Scaffold

- create `pyproject.toml`
- create `proof_agent/`
- create `tests/`
- implement empty CLI with `demo`, `run`, `doctor`, `inspect`, and `compare`
- add pytest baseline

### Phase 2: Contracts

- implement `AgentManifest`
- implement policy decision model
- implement trace event model
- implement approval state model
- implement receipt outcome enum
- implement config validation errors

### Phase 3: Deterministic Demo

- implement bundled demo scenarios
- implement deterministic provider
- write deterministic Plain RAG vs Harness RAG comparison through the real pipeline
- write deterministic trace through the real trace writer
- generate deterministic Governance Receipt

### Phase 4: Enterprise QA Runtime

- implement local knowledge provider
- implement evidence evaluator
- integrate LangGraph workflow
- implement session memory
- implement MCP mock approval states

### Phase 5: Audit And Trust

- implement JSONL trace writer
- implement receipt generator from trace events
- implement redaction
- add trust-boundary tests
- implement `inspect`

### Phase 6: Distribution

- add Docker Compose path
- add GitHub Actions
- add README smoke test
- add release checklist

## 10. v1 Non-Goals

- GUI playground
- hosted control plane
- production MCP Gateway or OAuth
- public multi-runtime adapter
- multi-provider production matrix
- multi-industry template library
- persistent user or task memory

## 11. Acceptance Criteria

v1 is accepted only when:

- `proof-agent demo` runs without an LLM key and completes in under 2 minutes
- `proof-agent run examples/enterprise_qa/agent.yaml` completes the enterprise Q&A path
- supported question returns cited answer
- unsupported question refuses or escalates
- tool-required question enters approval state
- Plain RAG and Harness RAG visibly diverge for unsupported question
- every run writes `runs/latest/trace.jsonl`
- every run writes `runs/latest/governance_receipt.md`
- receipt satisfies Governance Receipt Contract
- trust-boundary tests pass
- README launch path smoke test passes
