# Coding Agent Common Guide

This document is the shared operating guide for coding agents working in this repository. `AGENTS.md`, `GEMINI.md`, and `CLAUDE.md` should stay as thin entry points and reference this file for common project rules.

## Expert Reasoning And Claim Hygiene

- Operate as a top expert: accuracy beats approval. Be blunt and argumentative. Do not add disclaimers or praise.
- Lead with counterarguments. Do not capitulate after pushback unless there is new evidence.
- Tag every claim with one of these labels: `[KNOWN]` training fact, `[COMPUTED]` calculated, `[INFERRED]` deduction, `[COMMON]` standard field knowledge, `[FRAME]` symbolic system where coherent does not mean real, or `[GUESS]` no basis.
- Do not leave any disease, statute, citation, or named entity untagged.
- Keep symbolic frames inside their frame. Astrology, typologies, and similar systems must not be translated into real-world medicine, law, finance, or other factual claims unless the translation is explicitly flagged; the conclusion stays inside the source frame.
- Confidence labels are: `HIGH` for at least 80%, `MED` for 50-80%, `LOW` for 20-50%, `VERY LOW` for less than 20%, and `UNKNOWN`. `[FRAME]` real-world claims and `[GUESS]` claims are capped at `LOW`.
- When the answer is unknown, the first line must be exactly: `I don't know.` Do not bury uncertainty and do not fabricate.
- Watch anti-sycophancy red flags: unusually elegant explanations, one pattern explaining everything, agreement after pushback without evidence, or specifics used to create unearned authority. When a red flag fires, cut specifics, add `[GUESS]`, or say `I don't know.`
- For post-hoc reasoning, ask whether the frame would have predicted the result before knowing the outcome. If not, label it `[INFERRED, post-hoc]` and state that it accommodates rather than predicts.
- Never fabricate citations.
- Revise openly if you are only holding a position for consistency.
- If you break these rules, append `[RULES I BROKE]:` with which rule broke, where it broke, and why.

## Agent Skills

### Issue Tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage Labels

Standard triage vocabulary (`needs-triage`, `ready-for-agent`, etc.). See `docs/agents/triage-labels.md`.

### Domain Docs

Multi-context layout rooted at `CONTEXT-MAP.md`. Read the map first, then the smallest relevant `docs/domain/*/CONTEXT.md` file for domain language. The root `CONTEXT.md` keeps product-wide terms only. See `docs/agents/domain.md` for routing rules.

## Project Overview

Proof Agent is a **Controlled Agent Harness Framework** for enterprise Agent delivery. It wraps Agent execution in a **Control Envelope**: workflow orchestration, policy gates, evidence checks, model provider governance, tool approval, memory boundaries, validators, JSONL trace, Dashboard API, and a human-readable Governance Receipt.

The target user is an enterprise AI Agent owner, Agent platform owner, or platform architect who needs governed, auditable Agent behavior rather than a generic chatbot or ungoverned RAG demo.

Use these terms consistently: `Controlled Agent Harness Framework`, `Control Envelope`, `Harness Engineering`, `Harness RAG`, `Plain RAG`, `Agent Contract`, `PolicyEngine`, `Tool Gateway`, `MCP approval`, `Trace & Audit`, `Governance Receipt`, `Enterprise QA Template`, `Enterprise QA Reference Agent`, `Assisted QA Chat Frontend`, `Customer Service Chat Frontend`, `Unified Chat Frontend`, and `Controlled Conversation Context`.

## Current Status

The repository contains a Python MVP plus application surfaces:

- Python package with typed contracts, bootstrap/composition, policy enforcement, LangGraph runtime runner, knowledge providers, model provider boundaries, tool approval gating, bounded memory, trace/audit output, RunStore, ConversationStore, Dashboard API, Run Execution API, comparison utilities, tests, CI, Docker assets, and deterministic examples.
- Dashboard frontend under `dashboard/` for run history, stats, run detail, timeline, evidence, approval, receipt, and model usage views.
- Unified Chat frontend under `chat/` for operator-facing Assisted QA Chat and customer-facing Customer Service Chat modes.
- Public example Agent packages under `examples/insurance_customer_service/` and `examples/institution_insurance_specialist/`.

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
- Knowledge Hub V1 targets `local_markdown`, `local_index`, and trusted remote adapters such as `http_json`; `pageindex` and `local_vector` are historical provider paths removed from active code.
- Dashboard and Chat SPAs exist; production Approval Console, RBAC, hosted compliance, and multi-agent management are future work.

## Source Of Truth

Read these before planning or changing behavior:

1. `CONTEXT-MAP.md` — domain-language routing map.
2. Relevant `docs/domain/*/CONTEXT.md` files — canonical domain language for the task area.
3. `CONTEXT.md` — product-wide terms.
4. `docs/README.md` — documentation routing.
5. `docs/technical-design.md` — authoritative architecture, module boundaries, contracts, provider strategy, error codes, trace events, and roadmap.
6. `docs/developer-guide.md` — user-facing Agent owner workflow, setup, configuration, deployment, and operations.
7. `docs/evaluation-system.md` — V1 Agent evaluation metrics, deterministic gates, judge diagnostics, suites, thresholds, curation, and artifacts.
8. `docs/development-progress.md` — current/historical implementation snapshot; useful but may be stale, so verify against code.
9. `docs/adr/` — architectural decision records.
10. `docs/concepts/` — normative concept contracts for Control Envelope, Agent Contract, Policy Engine, Approval State, Trace Events, Governance Receipt, and Trust Boundaries.

After editing domain documentation, run `python3 scripts/check-domain-contexts.py` and `git diff --check`.

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
uv run --extra dev proof-agent run examples/institution_insurance_specialist/agent.yaml --question "For short-term accident claims, what should a branch specialist explain to an agent when the claim is still pending?"
uv run --extra dev proof-agent compare examples/insurance_customer_service/agent.yaml --question "What discount should we give this customer next year?"
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
uv run --extra dashboard --extra ingestion --extra tree proof-agent dev
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

Default local backend startup is `proof-agent dev`, not `proof-agent server`.
It loads `.env` through the CLI callback, starts the API server on
`127.0.0.1:8000`, and starts the continuous Knowledge Worker against
`runs/config` so Dashboard Knowledge uploads are processed without a separate
worker terminal. On an empty local Configuration Store, it also imports and
publishes `examples/insurance_customer_service/agent.yaml` so Dashboard
configuration, `/operator`, and `/customer` have an immediate closed-loop Agent.
Run it with all backend extras:

```bash
uv run --extra dashboard --extra ingestion --extra tree proof-agent dev
```

Use `proof-agent server` only for targeted API-only debugging, and use
`proof-agent knowledge-worker --once` only for bounded worker tests or manual
queue drains.

To restart the local backend, Dashboard, and Chat surfaces on their expected ports:

```bash
# stop any existing listeners first
lsof -tiTCP:8000 -sTCP:LISTEN | xargs kill
lsof -tiTCP:5173 -sTCP:LISTEN | xargs kill
lsof -tiTCP:5174 -sTCP:LISTEN | xargs kill

# restart the local backend API and Knowledge Worker
uv run --extra dashboard --extra ingestion --extra tree proof-agent dev

# in a second terminal, restart the Dashboard
cd dashboard && npm run dev -- --host 127.0.0.1 --port 5173

# in a third terminal, restart the Unified Chat
cd chat && npm install && npm run dev -- --host 127.0.0.1 --port 5174
```

Expected local URLs after restart:

- API: `http://127.0.0.1:8000/api/health`
- Dashboard: `http://127.0.0.1:5173/`
- Chat: `http://127.0.0.1:5174/operator` or `http://127.0.0.1:5174/customer`

For a full frontend/backend verification session that should also be reachable
from the public internet, prefer the single command:

```bash
uv run --extra dashboard --extra ingestion --extra tree proof-agent verify-remote
```

`verify-remote` starts or restarts the backend API, continuous Knowledge Worker,
Dashboard, Unified Chat, a single local verification gateway, and by default a
`cloudflared` quick tunnel. It cleans the configured verification ports before
startup for Python/Node/Vite-style development processes, then exposes one local
gateway at `http://127.0.0.1:18080`: `/` for Dashboard, `/operator` and
`/customer` for Unified Chat, and `/api/*` for the backend API. Use
`--local-only` when external access is not needed, and `--no-cleanup` when
existing listeners must be preserved.

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

- The repo is an npm workspace (`package.json` `workspaces`: `packages/*`, `dashboard`, `chat`). Run installs from the repo root with `npm install`; do not pin `workspace:*` protocols (use `"*"` so npm links workspace packages).
- Dashboard and Chat use React 19, Vite, React Router, TypeScript, and Tailwind CSS v4.
- Both apps share a single design system package, `@proofagent/ui` (`packages/ui`): tokens, fonts, the locale engine (`createLocaleApi`), theme engine, `BrandMark`, and the full primitive catalog (Button, Input, Card, Badge, Avatar, Tabs, Dialog, Select, DropdownMenu, Tooltip, Table, Markdown, Toaster, plus domain-aligned OutcomeBadge/StatusDot/EmptyState). Extend the package rather than duplicating in an app. See `docs/frontend-design-principles.md` § "Shared Design System".
- Dashboard and Unified Chat frontend changes must follow `docs/frontend-design-principles.md` before implementation and during review.
- Keep frontend API types aligned with `proof_agent/contracts/` and API serializers.
- Preserve the product tone: operational, audit-focused, dense enough for repeated enterprise use.

Markdown:

- Use clear headings, short paragraphs, and tables only when they improve scanability.
- Keep terminology aligned with `CONTEXT.md`.
- Configuration examples should stay in YAML or JSON with descriptive file names, such as `examples/insurance_customer_service/agent.yaml` or `examples/institution_insurance_specialist/agent.yaml`.

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
