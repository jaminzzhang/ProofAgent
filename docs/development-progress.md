# Proof Agent Development Progress

> Last updated: 2026-06-04
> Purpose: Give AI coding agents a short, current map of the implementation. Verify all claims against the code before changing behavior.

## 1. Current Positioning

Proof Agent is a **Controlled Agent Harness Framework**. The core product is the Harness lifecycle: Agent Contract, Workflow, PolicyEngine, Tool Gateway, Memory Boundary, Validators, Trace, Governance Receipt, RunStore, and Dashboard API.

The project is no longer positioned as local-first or CLI-first. It keeps a deterministic local demo as the regression baseline, and supports CLI plus Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven extensions around the same Harness contract.

Authoritative design doc: `docs/technical-design.md`.

- LLM-backed ReAct planning and Harness review now use the shared Model Provider Registry with role-specific configuration, bounded JSON normalization, role-aware trace events, and fail-closed behavior for invalid model output.
- V1 Autonomous Customer Service Mode now adds customer contracts, Customer Run API, customer-safe response snapshots, read-only customer status tools, internal handoff events, handoff monitor API/UI, and the `insurance_customer_service` reference Agent.
- Dashboard-hosted Agent Configuration now adds Draft Agents, Contract Bundles,
  validation runs, Published Agent Versions, rollback, Run Purpose metadata, and
  an Agents workspace in the Dashboard shell.
- Local Index ingestion now adds quarantined single-file and atomic batch upload staging,
  asynchronous Markdown and text-based PDF validation, immutable revision artifact construction,
  persisted bounded retries, Source claim concurrency, status APIs, continuous `knowledge-worker`
  polling, and bounded `knowledge-worker --once` CLI execution. The
  snapshot-freeze foundation now derives candidate snapshots, persists foundation validation,
  freezes immutable `local_index.snapshot.v2` manifests, and advances `latest_snapshot_id`. Source
  publication now validates smoke retrieval, publishes the vetted local snapshot or `http_json`
  `remote_config` into the legacy `published_snapshot_id` resource pointer, rejects unpublished
  shared Source binding, and persists resolved Knowledge Binding Sets on Published Agent Versions.
  The registered Local Index runtime now
  consumes `snapshot.v2`, performs bounded metadata-first document routing, loads only selected
  immutable revision artifacts, fails closed on selected-document errors, and emits trace-safe
  routing summaries through the shared Control Plane retrieval service.

## 2. Implementation Snapshot

