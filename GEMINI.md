# Proof Agent - Project Context for AI Agents

## Project Overview

Proof Agent is a **Controlled Agent Harness Framework** designed for enterprise environments. It wraps Agent execution (like RAG, model calls, and MCP tool usage) within a strict "Control Envelope." Rather than just orchestrating tasks, Proof Agent enforces policies at every step (e.g., mandatory retrieval, evidence quality checks, tool approval gates, memory boundaries), producing auditable JSONL traces and human-readable Governance Receipts.

**Main Technologies:**
- **Backend/Core:** Python 3.12+, Pydantic v2, Typer (CLI), FastAPI (Dashboard API), PyYAML. LangGraph and MCP are used but abstracted behind adapters.
- **Frontend Dashboard:** React 18, Vite, React Router DOM, Tailwind CSS (Vercel-style minimalist aesthetic).
- **Dependency Management:** `uv` for Python, `npm` for the frontend.

## Agent skills

### Issue tracker

GitHub Issues via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Standard triage vocabulary (`needs-triage`, `ready-for-agent`, etc.). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout at the repo root. See `docs/agents/domain.md`.

## Building and Running

### Python Environment (Core & API)
The project uses `uv` for fast dependency management.
*   **Install dependencies:** `uv pip install -e ".[dev,dashboard,openai,vector]"`
*   **Run Deterministic Demo:** `uv run --extra dev proof-agent demo` (Runs without API keys, generates traces in `runs/latest/`).
*   **Run a specific Agent:** `uv run --extra dev proof-agent run examples/enterprise_qa/agent.yaml`
*   **Start Dashboard API (Backend):** `uv run --extra dashboard proof-agent dashboard --host 127.0.0.1 --port 8000`
*   **Run with Docker:** `docker compose up`

### Testing and Validation
Always run the following commands to validate code changes:
*   **Unit Tests:** `uv run --extra dev python -m pytest tests/ -v`
*   **Linting (Ruff):** `uv run --extra dev ruff check proof_agent tests`
*   **Type Checking (Mypy):** `uv run --extra dev mypy proof_agent`

### Frontend Dashboard
*   **Install dependencies:** `cd dashboard && npm install`
*   **Start Dev Server:** `cd dashboard && npm run dev` (Connects to backend on port 8000).

## Development Conventions & Architecture Rules

**Bilingual documentation:** English docs live under `docs/` (default), Chinese translations under `docs/zh/` with the same directory structure. **Only update English docs during development; Chinese translations are synced at release time. Always reference English docs as the source of truth.**

1. **Authoritative Design:** Always refer to `docs/technical-design.md` as the source of truth for architectural decisions and module boundaries before planning code changes.
2. **Contract-First Design (`proof_agent/contracts/`):** Public boundaries use pure Pydantic v2 frozen models. **NEVER leak third-party SDK types** (like LangChain, LangGraph, MCP models, or provider clients) into public contracts, config, policy, or audit interfaces. Keep them hidden inside adapter layers (`proof_agent/runtime/`, `proof_agent/providers/`, `proof_agent/tools/`).
3. **Coding Style:** 
   - 4-space indentation.
   - `snake_case` for modules/functions/variables, `PascalCase` for classes.
   - Explicit type hints on all public APIs.
4. **Harness Semantics over Agent Logic:** Do not scatter governance logic inside workflow nodes. Instead, query the `PolicyEngine` at designated enforcement points (`before_retrieval`, `before_answer`, `before_tool_call`, etc.), and let it return typed decisions (`allow`, `deny`, `require_approval`, `escalate`).
5. **Dashboard Read-Only Principle:** The Dashboard API and UI exist strictly for **observability** of artifacts in `runs/latest/` (`trace.jsonl`, `governance_receipt.md`). They must not create a secondary execution path that bypasses the core Harness CLI/Workflow.
6. **Frontend Styling:** Adhere to a "Modern SaaS / Vercel" aesthetic—clean white/black backgrounds, 1px subtle borders, no drop shadows for flat cards, and sharp typography (`Geist`, `Inter`, `JetBrains Mono`). Default to Light Mode with Dark Mode support.