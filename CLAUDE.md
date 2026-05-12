# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard triage vocabulary (`needs-triage`, `ready-for-agent`, etc.). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout at the repo root. See `docs/agents/domain.md`.

## Project Overview

Proof Agent is a **Controlled Agent Harness Framework**. It wraps Agent execution in a **Control Envelope**: workflow orchestration, policy engine, evidence checks, model provider governance, tool approval, memory boundaries, validators, JSONL trace, Dashboard API, and a human-readable Governance Receipt. The first template is enterprise knowledge Q&A.

The target user is an enterprise AI Agent owner or platform architect who needs to deliver a governed, auditable Agent — not a generic hobby developer.

## Current State

The codebase has working Python modules, 28 test files, a deterministic demo, remote model provider boundaries, Dashboard API, Docker assets, and CI. The package is organized by architecture layer: `bootstrap/`, `control/`, `runtime/`, `capabilities/`, `observability/`, `delivery/`, `evaluation/`, and `contracts/`. The deterministic demo produces three outcomes: `ANSWERED_WITH_CITATIONS`, `REFUSED_NO_EVIDENCE`, and `WAITING_FOR_APPROVAL`. Demo artifacts are written to `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`.

**Not yet implemented:** production LangGraph StateGraph with `interrupt()` for real approval, real MCP stdio/HTTP transport, Dashboard UI / Approval Console, and real Azure/Anthropic providers.

## Development Progress

`docs/development-progress.md` records development status as of its last update date. It is a useful starting reference for understanding module status, test coverage, and roadmap completion, but **it may be stale — always verify its claims against the actual codebase** (run tests, check file contents, review git log) before trusting it.

## Build and Development Commands

```bash
uv run --extra dev python -m pytest tests/ -v              # run all tests
uv run --extra dev python -m pytest tests/test_cli.py -v   # run single test file
uv run --extra dev python -m pytest -k "test_demo" -v      # run tests matching name
uv run --extra dev ruff check proof_agent tests            # lint
uv run --extra dev ruff format proof_agent tests           # format
uv run --extra dev mypy proof_agent                        # type check
uv run --extra dev proof-agent demo                        # deterministic demo (no LLM key needed)
uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml  # full enterprise run
uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount?"  # baseline vs governed
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md  # inspect receipt
docker compose up                                         # full local evaluation
```

## Documentation

Documentation is bilingual: English (default) under `docs/`, Chinese translations under `docs/zh/` with the same directory structure. **Only update English docs during development; Chinese translations are synced at release time. Always reference English docs as the source of truth.**

**`docs/technical-design.md`** is the authoritative technical design document for this project. It covers:

- Design principles (harness controls flow, model only generates; deterministic regression baseline; third-party SDK isolation; auditable failures; untrusted remote output; explicit config without secrets)
- Total architecture and Control Envelope data flow
- Developer lifecycle and Agent package workflow
- Current implementation baseline per module
- Module-by-module decisions: Bootstrap / Composition, Control Plane, Runtime Plane, Capability Layer, Contracts & Ports, Audit & Observability
- Contract shapes: `ModelRole`, `ModelMessage`, `TokenUsage`, `ModelRequest`, `ModelResponse`, `ModelConfig`
- Provider protocol, registry, and factory design
- Agent contract (`agent.yaml`) schema for deterministic and remote providers
- Error codes (`PA_MODEL_001` through `PA_MODEL_004`)
- Directory structure and dependency design
- Implementation roadmap and adapter expansion strategy

**When planning features, writing implementation plans, or writing code, always read this document first and follow its design decisions.**

Other key docs:

- `docs/prd.md` — MVP scope, modules, architecture, and delivery milestones.
- `docs/feasibility-analysis.md` — feasibility, audience, stack options, and risks.
- `docs/developer-guide.md` — user-facing setup and deployment workflows.
- `docs/development-progress.md` — historical module status and roadmap (may be stale; verify against codebase).
- `docs/concepts/` — framework concept references: Control Envelope, Agent Contract, Policy Engine, Trace Events, Approval State, Governance Receipt, Trust Boundaries.
- `docs/examples/` — enterprise Q&A demo, launch script, and Governance Receipt examples.

## Tech Stack

See `docs/technical-design.md` for full analysis.