| Area | Status |
| --- | --- |
| Contracts | Pydantic v2 frozen models for manifest, policy, ReAct action/review, evidence, approval, tools, model, trace, receipt, run, dashboard, and Agent Configuration |
| Delivery | `delivery/cli.py` exposes Typer commands including continuous `knowledge-worker` and bounded `knowledge-worker --once`; `delivery/api.py` exposes Run Execution and Conversation APIs; `delivery/configuration_api.py` exposes Agent Configuration workflows plus Local Index quarantine, ingestion-job status, derived candidate validation, and frozen snapshot management; `delivery/published_agents.py` resolves static Published Agents and Active Agent Versions |
| Docker | `Dockerfile` and `docker-compose.yml` run deterministic demo |
| Bootstrap | `bootstrap/` owns YAML loader, path resolution, provider validation, retrieval config validation, secret-looking param rejection, and `HarnessInvocation` composition |
| Control | `control/` owns Enterprise QA and Controlled ReAct Enterprise QA workflow, policy, review fail-closed behavior, validators, evidence decisions, approval, and outcome behavior |
| Runtime | `runtime/langgraph_runner.py` executes supported LangGraph `StateGraph` templates with composed Harness dependencies |
| Capability | `capabilities/` owns model providers, ReAct planner, review subagent, knowledge provider registry, memory, ToolGateway, local tool handler loading, and future Skill packs |
| Audit | `observability/audit/` owns JSONL trace, ReAct review/reasoning projections, redaction, Governance Receipt, model usage section |
| Storage / API | `observability/storage/` owns RunStore and ConversationStore; `configuration/local_store.py` owns local Agent Configuration state; `observability/api/` owns read-only dashboard routes; Run Execution API starts governed production runs and Agent Configuration API starts governed validation runs through RunStore |
| Customer Service | `delivery/customer_api.py`, `delivery/customer_adapters.py`, `observability/storage/customer_store.py`, `observability/api/routers/handoffs.py`, `chat/` customer mode, and `examples/insurance_customer_service/` implement V1 customer-facing automatic replies with the insurance-specific Demo behind a Customer Run Adapter |
| Evaluation | `evaluation/` owns deterministic demo helpers and Plain RAG vs Harness RAG comparison |
| Tests | 70 test files and 595 statically detected `test_` functions at last scan |

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
| Knowledge Hub provider set | Active code accepts `local_markdown`, `local_index`, trusted `http_json`, and the fixture `remote_search` adapter; `pageindex` and `local_vector` are rejected; Agent Contracts use explicit `package_knowledge_sources[]` plus `knowledge_bindings[].source_ref`; `http_json` has a default Remote Retrieval Protocol, bounded whole-value request mapping, JSON Pointer response mapping, env-referenced headers, and fail-closed normalization into Candidate Evidence; `local_index` registered runtime config is v2-only and resolves explicit `snapshot_path + artifact_root`, validates immutable manifests before storage access, projects bounded trace-safe metadata, sends at most `100` candidates to the Source-owned routing model through Control Plane `before_model_call` policy and safe tracing, loads only selected revision artifacts read-only, and fails closed without partial evidence when selected-document retrieval fails; the ingestion foundation stages quarantined single-file uploads and atomic batches, asynchronously validates Markdown and text-based PDF, promotes accepted document revisions, builds immutable revision artifacts, persists bounded retries, and exposes continuous worker polling, bounded one-shot execution, plus status APIs; Dashboard/API operators can edit allowlisted per-document routing metadata, advancing the Source Draft token and candidate digest without reingestion; the snapshot-freeze and publication loop derives READY candidate projections, persists foundation validation, freezes immutable `local_index.snapshot.v2` manifests, validates Source-level smoke retrieval, publishes vetted local snapshots, validates `http_json` smoke retrieval, publishes remote configuration versions with explicit `resource_kind: remote_config`, rejects unpublished shared Source binding, and persists resolved Knowledge Binding Sets on Published Agent Versions; Enterprise QA and Controlled ReAct enter retrieval through the shared Control Plane Knowledge Retrieval Service; blended single-step, reviewed/fallback, and planner/evaluator-backed agentic retrieval use deterministic binding metadata routing, record provider calls, apply binding failure modes, exact deduplication, WRRF ordering, no-evidence reason codes, and allowlisted one-shot Local Index document-routing summaries | Add richer remote retrieval preview/health-check UX and hierarchical routing beyond the first `100` document candidates |
| Agentic RAG | Agentic retrieval strategy emits governed retrieval plan/step events through the shared Knowledge Retrieval Service and falls back through registered Knowledge Providers when planner/evaluator models are absent; when planner/evaluator models are configured, each rewritten query re-enters service-owned bounded source routing and records round-correlated provider summaries, including Local Index `document_candidates[]` and `selected_documents[]`; Controlled ReAct submits reviewed Retrieval Intent without directly calling providers | Richer trace-safe plan summaries and nested retrieval budget projections |
| Dashboard UI | Implemented for overview, runs, run detail, evidence, receipt, model usage, approvals, timeline, governed ReAct details, handoffs, Knowledge Hub Source creation/detail/publication, and the Agents configuration workspace with Workflow node editing, published Source binding, validation, publish, and rollback | Approval Console actions, RBAC, and richer multi-agent operations |
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
