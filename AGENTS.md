# Repository Guidelines

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard triage vocabulary (`needs-triage`, `ready-for-agent`, etc.). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout at the repo root. See `docs/agents/domain.md`.

## Current Status

This repository is no longer documentation-only. The current `main` branch contains a Python MVP for Proof Agent as a Controlled Agent Harness Framework. It includes typed contracts, policy enforcement, deterministic enterprise Q&A examples, remote model provider boundaries, tool approval gating, trace/audit output, comparison utilities, Dashboard API, tests, CI, and Docker assets.

The deterministic demo currently reports:

- `supported`: `ANSWERED_WITH_CITATIONS`
- `unsupported`: `REFUSED_NO_EVIDENCE`
- `tool_required`: `WAITING_FOR_APPROVAL`

Demo artifacts are written to `runs/latest/trace.jsonl` and `runs/latest/governance_receipt.md`. Generated run output is ignored by git except for `runs/.gitkeep`.

## Project Structure & Module Organization

Primary implementation and planning areas:

- `proof_agent/` is organized by architecture layer: `bootstrap/`, `control/`, `runtime/`, `capabilities/`, `observability/`, `delivery/`, `evaluation/`, and `contracts/`.
- `proof_agent/bootstrap/` owns `agent.yaml` loading, config validation, path resolution, and composition boundaries.
- `proof_agent/control/` owns Workflow, Orchestrator, PolicyEngine, Validators, approval semantics, memory policy checks, and outcome behavior.
- `proof_agent/runtime/` owns LangGraph/LangChain runtime adapter boundaries. Runtime mechanics must not redefine Control Plane semantics.
- `proof_agent/capabilities/` owns concrete abilities: model providers, knowledge/retrieval, memory, Tool/MCP adapters, and future Skill packs.
- `proof_agent/observability/` owns audit trace, redaction, Governance Receipt, RunStore, and Dashboard read API.
- `proof_agent/delivery/` owns CLI and future execution entry points. `proof_agent/cli.py` is a compatibility shim.
- `proof_agent/evaluation/` owns deterministic demo helpers and Plain RAG vs Harness RAG comparison.
- `proof_agent/contracts/` owns public Pydantic v2 contract models and provider-neutral ports. Keep framework/provider-specific objects out of this layer.
- `tests/` contains the pytest suite for bootstrap/config loading, contracts, policy, knowledge retrieval, tool approval, memory, audit output, compare, workflow, and CLI behavior.
- `examples/enterprise_qa/` contains the runnable Enterprise QA Template, including `agent.yaml`, knowledge fixtures, tools, and prompt templates.
- `docs/` contains product, architecture, concept, and example documentation.
- `runs/` is the local audit output directory; only `runs/.gitkeep` should be committed.
- Operational assets live at the repository root, including `Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, and `.github/workflows/ci.yml`.

Important documentation:

- `docs/Proof Agent PRD.md` defines MVP scope, modules, architecture, and delivery milestones.
- `docs/Proof Agent 可行性分析报告.md` captures feasibility, audience, stack options, and risks.
- **`docs/Proof Agent 技术设计方案.md` is the authoritative technical design document. It defines design principles, architecture decisions, module boundaries, contract shapes, provider strategy, error codes, trace events, and the implementation roadmap. When writing implementation plans, designing features, or writing code, always read and follow this document first.**
- **`docs/developer-guide.md` explains the AI Agent owner workflow: Quick Start, Agent package structure, configuration, development, deployment, and operations. Use it when changing user-facing setup or developer experience.**
- **`docs/development-progress.md` records historical development status — module status, test coverage, and implementation roadmap as of the last update date shown in the file. It is a useful reference but may be stale. Always verify claims against the actual codebase before trusting them.**
- `docs/concepts/` explains framework concepts such as Control Envelope, Agent Contract, and Policy Engine.
- `docs/examples/` documents the enterprise Q&A demo, launch script, and Governance Receipt.

## Build, Test, and Development Commands

Use `uv` for local development:

- `uv run --extra dev python -m pytest tests/ -v` runs the full test suite.
- `uv run --extra dev ruff check proof_agent tests` runs lint checks.
- `uv run --extra dev mypy proof_agent` runs static type checks.
- `uv run --extra dev proof-agent demo` runs the deterministic three-scenario demo.
- `uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml` runs the Enterprise QA Template directly.
- `uv run --extra dev proof-agent compare examples/enterprise_qa/agent.yaml --question "What discount should we give this customer next year?"` compares baseline and governed behavior.
- `uv run --extra dev proof-agent inspect runs/latest/governance_receipt.md` inspects the latest receipt.
- `docker compose up` runs the local containerized demo path.

For documentation-only edits, at minimum run `git diff --check`. For runtime changes, run pytest, Ruff, mypy, and at least one CLI demo path.

## Coding Style & Naming Conventions

Use clear Markdown headings, short paragraphs, and tables only when they improve scanability. Keep project terminology consistent: `Controlled Agent Harness Framework`, `Control Envelope`, `Agent Contract`, `PolicyEngine`, `Tool Gateway`, `MCP approval`, `Trace & Audit`, `Governance Receipt`, and `Enterprise QA Template`.

For Python code, use 4-space indentation, snake_case modules and functions, PascalCase classes, and explicit type hints on public APIs. Prefer small, typed functions and keep side effects behind adapters or CLI entry points.

The runtime uses Python 3.12+, Pydantic v2 frozen contracts, Typer for the CLI, PyYAML for configuration, Jinja2 for receipt rendering, and pytest/Ruff/mypy for verification. Keep LangGraph, Chroma, MCP, and provider-specific details behind adapters; do not leak those types into contracts, bootstrap, control, trace, receipt, or Dashboard contracts.

Configuration examples should stay in YAML or JSON with descriptive file names, such as `examples/enterprise_qa/agent.yaml`.

## Testing Guidelines

Tests live under `tests/` and should be named `test_<module>.py`. Keep coverage focused on externally visible behavior and contracts:

- workflow routing and refusal behavior
- evidence-backed answer generation
- memory read/write behavior
- MCP mock tool registration and approval gating
- policy decisions and redaction
- trace/audit event output
- Governance Receipt rendering
- baseline-vs-governed comparison
- CLI command behavior

Documentation edits should still verify links, headings, tables, and code blocks render correctly.

## Commit & Pull Request Guidelines

Use concise, imperative commit subjects such as `Add MVP architecture notes` or `Document receipt contract`.

Pull requests should include a short summary, changed files or sections, validation performed, and any unresolved product or architecture questions. For UI or diagram changes, attach screenshots or rendered previews when available.

## Security & Configuration Tips

Do not commit API keys, model provider credentials, vector database secrets, or production connection strings. Use `.env.example` for required variables and keep real secrets in local environment files excluded by `.gitignore`.

The deterministic demo path must remain runnable without external API keys. Generated artifacts under `runs/latest/` should not be committed. Current redaction coverage includes API keys, access tokens, bearer tokens, passwords, secrets, connection strings, customer phone values, and provider API keys.