- Python 3.12+, `typer` for CLI, `pydantic` v2 for data contracts (frozen=True)
- `langgraph >= 1.1.0` as runtime adapter direction
- `mcp[cli] >= 1.27.0` + `langchain-mcp-adapters` for MCP adapter direction
- `sentence-transformers` + `chromadb` behind optional `[vector]`
- `openai` behind optional `[openai]` for OpenAI-compatible remote providers
- `jinja2` for Governance Receipt Markdown generation
- `pytest` for tests, `ruff` for lint/format, `mypy` for type checking
- Portable JSONL for audit, CLI and Docker Compose for distribution

**Key tech decision:** third-party runtime, model, vector, and MCP SDKs stay behind adapters. Contracts, bootstrap, control, trace, receipt, and Dashboard contracts must not expose SDK-specific objects.

## Architecture

### Core Abstraction: Control Envelope

The Control Envelope wraps every Agent run with enforced policy, evidence, approval, memory, trace, and receipt. It does NOT replace LangGraph, MCP, or ChromaDB — it composes them behind an enterprise control contract.

### Architecture Layers

```
Delivery / Entry
  -> Bootstrap / Composition
  -> Control Plane
  -> Runtime Plane
  -> Capability Layer
  -> Infrastructure

Contracts & Ports define the shared language.
Audit & Observability records facts as a side channel.
```

### Data Flow

```
CLI/Docker command
  -> load and validate agent.yaml
  -> run Enterprise QA Harness workflow
      -> PolicyEngine.before_retrieval
      -> Knowledge retrieval + evidence evaluation
      -> PolicyEngine.before_answer
      -> PolicyEngine.before_model_call
      -> ModelProvider.generate
      -> Validators
      -> optional ToolGateway approval path
      -> memory policy/write
      -> final outcome
  -> JSONL trace -> RunStore -> Governance Receipt / Dashboard API
```

### Key Modules

| Module | Responsibility |
|--------|---------------|
| `bootstrap/` | Load and validate `agent.yaml`, resolve paths, enforce config boundaries |
| `contracts/` | Pydantic v2 frozen models for policy decisions, evidence, approval, trace events, receipts, manifests, runs |
| `control/` | Workflow orchestration, PolicyEngine, validators, approval semantics, and outcome behavior |
| `runtime/` | LangGraph/LangChain runtime adapter boundaries |
| `capabilities/` | Model providers, knowledge/retrieval, memory, ToolGateway/MCP, and future Skill packs |
| `observability/` | JSONL trace, redaction, Governance Receipt, RunStore, and Dashboard read API |
| `delivery/` | CLI and future execution entry points |
| `evaluation/` | Deterministic demo helpers and Plain RAG vs Harness RAG comparison |
| `proof_agent/cli.py` | Backward-compatible CLI shim; implementation lives in `delivery/cli.py` |

### Policy Engine

The heart of the Control Envelope. Five enforcement points:

1. `before_retrieval` — may the Agent retrieve knowledge?
2. `before_answer` — is evidence sufficient to answer?
3. `before_tool_call` — is the tool call allowed, denied, or requires approval?
4. `before_memory_write` — may generated info be written to session memory?
5. `before_model_call` — may this provider/model/cost/token/stream call proceed?

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

Use these terms consistently: `Controlled Agent Harness Framework`, `Control Envelope`, `Harness Engineering`, `Harness RAG`, `Plain RAG`, `Agent Contract`, `PolicyEngine`, `Tool Gateway`, `MCP approval`, `Trace & Audit`, `Governance Receipt`, `Enterprise QA Template`.

## Implementation Rules

- LangGraph types must NOT leak into bootstrap, control, trace, receipt, or public contract models
- Deterministic demo must use the same policy/evidence/approval/trace/receipt code paths as full runs
- Invalid `agent.yaml` must fail before execution starts with actionable error codes
- Trace writing failure before model/tool execution = fail closed
- Receipt generation failure = preserve trace and report `FAILED_RECEIPT_UNAVAILABLE`
- Redacted values must never appear in trace payloads; `redaction.fields` names field classes only

## v1 Non-Goals

Production LangGraph interrupt/checkpoint wiring, real MCP transport, Dashboard UI / Approval Console, OAuth, multi-tenant auth, hosted compliance, persistent user/task memory, and template library beyond enterprise Q&A.
