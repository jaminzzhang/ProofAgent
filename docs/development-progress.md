# Proof Agent Development Progress

> Last updated: 2026-05-20
> Purpose: Give AI coding agents a short, current map of the implementation. Verify all claims against the code before changing behavior.

## 1. Current Positioning

Proof Agent is a **Controlled Agent Harness Framework**. The core product is the Harness lifecycle: Agent Contract, Workflow, PolicyEngine, Tool Gateway, Memory Boundary, Validators, Trace, Governance Receipt, RunStore, and Dashboard API.

The project is no longer positioned as local-first or CLI-first. It keeps a deterministic local demo as the regression baseline, and supports CLI plus Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven extensions around the same Harness contract.

Authoritative design doc: `docs/technical-design.md`.

- LLM-backed ReAct planning and Harness review now use the shared Model Provider Registry with role-specific configuration, bounded JSON normalization, role-aware trace events, and fail-closed behavior for invalid model output.
- V1 Autonomous Customer Service Mode now adds customer contracts, Customer Run API, customer-safe response snapshots, read-only customer status tools, internal handoff events, handoff monitor API/UI, and the `insurance_customer_service` reference Agent.

## 2. Implementation Snapshot

| Area | Status |
| --- | --- |
| Contracts | Pydantic v2 frozen models for manifest, policy, ReAct action/review, evidence, approval, tools, model, trace, receipt, run, dashboard |
| Delivery | `delivery/cli.py` exposes Typer commands; `delivery/api.py` exposes Run Execution and Conversation APIs; `delivery/published_agents.py` maps Published Agent ids to approved manifests |
| Docker | `Dockerfile` and `docker-compose.yml` run deterministic demo |
| Bootstrap | `bootstrap/` owns YAML loader, path resolution, provider validation, retrieval config validation, secret-looking param rejection, and `HarnessInvocation` composition |
| Control | `control/` owns Enterprise QA and Controlled ReAct Enterprise QA workflow, policy, review fail-closed behavior, validators, evidence decisions, approval, and outcome behavior |
| Runtime | `runtime/langgraph_runner.py` executes supported LangGraph `StateGraph` templates with composed Harness dependencies |
| Capability | `capabilities/` owns model providers, ReAct planner, review subagent, knowledge provider registry, memory, ToolGateway, local tool handler loading, and future Skill packs |
| Audit | `observability/audit/` owns JSONL trace, ReAct review/reasoning projections, redaction, Governance Receipt, model usage section |
| Storage / API | `observability/storage/` owns RunStore and ConversationStore; `observability/api/` owns read-only dashboard routes; Run Execution API starts governed runs and persists them through RunStore |
| Customer Service | `delivery/customer_api.py`, `delivery/customer_adapters.py`, `observability/storage/customer_store.py`, `observability/api/routers/handoffs.py`, `chat/` customer mode, and `examples/insurance_customer_service/` implement V1 customer-facing automatic replies with the insurance-specific Demo behind a Customer Run Adapter |
| Evaluation | `evaluation/` owns deterministic demo helpers and Plain RAG vs Harness RAG comparison |
| Tests | 36 test files and 164 statically detected `test_` functions at last scan |

## 3. Stable Demo Contract

The deterministic demo must remain runnable without network access, API keys, or remote provider SDK configuration.

Expected outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

ReAct demo expected outcomes:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
clarify: WAITING_FOR_USER_CLARIFICATION
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
| LangGraph runtime | Enterprise QA `StateGraph` runs through composed Harness dependencies | Checkpoint interrupt/resume and streaming hooks |
| Controlled ReAct | `react_enterprise_qa` runs deterministic planner/review scenarios with fixed action set, advisory review, clarification wait, approval wait, trace, and receipt output | Production-grade checkpoint resume, streaming, and remote planner/review adapters |
| LangChain integration | Not a public adapter yet | Optional ecosystem adapter that preserves contracts |
| Real MCP | Mock tool proves approval contract | stdio/HTTP MCP adapter behind ToolGateway |
| Vector provider | Local Vector provider queries existing Chroma indexes | Index build lifecycle and broader vector store adapters |
| Agentic RAG | PageIndex provider path emits governed retrieval plan/step events and evaluates evidence locally | Planner-driven multi-step retrieval strategy beyond provider-agentic retrieval |
| Dashboard UI | Implemented for overview, runs, run detail, evidence, receipt, model usage, approvals, timeline, and governed ReAct details; SPA mount supported if built assets exist | Approval Console actions and richer filtering |
| Handoff Monitor | Implemented as read-only internal projection of customer handoff trace events | Filtering and richer run correlation |
| Unified Chat UI | Implemented under `chat/` with `/operator` and `/customer` modes, Conversation API integration, governed ReAct detail display, and customer-safe API responses | Polish, multi-agent selection, production auth, and deployment packaging |
| Azure/Anthropic | Placeholder providers | Real provider adapters with mocked tests |
| Streaming | Not implemented | Trace-safe streaming chunks |

## 5. Verification Commands

For runtime changes:

```bash
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev mypy proof_agent
uv run --extra dev proof-agent demo
uv run --extra dev --extra dashboard proof-agent react-demo
```

For documentation-only edits:

```bash
git diff --check
```

## 6. AI Session Guidance

1. Start with `docs/README.md` for document routing.
2. Use `docs/technical-design.md` as the architectural source of truth.
3. Preserve the deterministic demo while adding remote/provider/platform integrations.
4. Keep third-party SDK types out of contracts, policy, trace, receipt, bootstrap, and dashboard contracts.
