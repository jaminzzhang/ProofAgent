# Proof Agent

Proof Agent is a **Controlled Agent Harness Framework** for building enterprise Agents that are workflow-governed, policy-enforced, tool-gated, memory-bounded, validated, and auditable.

The long-term vision is an enterprise Agent Control Platform. The current release keeps a deterministic local demo as the regression baseline, while supporting CLI and Docker entry points plus adapter-driven remote model, runtime, vector, MCP, and Dashboard API paths.

Proof Agent still ships as an **Enterprise Agent Delivery Kit**, but that is the delivery shape rather than the core identity. The framework provides the Harness; the delivery kit packages it; the enterprise Q&A template proves it.

## What is Harness

Proof Agent uses **Harness Engineering** to build the Control Envelope. A Harness is a control layer that wraps around the Agent execution flow, inserting explicit policy decision points at every critical step — retrieval, answer generation, tool calls, and memory writes. This is what makes the Agent flow controlled (受控), not just orchestrated.

**Harness RAG** is an **Agentic RAG** implementation governed by the Harness. Unlike Plain RAG (retrieve → generate), Harness RAG adds policy gates at each step: mandatory retrieval before answering, evidence quality evaluation, citation enforcement, refusal on weak evidence, and explicit tool approval. The result is not just a better answer — it is a governed, auditable answer.

```text
Plain RAG:      Retrieve → Generate (no control gates)
Harness RAG:    Retrieve → Policy → Evidence → Policy → Answer/Refuse → Tool Approval → Audit
```

## Why This Exists

普通 Agent 或 RAG demo 证明模型能回答问题。Proof Agent 证明 Agent 为什么可以行动、什么时候必须拒答、什么时候必须等待人工审批、哪些记忆可以写入、以及事后如何复盘。

The first v1 template is a strongly controlled enterprise knowledge Q&A Agent:

- mandatory knowledge retrieval before answering
- evidence-based answer, refusal, or escalation
- citation requirements for supported answers
- explicit MCP tool approval state
- bounded session memory writes
- JSONL trace as the audit source of truth
- human-readable Governance Receipt for every run

## The 2-Minute Demo

```bash
uv run --extra dev proof-agent demo
```

The framework regression demo must run without an LLM API key. It uses internal bundled fixtures and a deterministic provider to show:

- Plain RAG answering loosely
- Harness RAG refusing or escalating unsupported questions
- a supported answer with citations
- a tool-required question pausing for approval
- `runs/latest/trace.jsonl`
- `runs/latest/governance_receipt.md`

## The 30-Minute Enterprise Evaluation

```bash
docker compose up
uv run --extra dashboard --extra ingestion --extra tree proof-agent dev
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
uv run --extra dev proof-agent run examples/institution_insurance_specialist/agent.yaml --question "For short-term accident claims, what should a branch specialist explain to an agent when the claim is still pending?"
uv run --extra dev proof-agent compare examples/insurance_customer_service/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
```

`proof-agent dev` is the local Dashboard backend path: it loads `.env` and starts
both the API server and Knowledge Worker so Knowledge uploads can be processed.
On an empty local configuration store, it also imports and publishes the canonical
`insurance_customer_service` Agent so Dashboard configuration, operator chat, and
customer chat have an immediate closed-loop example.

The regression demo and public package smoke paths together must show three visible outcomes:

| Question type | Example | Expected Harness behavior |
| --- | --- | --- |
| Supported | "What documents are required for inpatient claim reimbursement?" | Answer with citations and receipt |
| Unsupported | "What discount should we give this customer next year?" | Refuse or escalate because evidence is missing |
| Tool-required regression | `proof-agent demo` fixture: "Look up customer policy status before answering." | Pause for approval before the MCP mock tool runs |

The side-by-side evaluation should show two paths:

1. **Plain RAG** answers loosely.
2. **Harness RAG** answers only when policy, evidence, tool approval, and audit requirements are satisfied.

The output includes a final answer or refusal plus:

