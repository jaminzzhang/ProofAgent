# Coding Agent Common Guide

This document is the shared operating guide for coding agents working in this repository. `AGENTS.md`, `GEMINI.md`, and `CLAUDE.md` should stay as thin entry points and reference this file for common project rules.

## Agent Skills

### Issue Tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage Labels

Standard triage vocabulary (`needs-triage`, `ready-for-agent`, etc.). See `docs/agents/triage-labels.md`.

### Domain Docs

Single-context layout at the repo root. Read `CONTEXT.md` for domain language and see `docs/agents/domain.md` for routing rules.

## Project Overview

Proof Agent is a **Controlled Agent Harness Framework** for enterprise Agent delivery. It wraps Agent execution in a **Control Envelope**: workflow orchestration, policy gates, evidence checks, model provider governance, tool approval, memory boundaries, validators, JSONL trace, Dashboard API, and a human-readable Governance Receipt.

The target user is an enterprise AI Agent owner, Agent platform owner, or platform architect who needs governed, auditable Agent behavior rather than a generic chatbot or ungoverned RAG demo.

Use these terms consistently: `Controlled Agent Harness Framework`, `Control Envelope`, `Harness Engineering`, `Harness RAG`, `Plain RAG`, `Agent Contract`, `PolicyEngine`, `Tool Gateway`, `MCP approval`, `Trace & Audit`, `Governance Receipt`, `Enterprise QA Template`, `Enterprise QA Reference Agent`, `Assisted QA Chat Frontend`, `Customer Service Chat Frontend`, `Unified Chat Frontend`, and `Controlled Conversation Context`.

## Current Status

The repository contains a Python MVP plus application surfaces:

- Python package with typed contracts, bootstrap/composition, policy enforcement, LangGraph runtime runner, knowledge providers, model provider boundaries, tool approval gating, bounded memory, trace/audit output, RunStore, ConversationStore, Dashboard API, Run Execution API, comparison utilities, tests, CI, Docker assets, and deterministic examples.
- Dashboard frontend under `dashboard/` for run history, stats, run detail, timeline, evidence, approval, receipt, and model usage views.
- Unified Chat frontend under `chat/` for operator-facing Assisted QA Chat and customer-facing Customer Service Chat modes.
- The canonical example Agent package under `examples/insurance_customer_service/`.

The deterministic demo must remain runnable without network access, API keys, or external services. Expected demo outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

Demo artifacts are written to `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`. Generated run output is ignored by git except for `runs/.gitkeep`.

Current known gaps and extension directions:

- LangGraph runtime exists; production checkpoint interrupt/resume and streaming hooks are still future work.
- Real MCP stdio/HTTP transport is not implemented; mock tools prove the approval contract.
- `openai_compatible` is implemented; Azure OpenAI and Anthropic providers are clean-failure placeholders.
- Local vector retrieval can query existing indexes; index build lifecycle and broader vector adapters are future work.
- Dashboard and Chat SPAs exist; production Approval Console, RBAC, hosted compliance, and multi-agent management are future work.

## Source Of Truth

Read these before planning or changing behavior:

1. `CONTEXT.md` — canonical domain language and relationships.
2. `docs/README.md` — documentation routing.
3. `docs/technical-design.md` — authoritative architecture, module boundaries, contracts, provider strategy, error codes, trace events, and roadmap.
4. `docs/developer-guide.md` — user-facing Agent owner workflow, setup, configuration, deployment, and operations.
5. `docs/development-progress.md` — current/historical implementation snapshot; useful but may be stale, so verify against code.
6. `docs/adr/` — architectural decision records.
7. `docs/concepts/` — normative concept contracts for Control Envelope, Agent Contract, Policy Engine, Approval State, Trace Events, Governance Receipt, and Trust Boundaries.

Documentation is bilingual. English docs live under `docs/`; Chinese translations live under `docs/zh/` with the same structure. **Only update English docs during development; Chinese translations are synced at release time.**

## Project Structure

- `proof_agent/bootstrap/` owns `agent.yaml` loading, validation, path resolution, secret-looking parameter rejection, and Harness invocation composition.
- `proof_agent/contracts/` owns public Pydantic v2 frozen contract models and provider-neutral ports. Keep framework/provider-specific objects out of this layer.
- `proof_agent/control/` owns workflow orchestration, `PolicyEngine`, validators, approval semantics, memory policy checks, evidence admission, and outcome behavior.
- `proof_agent/runtime/` owns LangGraph/LangChain runtime adapter boundaries. Runtime mechanics must not redefine Control Plane semantics.
- `proof_agent/capabilities/` owns concrete abilities: model providers, knowledge/retrieval providers, memory, Tool/MCP adapters, and future Skill packs.
- `proof_agent/observability/` owns audit trace, redaction, Governance Receipt, RunStore, ConversationStore, Dashboard read API, and API serializers.
- `proof_agent/delivery/` owns CLI, Run Execution API, Conversation API, and future execution entry points. `proof_agent/cli.py` is a compatibility shim.
- `proof_agent/evaluation/` owns deterministic demo helpers and Plain RAG vs Harness RAG comparison.
- `tests/` contains pytest coverage for contracts, bootstrap, policy, knowledge, model providers, tool approval, memory, audit output, API, compare, workflow, and CLI behavior.
- `dashboard/` contains the Vite/React Dashboard SPA.
- `chat/` contains the Vite/React Unified Chat SPA with `/operator` and `/customer` modes.
- `examples/` contains the canonical runnable Agent package.
- `docs/` contains product, architecture, concept, example, agent, and ADR documentation.
- `runs/` is the local audit output directory; only `runs/.gitkeep` should be committed.

