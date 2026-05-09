# Proof Agent

Proof Agent is an **Enterprise Agent Delivery Kit**.

It gives enterprise AI Agent owners a runnable, governed knowledge Q&A Agent that can be delivered, inspected, and reused. The delivery kit is powered by a **Control Envelope**: policy, evidence, approval, memory boundaries, trace, and a human-readable Governance Receipt around the Agent run.

## Why This Exists

普通 RAG demo 证明 Agent 能回答问题。Proof Agent 证明 Agent 为什么可以回答、什么时候必须拒答、什么时候必须等人工审批、以及事后如何复盘。

The first v1 demo is a strongly controlled enterprise knowledge Q&A Agent:

- mandatory knowledge retrieval before answering
- evidence-based answer, refusal, or escalation
- citation requirements for supported answers
- explicit MCP tool approval state
- bounded session memory writes
- JSONL trace as the audit source of truth
- human-readable Governance Receipt for every run

## The 2-Minute Demo

```bash
proof-agent demo
```

The first demo must run without an LLM API key. It uses bundled sample knowledge and a deterministic provider to show:

- Plain RAG answering loosely
- Harness RAG refusing or escalating unsupported questions
- a supported answer with citations
- a tool-required question pausing for approval
- `runs/latest/trace.jsonl`
- `runs/latest/governance_receipt.md`

## The 30-Minute Enterprise Evaluation

```bash
docker compose up
proof-agent run examples/enterprise_qa/agent.yaml
```

The full local evaluation must show three visible outcomes:

| Question type | Example | Expected Harness behavior |
| --- | --- | --- |
| Supported | "What is the reimbursement rule for travel meals?" | Answer with citations and receipt |
| Unsupported | "What discount should we give this customer next year?" | Refuse or escalate because evidence is missing |
| Tool-required | "Look up customer policy status before answering." | Pause for approval before the MCP mock tool runs |

The side-by-side evaluation should show two paths:

1. **Plain RAG** answers loosely.
2. **Harness RAG** answers only when policy, evidence, tool approval, and audit requirements are satisfied.

The output includes a final answer or refusal plus:

- `runs/latest/trace.jsonl`
- `runs/latest/governance_receipt.md`

## Core Model

```text
User Question
     |
     v
Agent Contract: agent.yaml
     |
     v
Control Envelope
  |-- PolicyEngine
  |-- Evidence checks
  |-- Tool approval
  |-- Memory boundary
  |-- JSONL trace
  `-- Governance Receipt
     |
     v
Enterprise Agent Response
```

Proof Agent does not replace LangGraph, LlamaIndex, MCP, or observability tools. It composes them behind an enterprise control envelope.

## Documentation

- [Control Envelope](docs/concepts/control-envelope.md)
- [Agent Contract](docs/concepts/agent-contract.md)
- [Policy Engine](docs/concepts/policy-engine.md)
- [Governance Receipt Contract](docs/concepts/governance-receipt-contract.md)
- [Trace Event Contract](docs/concepts/trace-event-contract.md)
- [Approval State Contract](docs/concepts/approval-state-contract.md)
- [Trust Boundaries](docs/concepts/trust-boundaries.md)
- [Launch Script](docs/examples/launch-script.md)
- [Technical Plan](docs/Proof%20Agent%20Technical%20Plan.md)
- [Enterprise Q&A Demo](docs/examples/enterprise-qa.md)
- [Governance Receipt](docs/examples/governance-receipt.md)
- [Framework Design](docs/Proof%20Agent%20Framework%20Design.md)
- [Engineering Review](docs/Proof%20Agent%20Engineering%20Review.md)
- [Test Plan](docs/Proof%20Agent%20Test%20Plan.md)

## v1 Scope

v1 is intentionally narrow: one excellent enterprise Q&A delivery template, one public runtime path using LangGraph, deterministic demo mode, local knowledge, session memory, one MCP mock tool with approval state, JSONL trace, Governance Receipt, CLI, Docker Compose, and CI.

Multi-runtime support, multiple production providers, GUI policy playground, policy packs, and additional industry templates are vNext.
