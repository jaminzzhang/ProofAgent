# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Proof Agent is an **Enterprise Agent Delivery Kit** — a CLI-first Python package that wraps an Agent execution in a **Control Envelope**: policy engine, evidence checks, tool approval, memory boundaries, JSONL trace, and a human-readable Governance Receipt. The first template is enterprise knowledge Q&A.

The target user is an enterprise AI Agent owner or platform architect who needs to deliver a governed, auditable Agent — not a generic hobby developer.

## Current State

**Documentation-only.** No source code, tests, or build tooling exists yet. The implementation plan is in `docs/superpowers/plans/2026-05-09-proof-agent-v1.md`.

## Build and Development Commands

Once implementation starts (from the plan):

```bash
python -m pytest tests/ -v              # run all tests
python -m pytest tests/test_cli.py -v   # run single test file
python -m pytest -k "test_demo" -v      # run tests matching name
ruff check proof_agent/                 # lint
ruff format proof_agent/                # format
proof-agent demo                        # deterministic demo (no LLM key needed)
proof-agent run examples/enterprise_qa/agent.yaml  # full enterprise run
docker compose up                       # full local evaluation
```

## Tech Stack

Full analysis: `docs/Proof Agent 技术选型.md`

- Python 3.12+, `typer` for CLI, `pydantic` v2 for data contracts (frozen=True)
- `langgraph >= 1.1.0` for workflow runtime (StateGraph + interrupt() for approval)
- `mcp[cli] >= 1.27.0` + `langchain-mcp-adapters` for MCP mock tool (stdio transport)
- `sentence-transformers` + `chromadb` for local RAG (self-built, not LlamaIndex)
- `jinja2` for Governance Receipt Markdown generation
- `pytest` for tests, `ruff` for lint/format, `mypy` for type checking
- Local JSONL for audit, Docker Compose for distribution

**Key tech decision:** Knowledge/RAG is self-built (~280 lines) rather than using LlamaIndex. Reason: LlamaIndex's 50+ subpackages and frequent API changes conflict with v1's "controlled" principle. Self-built RAG puts every step through Harness policy gates with zero framework black box.

## Architecture

### Core Abstraction: Control Envelope

The Control Envelope wraps every Agent run with enforced policy, evidence, approval, memory, trace, and receipt. It does NOT replace LangGraph, MCP, or ChromaDB — it composes them behind an enterprise control contract.

### Data Flow

```
CLI command → Load agent.yaml → Build LangGraph workflow
  → PolicyEngine.before_retrieval → Knowledge retrieval + evidence evaluation
  → PolicyEngine.before_answer → (allow: answer with citations | deny: refuse/escalate)
  → Optional tool request → PolicyEngine.before_tool_call → Approval state
  → PolicyEngine.before_memory_write → JSONL trace → Governance Receipt
```

### Key Modules (planned)

| Module | Responsibility |
|--------|---------------|
| `config/` | Load and validate `agent.yaml` manifest |
| `policy/` | Typed decisions (`allow`, `deny`, `require_approval`, `escalate`) at 4 enforcement points |
| `knowledge/` | Local document retrieval and evidence evaluation |
| `runtime/` | Workflow state and LangGraph execution |
| `tools/` | MCP mock tool with explicit approval state machine |
| `memory/` | Session memory only (v1) |
| `audit/` | JSONL trace writer, redaction, Governance Receipt generator |
| `demo/` | Deterministic provider (no LLM key needed) and bundled scenarios |
| `compare/` | Plain RAG vs Harness RAG comparison |

### Policy Engine

The heart of the Control Envelope. Four enforcement points:

1. `before_retrieval` — may the Agent retrieve knowledge?
2. `before_answer` — is evidence sufficient to answer?
3. `before_tool_call` — is the tool call allowed, denied, or requires approval?
4. `before_memory_write` — may generated info be written to session memory?

Every decision is typed, traced, and summarized in the Governance Receipt.

### Approval State Machine

Tool approval is an explicit workflow state (not a callback): `requested → granted | denied | timed_out`. Each state emits trace events.

## Key Contracts (docs/concepts/)

These are normative — implementation must satisfy them:

- **Agent Contract** (`agent-contract.md`): `agent.yaml` schema and failure behavior
- **Policy Engine** (`policy-engine.md`): enforcement points, decisions, minimum policy YAML schema
- **Trace Event Contract** (`trace-event-contract.md`): JSONL envelope, 19 v1 event types, semantic mapping to OpenTelemetry
- **Approval State Contract** (`approval-state-contract.md`): state machine, CLI UX, trace/receipt requirements
- **Governance Receipt Contract** (`governance-receipt-contract.md`): 7 outcomes, required sections, redaction rules, trace mapping
- **Trust Boundaries** (`trust-boundaries.md`): what v1 controls vs. what it does not claim

## Terminology

- **Harness Engineering**: the design discipline of inserting typed policy decision points into Agent workflows to achieve controlled execution. This is the mechanism behind the Control Envelope.
- **Harness RAG**: an Agentic RAG implementation governed by the Harness — mandatory retrieval, evidence evaluation, citation enforcement, refusal on weak evidence, explicit tool approval, and audit trail. Contrasted with Plain RAG (uncontrolled retrieve-and-generate).
- **Plain RAG**: standard retrieve-and-generate without policy gates or evidence checks.

Use these terms consistently: `Enterprise Agent Delivery Kit`, `Control Envelope`, `Harness Engineering`, `Harness RAG`, `Plain RAG`, `Agent Contract`, `PolicyEngine`, `MCP mock tool approval`, `Trace & Audit`, `Governance Receipt`, `Enterprise QA Template`.

## Implementation Rules

- LangGraph types must NOT leak into config, policy, trace, or receipt models
- Deterministic demo must use the same policy/evidence/approval/trace/receipt code paths as full runs
- Invalid `agent.yaml` must fail before execution starts with actionable error codes
- Trace writing failure before model/tool execution = fail closed
- Receipt generation failure = preserve trace and report `FAILED_RECEIPT_UNAVAILABLE`
- Redacted values must never appear in trace payloads; `redaction.fields` names field classes only

## v1 Non-Goals

Multi-runtime support, multiple production providers, GUI policy playground, full MCP Gateway, OAuth, multi-tenant auth, hosted compliance, persistent user/task memory, template library beyond enterprise Q&A.