## Build, Test, And Development Commands

Use `uv` for Python development:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev ruff format proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
uv run --extra dev proof-agent demo
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml --question "What documents are required for inpatient claim reimbursement?"
uv run --extra dev proof-agent compare examples/insurance_customer_service/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
uv run --extra dashboard proof-agent server --host 127.0.0.1 --port 8000
docker compose up
```

Frontend development:

```bash
cd dashboard && npm install
cd dashboard && npm run dev
cd dashboard && npm run build
cd dashboard && npm test

cd chat && npm install
cd chat && npm run dev
cd chat && npm run build
cd chat && npm test
```

The Dashboard dev server runs on port 5173 by default. The Chat dev server runs on port 5174 by default. Both expect the API server on `127.0.0.1:8000`. Use `/operator` for Assisted QA Chat and `/customer` for Customer Service Chat.

For documentation-only edits, at minimum run:

```bash
git diff --check
```

For runtime changes, run pytest, Ruff, mypy, and at least one CLI demo path. For frontend changes, run the relevant app's build/test command and inspect the changed UI.

## Architecture Rules

- Control Plane owns decisions. Runtime and Capability layers cannot bypass `PolicyEngine`, approval, validators, evidence admission, memory policy, or outcome mapping.
- Runtime Plane owns execution mechanics. LangGraph/LangChain can provide graph execution, checkpoint, interrupt/resume, and streaming hooks, but cannot redefine Harness governance semantics.
- Capability Layer owns concrete integrations. Model, knowledge, memory, tools, MCP, and Skills are exposed through Proof Agent ports and contracts.
- Contracts & Ports define stable DTOs and provider protocols; they are not an execution layer.
- Audit & Observability is a side channel. Trace is written during execution; Receipt and Dashboard API are read projections and must not create a second workflow or tool execution path.
- The Run Execution API starts governed runs for Published Agents; application surfaces must not submit arbitrary manifest paths.
- Dashboard read APIs and frontend views observe run artifacts; they must not bypass the core Harness workflow.
- Deterministic demo paths must use the same policy/evidence/approval/trace/receipt code paths as full runs.
- Third-party SDK types from LangGraph, LangChain, MCP, Chroma, OpenAI, Azure, Anthropic, or frontend libraries must not leak into public contracts, bootstrap, control, trace, receipt, or Dashboard contracts.

## Coding Style

Python:

- Python 3.12+, 4-space indentation, snake_case modules/functions, PascalCase classes.
- Use explicit type hints on public APIs.
- Prefer small typed functions and keep side effects behind adapters, storage, or CLI/API entry points.
- Public contracts use Pydantic v2 frozen models.
- Keep provider-specific behavior behind adapters and registries.

Frontend:

- Dashboard and Chat use React 19, Vite, React Router, TypeScript, and Tailwind CSS v4.
- Keep frontend API types aligned with `proof_agent/contracts/` and API serializers.
- Preserve the product tone: operational, audit-focused, dense enough for repeated enterprise use.

Markdown:

- Use clear headings, short paragraphs, and tables only when they improve scanability.
- Keep terminology aligned with `CONTEXT.md`.
- Configuration examples should stay in YAML or JSON with descriptive file names, such as `examples/insurance_customer_service/agent.yaml`.

## Testing Guidelines

Tests live under `tests/` and should be named `test_<module>.py`. Focus coverage on externally visible behavior and contracts:

- workflow routing and refusal behavior
- evidence-backed answer generation and citation validation
- model provider request/response boundaries
- memory read/write behavior and denylist enforcement
- MCP/tool registration and approval gating
- policy decisions and redaction
- trace/audit event output
- Governance Receipt rendering
- RunStore, ConversationStore, Dashboard API, and Run Execution API behavior
- Plain RAG vs Harness RAG comparison
- CLI behavior

## Security And Configuration

- Do not commit API keys, model provider credentials, vector database secrets, bearer tokens, passwords, connection strings, or production URLs with secrets.
- Use `.env.example` for required variable names and keep real secrets in local ignored files or environment variables.
- `agent.yaml` may declare provider names, model names, env var names, timeouts, token limits, and paths. It must not contain raw secrets.
- Trace payloads and receipts must preserve redaction guarantees. Current redaction coverage includes API keys, access tokens, bearer tokens, passwords, secrets, connection strings, customer phone values, and provider API keys.
- Generated artifacts under `runs/latest/` and run history outputs should not be committed.
