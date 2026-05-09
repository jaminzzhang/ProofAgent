# Proof Agent

Proof Agent is a **Controlled Agent Harness Framework** for building enterprise Agents that are workflow-governed, policy-enforced, tool-gated, memory-bounded, validated, and auditable.

The long-term vision is an enterprise Agent Control Platform. The v1 release stays intentionally narrow: a local-first, CLI-first framework MVP that proves the platform direction through one runnable enterprise knowledge Q&A reference template.

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
User Goal / Question
     |
     v
Agent Contract: agent.yaml
     |
     v
Control Envelope
  |-- Workflow Orchestrator
  |-- PolicyEngine
  |-- Tool Gateway
  |-- Validators / Evaluators
  |-- Evidence checks
  |-- Tool approval
  |-- Memory boundary
  |-- JSONL trace
  `-- Governance Receipt
     |
     v
Enterprise Agent Response
```

Proof Agent does not replace LangGraph, MCP, vector stores, or observability tools. It composes them behind an enterprise control envelope. In v1, LangGraph is an implementation detail for workflow execution; the public model is Workflow + Policy + Gateway + Validator + Audit.

## Architecture Layers

```text
User / CLI / API
  -> Agent Control Layer
  -> Agent Runtime Layer
  -> Gateway & Context Layer
  -> Verification & Governance Layer
  -> Templates & Examples
```

v1 implements the narrow local path:

```text
CLI
  -> agent.yaml
  -> Workflow Orchestrator
  -> Policy Engine + Validator
  -> Local Knowledge + MCP Mock Tool + Session Memory
  -> Trace + Governance Receipt
  -> Enterprise QA Template
```

## Documentation

- [Controlled Agent Harness Redesign](docs/superpowers/specs/2026-05-09-controlled-agent-harness-redesign.md)
- [Controlled Agent Harness Framework](docs/Proof%20Agent%20-%20Controlled%20Agent%20Harness%20Framework.md)
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

v1 is intentionally narrow: one excellent enterprise Q&A reference template, one public local CLI path, deterministic demo mode, local knowledge, session memory, one MCP mock tool routed through Tool Gateway approval state, validators, JSONL trace, Governance Receipt, Docker Compose, and CI.

Multi-runtime support, multiple production providers, GUI policy playground, policy packs, and additional industry templates are vNext.
