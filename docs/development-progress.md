# Proof Agent Development Progress

> Last updated: 2026-05-11
> Purpose: Give AI coding agents a short, current map of the implementation. Verify all claims against the code before changing behavior.

## 1. Current Positioning

Proof Agent is a **Controlled Agent Harness Framework**. The core product is the Harness lifecycle: Agent Contract, Workflow, PolicyEngine, Tool Gateway, Memory Boundary, Validators, Trace, Governance Receipt, RunStore, and Dashboard API.

The project is no longer positioned as local-first or CLI-first. It keeps a deterministic local demo as the regression baseline, and supports CLI plus Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven extensions around the same Harness contract.

Authoritative design doc: `docs/Proof Agent 技术设计方案.md`.

## 2. Implementation Snapshot

| Area | Status |
| --- | --- |
| Contracts | Pydantic v2 frozen models for manifest, policy, evidence, approval, tools, model, trace, receipt, run, dashboard |
| CLI | Typer commands: `demo`, `run`, `doctor`, `inspect`, `compare`, `dashboard` |
| Docker | `Dockerfile` and `docker-compose.yml` run deterministic demo |
| Config | YAML loader, path resolution, provider validation, secret-looking model param rejection |
| Workflow | Enterprise QA orchestrator with policy, evidence, model, tool, memory, validators, trace, receipt |
| Runtime | `runtime/langgraph_runner.py` is an adapter boundary; current flow delegates to plain Python orchestrator |
| Policy | Enforcement points include retrieval, answer, tool call, memory write, model call |
| Knowledge | Deterministic markdown retrieval; vector adapter lives behind optional `[vector]` dependency |
| Model Providers | `deterministic` and `openai_compatible` implemented; Azure and Anthropic placeholders fail clearly |
| Tools / MCP | ToolGateway, approval state, mock `customer_lookup`; real MCP transport is adapter work |
| Memory | Session memory with denylist and policy gate |
| Validators | schema, evidence, safety, citations, tool result |
| Audit | JSONL trace, redaction, Governance Receipt, model usage section |
| Storage / API | RunStore, history/latest compatibility, FastAPI dashboard routes for health/runs/stats |
| Tests | 28 test files and 91 statically detected `test_` functions at last scan |

## 3. Stable Demo Contract

The deterministic demo must remain runnable without network access, API keys, or remote provider SDK configuration.

Expected outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

Artifacts:

```text
runs/latest/trace.jsonl
runs/latest/governance_receipt.md
```

## 4. Current Gaps

| Gap | Current State | Intended Direction |
| --- | --- | --- |
| LangGraph runtime | Adapter stub delegates to orchestrator | Real StateGraph, checkpoint, interrupt |
| LangChain integration | Not a public adapter yet | Optional ecosystem adapter that preserves contracts |
| Real MCP | Mock tool proves approval contract | stdio/HTTP MCP adapter behind ToolGateway |
| Vector provider | Optional Chroma adapter scaffold | Formal vector provider contract and tests |
| Dashboard UI | FastAPI API exists; SPA mount supported if built assets exist | Dashboard UI and Approval Console |
| Azure/Anthropic | Placeholder providers | Real provider adapters with mocked tests |
| Streaming | Not implemented | Trace-safe streaming chunks |

## 5. Verification Commands

For runtime changes:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
uv run --extra dev proof-agent demo
```

For documentation-only edits:

```bash
git diff --check
```

## 6. AI Session Guidance

1. Start with `docs/README.md` for document routing.
2. Use `docs/Proof Agent 技术设计方案.md` as the architectural source of truth.
3. Preserve the deterministic demo while adding remote/provider/platform integrations.
4. Keep third-party SDK types out of contracts, policy, trace, receipt, config, and dashboard contracts.
