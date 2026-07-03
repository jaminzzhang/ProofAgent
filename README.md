# Proof Agent

> Controlled Agent Harness Framework for governed, auditable enterprise AI Agents.

Proof Agent wraps Agent execution in a **Control Envelope**: workflow
orchestration, policy gates, evidence admission, model-provider governance, tool
approval, memory boundaries, validators, JSONL trace, Dashboard APIs, and a
human-readable Governance Receipt.

It is designed for teams that need to explain why an Agent answered, refused,
asked for clarification, or paused for approval. The project keeps a
no-network, no-API-key deterministic demo as its regression baseline, while
supporting adapter-driven model, retrieval, tool, Dashboard, and chat surfaces.

## Table of Contents

- [Why Proof Agent](#why-proof-agent)
- [What It Provides](#what-it-provides)
- [Current Status](#current-status)
- [Architecture](#architecture)
- [Repository Layout](#repository-layout)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [Run Example Agent Packages](#run-example-agent-packages)
- [Local Backend and Frontends](#local-backend-and-frontends)
- [Agent Package Format](#agent-package-format)
- [Configuration and Credentials](#configuration-and-credentials)
- [Development](#development)
- [Documentation](#documentation)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Why Proof Agent

Most Agent and RAG demos show that a model can produce an answer. Proof Agent is
about whether an enterprise Agent is allowed to act:

- Was retrieval required before answering?
- Was the evidence strong enough?
- Were citations enforced?
- Did a tool call require approval?
- Was memory allowed to store the proposed fact?
- Which validators accepted or blocked the output?
- What does the audit record prove after the run?

Proof Agent does not replace LangGraph, MCP, vector stores, model providers, or
observability tools. It composes them behind a contract-first Harness so runtime
mechanics cannot bypass governance semantics.

## What It Provides

- **Agent Contract**: `agent.yaml` declares workflow, model, knowledge, policy,
  tools, memory, and audit behavior.
- **Control Plane**: workflow templates, `PolicyEngine`, approval semantics,
  evidence admission, validators, memory checks, and outcome mapping.
- **Tool Gateway**: governed tool proposal, approval, execution, summarization,
  and trace projection.
- **Knowledge and evidence**: local Markdown, local index, and trusted remote
  adapter paths behind Proof Agent contracts.
- **Model boundaries**: deterministic provider plus OpenAI-compatible provider
  paths and clean-failure placeholders for future providers.
- **Trace and receipt**: JSONL trace as the execution source of truth, with a
  readable Governance Receipt projection for review.
- **Application surfaces**: CLI, Docker entry point, Dashboard API, Dashboard
  SPA, and Unified Chat SPA for operator and customer modes.
- **Evaluation utilities**: deterministic demos, Plain RAG vs Harness RAG
  comparison, suites, campaigns, and post-run analysis artifacts.

## Current Status

Proof Agent is an active Python MVP with frontend application surfaces.

Implemented paths include:

- Python package and CLI for deterministic demos, governed Agent package runs,
  inspection, comparison, evaluation, local API serving, and knowledge worker
  execution.
- Public example Agent packages under `examples/insurance_customer_service/`
  and `examples/institution_insurance_specialist/`.
- Dashboard frontend under `dashboard/` for run history, run detail, evidence,
  approvals, receipts, model usage, configuration, knowledge, and evaluation
  workflows.
- Unified Chat frontend under `chat/` with operator-facing Assisted QA Chat and
  customer-facing Customer Service Chat modes.
- CI for pytest, Ruff, mypy, and CLI smoke coverage.
- Docker assets for running the deterministic demo.

Current extension areas include production RBAC, richer hosted operations, real
MCP stdio/HTTP transport, streaming hooks, additional provider adapters, and
more production-grade deployment packaging.

## Architecture

Proof Agent is organized around a governed Agent lifecycle:

```text
Delivery / Entry
  -> Bootstrap / Composition
  -> Control Plane
  -> Runtime Plane
  -> Capability Layer
  -> Infrastructure

Contracts & Ports define the shared language.
Audit & Observability records execution facts as a side channel.
```

Current package execution follows this shape:

```text
CLI / API / Docker
  -> load and validate agent.yaml
  -> compose Harness dependencies
  -> run the selected governed workflow template
  -> apply policy, evidence, tool, memory, and validator decisions
  -> write trace and run metadata
  -> render Governance Receipt
  -> expose Dashboard and inspection projections
```

The Control Plane owns decisions. Runtime and capability adapters can execute
mechanics, call providers, or load integrations, but they must not redefine
policy, evidence, approval, memory, outcome, trace, or receipt semantics.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `proof_agent/bootstrap/` | Agent Contract loading, validation, path resolution, and Harness composition |
| `proof_agent/contracts/` | Provider-neutral Pydantic v2 contracts and ports |
| `proof_agent/control/` | Workflow orchestration, policy, validators, approval, evidence, memory, and governed outcomes |
| `proof_agent/runtime/` | Runtime adapter boundaries for historical and future runtime mechanics |
| `proof_agent/capabilities/` | Model, knowledge, memory, tool, MCP, ReAct planner, and review adapters |
| `proof_agent/observability/` | Trace, redaction, Governance Receipt, RunStore, ConversationStore, and read APIs |
| `proof_agent/delivery/` | CLI, Run Execution API, Conversation API, Configuration API, and customer API |
| `proof_agent/evaluation/` | Deterministic demos, comparison helpers, suites, campaigns, and analysis |
| `examples/` | Runnable public Agent packages |
| `dashboard/` | Vite/React Dashboard SPA |
| `chat/` | Vite/React Unified Chat SPA |
| `packages/ui/` | Shared React design system package |
| `docs/` | Product, architecture, concept, evaluation, frontend, ADR, and example docs |
| `tests/` | Pytest coverage for contracts, control, APIs, adapters, examples, and evaluation |
| `runs/` | Generated local audit output; only `runs/.gitkeep` is committed |

## Requirements

- Python 3.12+
- `uv` for Python dependency management and command execution
- Node.js and npm for the Dashboard, Chat, and shared UI package
- Docker and Docker Compose for the optional container demo

The deterministic demo does not require API keys, network model calls, vector
databases, or external services.

## Quick Start

From the repository root:

```bash
uv run --extra dev proof-agent demo
```

Expected deterministic outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
tool_required: WAITING_FOR_APPROVAL
```

The run writes:

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

Inspect the latest artifacts:

```bash
uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md
uv run --extra dev proof-agent inspect runs/latest/trace.jsonl
```

## Run Example Agent Packages

Run the customer-facing Insurance Customer Service Agent:

```bash
uv run --extra dev proof-agent run examples/insurance_customer_service/agent.yaml \
  --question "What documents are required for inpatient claim reimbursement?"
```

Run the staff-facing Institution Insurance Specialist Agent:

```bash
uv run --extra dev proof-agent run examples/institution_insurance_specialist/agent.yaml \
  --question "For short-term accident claims, what should a branch specialist explain to an agent when the claim is still pending?"
```

Compare Plain RAG with Harness RAG on an unsupported question:

```bash
uv run --extra dev proof-agent compare examples/insurance_customer_service/agent.yaml \
  --question "What discount should we give this customer next year?"
```

Run the Docker demo:

```bash
docker compose up
```

## Local Backend and Frontends

Start the local backend API plus the continuous Knowledge Worker:

```bash
uv run --extra dashboard --extra ingestion --extra tree proof-agent dev
```

The backend defaults to `http://127.0.0.1:8000` and seeds the canonical
`insurance_customer_service` Agent into an empty local configuration store.

Install frontend dependencies from the repository root:

```bash
npm install
```

Start the Dashboard:

```bash
npm run dev -w proof-agent-dashboard -- --host 127.0.0.1 --port 5173
```

Start Unified Chat:

```bash
npm run dev -w proof-agent-chat -- --host 127.0.0.1 --port 5174
```

Useful local URLs:

- API health: `http://127.0.0.1:8000/api/health`
- Dashboard: `http://127.0.0.1:5173/`
- Operator chat: `http://127.0.0.1:5174/operator`
- Customer chat: `http://127.0.0.1:5174/customer`

## Agent Package Format

The developer-facing unit is an Agent package:

```text
agent.yaml      # Agent Contract
policy.yaml     # Control Plane policy
tools.yaml      # Tool / MCP declarations
knowledge/      # Package-local knowledge sources
questions.yaml  # Optional evaluation questions
expected/       # Optional expected trace or receipt examples
```

`agent.yaml` can declare provider names, model names, environment variable
names, timeouts, token limits, retrieval settings, capability files, and audit
paths. It must not contain raw secrets.

Minimal development loop:

```text
create or copy an Agent package
  -> configure agent.yaml, policy.yaml, tools.yaml, and knowledge
  -> run deterministic validation
  -> inspect trace and Governance Receipt
  -> compare Plain RAG vs Harness RAG on unsupported questions
  -> optionally switch to a remote model or shared model connection
  -> operate through CLI, APIs, Dashboard, Chat, trace, and receipt
```

## Configuration and Credentials

Copy `.env.example` to `.env` for optional provider credentials:

```bash
cp .env.example .env
```

The default deterministic path does not require credentials. Optional provider
paths use environment variables such as:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_COMPATIBLE_API_KEY`
- `OPENAI_COMPATIBLE_BASE_URL`
- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `PA_KNOWLEDGE_TOKEN`

Keep real secrets in ignored local environment files or deployment secret
stores. Do not commit secrets in Agent packages, traces, receipts, fixtures, or
documentation.

## Development

Python checks:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai mypy proof_agent
uv run --extra dev proof-agent demo
```

Frontend checks:

```bash
npm install
npm run build
npm test
```

Documentation-only check:

```bash
python3 scripts/check-domain-contexts.py
git diff --check
```

CI runs pytest, Ruff, mypy, and a CLI smoke test that verifies the generated
trace and Governance Receipt.

## Documentation

Start here:

- [Documentation Index](docs/README.md)
- [Developer Guide](docs/developer-guide.md)
- [Technical Design](docs/technical-design.md)
- [Product Requirements](docs/prd.md)
- [Evaluation System](docs/evaluation-system.md)
- [Evaluation Campaign System](docs/evaluation-campaign-system.md)
- [Frontend Design Principles](docs/frontend-design-principles.md)

Core concept contracts:

- [Control Envelope](docs/concepts/control-envelope.md)
- [Agent Contract](docs/concepts/agent-contract.md)
- [Policy Engine](docs/concepts/policy-engine.md)
- [Approval State Contract](docs/concepts/approval-state-contract.md)
- [Trace Event Contract](docs/concepts/trace-event-contract.md)
- [Governance Receipt Contract](docs/concepts/governance-receipt-contract.md)
- [Trust Boundaries](docs/concepts/trust-boundaries.md)

Example docs:

- [Insurance Customer Service Agent](docs/examples/insurance-customer-service.md)
- [Institution Insurance Specialist Agent](docs/examples/institution-insurance-specialist.md)
- [Launch Script](docs/examples/launch-script.md)
- [Governance Receipt Example](docs/examples/governance-receipt.md)

Docs are bilingual: English docs live under `docs/`, and Chinese translations
live under `docs/zh/`. During development, update English docs first; Chinese
translations are synced at release time.

## Contributing

Contributions should preserve the Harness boundaries:

- Keep public contracts provider-neutral.
- Keep Control Plane decisions out of runtime and capability adapters.
- Keep trace and receipt output audit-safe and redacted.
- Keep deterministic demos runnable without network access, API keys, or
  external services.
- Add or update tests for externally visible behavior.
- For documentation changes, keep terminology aligned with `CONTEXT.md`,
  `CONTEXT-MAP.md`, and the relevant `docs/domain/*/CONTEXT.md` file.

Before opening a pull request, run the smallest relevant verification set from
[Development](#development).

## Security

- Do not commit API keys, bearer tokens, passwords, connection strings, provider
  secrets, or production URLs containing secrets.
- Use environment variable references in Agent packages instead of raw secret
  values.
- Treat generated traces and receipts as audit artifacts. They are ignored by
  git under `runs/`, except for `runs/.gitkeep`.
- If you need to report a vulnerability and no private channel is available,
  open a minimal public issue requesting a private disclosure path. Do not put
  exploit details or secrets in the issue.

## License

Proof Agent is licensed under the [Apache License 2.0](LICENSE).