- `runs/latest/trace.jsonl`
- `runs/latest/governance_receipt.md`

Expected deterministic regression and public smoke questions:

- Regression fixture: `What is the reimbursement rule for travel meals?`
- `What documents are required for inpatient claim reimbursement?`
- `What discount should we give this customer next year?`
- Regression fixture: `Look up customer policy status before answering.`

## Developer Model

Proof Agent is built around an Agent package:

```text
agent.yaml      # Agent Contract
policy.yaml     # Control Plane policy
tools.yaml      # Tool / MCP declaration
knowledge/      # business knowledge source
questions.yaml  # optional evaluation set
expected/       # optional expected trace or receipt examples
```

Developers configure the Agent package, run deterministic validation, inspect trace and receipt artifacts, then optionally switch to a remote model provider or deploy with Docker.

Proof Agent does not replace LangGraph, MCP, vector stores, or observability tools. It composes them behind an enterprise Control Plane. Runtime frameworks execute mechanics; the Control Plane decides whether retrieval, model calls, tool calls, memory writes, and final answers are allowed.

## Architecture Layers

```text
Delivery / Entry
  -> Bootstrap / Composition
  -> Control Plane
  -> Runtime Plane
  -> Capability Layer
  -> Infrastructure

Contracts & Ports define the shared language.
Audit & Observability records facts as a side channel.
```

v1 implements the narrow local path:

```text
Delivery CLI / Docker
  -> Bootstrap: load and validate agent.yaml
  -> Control: workflow, policy gates, validators, outcome
  -> Runtime: LangGraph adapter boundary, currently delegated to orchestrator
  -> Capability: deterministic model, local knowledge, session memory, mock Tool/MCP
  -> Observability: JSONL trace, RunStore, Governance Receipt, Dashboard API
```

The package layout mirrors the architecture:

```text
proof_agent/
  bootstrap/      # manifest loading, validation, composition boundary
  control/        # workflow, policy, validators, governed decisions
  runtime/        # LangGraph/LangChain runtime adapter boundaries
  capabilities/   # models, knowledge, memory, tools, future Skill packs
  observability/  # trace, receipt, RunStore, Dashboard read API
  delivery/       # CLI and future execution entry points
  evaluation/     # demo and Plain RAG vs Harness RAG comparison
  contracts/      # provider-neutral public contracts and ports
```

## Documentation

- [Documentation Index](docs/README.md)
- [Developer Guide](docs/developer-guide.md)
- [Product Requirements](docs/prd.md)
- [Technical Design](docs/technical-design.md)
- [Feasibility Analysis](docs/feasibility-analysis.md)
- [Development Progress](docs/development-progress.md)
- [Control Envelope](docs/concepts/control-envelope.md)
- [Agent Contract](docs/concepts/agent-contract.md)
- [Policy Engine](docs/concepts/policy-engine.md)
- [Governance Receipt Contract](docs/concepts/governance-receipt-contract.md)
- [Trace Event Contract](docs/concepts/trace-event-contract.md)
- [Approval State Contract](docs/concepts/approval-state-contract.md)
- [Trust Boundaries](docs/concepts/trust-boundaries.md)
- [Launch Script](docs/examples/launch-script.md)
- [Insurance Customer Service Agent](docs/examples/insurance-customer-service.md)
- [Institution Insurance Specialist Agent](docs/examples/institution-insurance-specialist.md)
- [Governance Receipt](docs/examples/governance-receipt.md)

Docs are bilingual: English (default) under `docs/`, Chinese translations under `docs/zh/`.

## v1 Scope

v1 is intentionally narrow: public insurance Agent packages for customer-facing service and staff-facing institution specialist assistance, internal deterministic framework fixtures, local knowledge, optional OpenAI-compatible remote model provider paths, bounded memory, governed tools, validators, JSONL trace, RunStore, Governance Receipt, Dashboard API, Docker Compose, and CI.

Production LangChain/LangGraph adapters, real MCP transport, richer vector providers, Dashboard UI, Approval Console, policy packs, and additional industry templates are vNext.
