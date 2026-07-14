# Proof Agent Development Progress

> Last updated: 2026-06-26
> Purpose: Give AI coding agents a short, current map of the implementation. Verify all claims against the code before changing behavior.

## 1. Current Positioning

Proof Agent is a **Controlled Agent Harness Framework**. The core product is the Harness lifecycle: Agent Contract, Workflow, PolicyEngine, Tool Gateway, Memory Boundary, Validators, Trace, Governance Receipt, RunStore, and Dashboard API.

The project is no longer positioned as local-first or CLI-first. It keeps a deterministic local React Enterprise QA demo as the regression baseline, and supports CLI plus Docker entry points. Remote models, LangChain/LangGraph, vector stores, real MCP, and Dashboard capabilities are adapter-driven extensions around the same Harness contract.

Authoritative design doc: `docs/technical-design.md`.

- LLM-backed ReAct planning and Harness review now use the shared Model Provider Registry with role-specific configuration, bounded JSON normalization, role-aware trace events, and fail-closed behavior for invalid model output.
- V1 Autonomous Customer Service Mode now adds customer contracts, Customer Run API, customer-safe response snapshots, read-only customer status tools, internal handoff events, handoff monitor API/UI, and the `insurance_customer_service` reference Agent.
- Dashboard-hosted Agent Configuration now adds Draft Agents, Contract Bundles,
  validation runs, Published Agent Versions, rollback, Run Purpose metadata, and
  an Agents workspace in the Dashboard shell.
- Workflow Stage Prompt Configuration now adds backend-owned Workflow Template
  Descriptors, governed `workflow.stages[]` Prompt/context config for ReAct
  templates including `react_enterprise_qa_v3`, redacted stage context preview, Dashboard relationship-map
  plus Stage Inspector editing, validation/publish gating, and runtime Business Context Addendum injection
  with trace-safe `workflow_stage_context_applied` events. Harness-owned prompts remain
  locked and stage Prompt text is never stored in trace; validation-only full capture
  uses Sensitive Validation Capture Artifacts gated by `agent.validate`.
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
- Knowledge Source lifecycle management now requires `ACTIVE` or `ARCHIVED` state, treats Archive
  as the default delete-like action, blocks archived Source mutation and new/shared Agent binding,
  keeps Published Agent Versions pinned to resolved bindings, exposes deletion eligibility, and
  permits physical deletion only for empty archived Sources after writing global configuration audit.
- Dashboard Configuration now includes Models for Shared Model Connections. Agents and Local Index
  Knowledge Sources can select shared connections or custom model config; connection-level
  provider/model/base URL/credential env/default timeout are shared, while role and Source usage
  params such as temperature, output tokens, retrieval budgets, and document routing settings remain
  local. Runtime emits trace-safe model connection resolution records.
- React Enterprise QA V3 is now the product main path. `workflow.template:
  react_enterprise_qa_v3` with `workflow.runtime: controlled_react` enters
  `delivery/agent_package_execution.py`, composes a `HarnessInvocation`, builds
  `control/workflow/controlled_react/ControlledReActOrchestrator`, emits
  `runtime: controlled_react_orchestrator` trace projection, and finalizes the
  run through the same receipt and RunStore path as other governed runs.
- V3 approval pause/resume now uses `ControlledReActRunStateSnapshot` through
  the Orchestrator snapshot store. Approval-granted resume observes the tool
  and continues through the Orchestrator; approval denial records the governed
  denied outcome. Non-V3 LangGraph checkpoint resume remains a historical
  runtime path, not the V3 product semantics.

## 2. Implementation Snapshot

### Phase F Hybrid Knowledge production closure (2026-07-14)

- [COMPUTED | HIGH] Shadow suite schema v2 contains no observations or pointer snapshots;
  trusted live drivers execute both pinned bindings and the core proves active pointers
  remain unchanged.
- [COMPUTED | HIGH] Sealed Acceptance obtains aggregate facts only from an independently
  resolved evaluator driver, verifies a canonical attestation digest, candidate/suite/Gate
  Profile bindings, evaluator identity, key identity, and detached signature, then applies
  deterministic gates.
- [COMPUTED | HIGH] `KnowledgeReleaseRecord` binds the exact Draft Contract Bundle and
  Resolved Hybrid Knowledge Bindings to four distinct immutable Shadow, Capacity,
  Acceptance, and Recovery artifacts. Hybrid Agent publication fails closed without a
  registered matching record and freezes it into the Published Agent Version.
- [COMPUTED | HIGH] Release Record registration additionally requires an independent
  Release Evidence Authority to approve all four exact artifact references; absent,
  failed, or negative verification blocks persistence.
- [COMPUTED | HIGH] The registered `private-http` adapter covers all evaluation drivers
  and production operations telemetry over the pinned private-network transport. An
  independently registered HMAC verifier supplies the acceptance trust decision.
- [COMPUTED | HIGH] The external evaluation-asset manifest enforces the real 300/200 Gold
  Suite split, both 30/50/20 query mixes, tuner-hidden sealed custody, and a distinct
  100-to-200-case parser benchmark. No synthetic business corpus is committed.
- [COMPUTED | HIGH] Phase F verification passed 2662 backend tests with 1 skipped and 8
  opt-in tests deselected; Ruff passed and mypy passed all 257 source files.

### Phase E Hybrid Knowledge release controls (2026-07-14)

- Insurance Knowledge and parser contracts now enforce the 30/50/20 Gold Suite profile,
  exact Source Publication identity, complete comparison slots, ACL hard negatives, and
  sliced retrieval/parser metrics.
- Sealed acceptance persists an atomic one-attempt claim per production candidate and
  exposes aggregate-only results. Hard-zero authority, security, citation, and support
  failures cannot be offset by retrieval quality or latency.
- Knowledge Operations adds a read-only backend projection and Hybrid Source Dashboard
  panel for blockers, backlog, throughput, GPU/scheduler timing, outcome rates, rebuild
  state, citation/slot facts, and incomplete-telemetry blocking.
- Shadow comparison, five-run capacity measurement, and disposable four-fault recovery
  drill modules emit stable digest-bearing artifacts. CLI commands execute trusted
  deployment drivers, validate core invariants, and atomically persist shadow, capacity,
  sealed acceptance, and recovery results.
- Real Hybrid integration harnesses cover five concurrent authorized searches during a
  second publication and deletion/rebuild of a disposable Generation. They remain
  opt-in under the `hybrid_integration` marker.

| Area | Status |
| --- | --- |
| Contracts | Pydantic v2 frozen models for manifest, policy, ReAct action/review, evidence, approval, tools, model, Shared Model Connections, trace, receipt, run, dashboard, and Agent Configuration |
| Delivery | `delivery/cli.py` exposes Typer commands including continuous `knowledge-worker` and bounded `knowledge-worker --once`; `delivery/agent_package_execution.py` is the shared Agent package execution seam for CLI, validation, Run Execution API, and Conversation API; `delivery/api.py` exposes Run Execution and Conversation APIs; `delivery/configuration_api.py` exposes Agent Configuration, Knowledge Source, Shared Model Connection, and Tool Source workflows with server-side Operator Identity Context permissions, Workflow Template Descriptor and workflow stage preview/update routes, Shared Model Connection CRUD/lifecycle/reference/validation/smoke-test routes with Configuration Operation Audit for create/update/archive/restore/delete, Tool Source descriptor/CRUD/lifecycle routes with Configuration Operation Audit for create/update/archive/restore, plus Local Index quarantine, ingestion-job status, derived candidate validation, frozen snapshot management, Source publication, archive, restore, and physical-deletion eligibility; `delivery/published_agents.py` resolves static Published Agents and Active Agent Versions |
| Docker | `Dockerfile` and `docker-compose.yml` run deterministic demo |
| Bootstrap | `bootstrap/` owns YAML loader, path resolution, provider validation, model connection resolution, retrieval config validation, secret-looking param rejection, and `HarnessInvocation` composition |
| Control | `control/` owns Enterprise QA and Controlled ReAct workflow, Workflow Template Descriptors, stage context preview/summary assembly, policy, review fail-closed behavior, validators, evidence decisions, approval, and outcome behavior; `control/workflow/controlled_react/` owns the V3 Orchestrator, pure transition kernel, ports, and invocation adapters |
| Runtime | `runtime/langgraph_runner.py` executes non-V3 historical/runtime templates with composed Harness dependencies; V3 product execution bypasses LangGraph and runs through the Controlled ReAct Orchestrator |
| Capability | `capabilities/` owns model providers, ReAct planner, review subagent, knowledge provider registry, Local Index source-owned model resolution, memory, ToolGateway, local tool handler loading, and future Skill packs |
| Audit | `observability/audit/` owns JSONL trace, ReAct review/reasoning projections, model connection resolution records, redaction, Governance Receipt, model usage section |
| Storage / API | `observability/storage/` owns RunStore and ConversationStore; `configuration/local_store.py` owns local Agent Configuration state including Shared Model Connections; `observability/api/` owns read-only dashboard routes; Run Execution API starts governed production runs and Agent Configuration API starts governed validation runs through RunStore |
| Customer Service | `delivery/customer_api.py`, `delivery/customer_adapters.py`, `observability/storage/customer_store.py`, `observability/api/routers/handoffs.py`, `chat/` customer mode, and `examples/insurance_customer_service/` implement V1 customer-facing automatic replies with the insurance-specific Demo behind a Customer Run Adapter |
| Institution Specialist | `examples/institution_insurance_specialist/` implements a staff-facing insurance institution specialist Agent Package with Workflow Stage Prompt Configuration, short-term insurance-scoped knowledge, and read-only institution business tool fixtures |
| Evaluation | `evaluation/` owns deterministic demo helpers and Plain RAG vs Harness RAG comparison |
| Tests | 128 test files and 1119 statically detected `test_` functions at last scan |

## 3. Stable Demo Contract

The deterministic demo must remain runnable without network access, API keys, or remote provider SDK configuration.

Expected outcomes:

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
| LangGraph runtime | Non-V3 historical/runtime templates run through composed Harness dependencies; approval decisions use `PendingApproval` plus checkpoint resume where those templates still require LangGraph mechanics | Shared transactional checkpointer/lock backend for non-V3 deployments, production auth/RBAC integration, and streaming hooks |
| Controlled ReAct V3 | `react_enterprise_qa_v3` is the product main path; `execute_agent_package_run` routes it to `ControlledReActOrchestrator.start`, retrieval/tool actions produce `ObservationRecord` state, accepted evidence is admitted by manifest `min_score`, clarification returns `WAITING_FOR_USER_CLARIFICATION`, approval pause emits `ApprovalPause` plus snapshot ref, and resume uses `ControlledReActOrchestrator.resume` | Streaming, remote planner/review hardening, and any denied-approval-as-observation expansion without moving authority back into Runtime Plane |
| LangChain integration | Not a public adapter yet | Optional ecosystem adapter that preserves contracts |
| Real MCP | Mock tool proves approval contract | stdio/HTTP MCP adapter behind ToolGateway |
| Knowledge Hub provider set | Active code accepts `local_markdown`, `local_index`, trusted `http_json`, and the fixture `remote_search` adapter; `pageindex` and `local_vector` are rejected; Agent Contracts use explicit `package_knowledge_sources[]` plus `knowledge_bindings[].source_ref`; `http_json` has a default Remote Retrieval Protocol, bounded whole-value request mapping, JSON Pointer response mapping, env-referenced headers, and fail-closed normalization into Candidate Evidence; `local_index` registered runtime config is v2-only and resolves explicit `snapshot_path + artifact_root`, validates immutable manifests before storage access, projects bounded trace-safe metadata, sends at most `100` candidates to the Source-owned routing model through Control Plane `before_model_call` policy and safe tracing, loads only selected revision artifacts read-only, and fails closed without partial evidence when selected-document retrieval fails; source-owned ingestion and routing models can reference Shared Model Connections or custom provider config, with Source params overriding connection default timeout; the ingestion foundation stages quarantined single-file uploads and atomic batches, asynchronously validates Markdown and text-based PDF, promotes accepted document revisions, builds immutable revision artifacts, persists bounded retries, and exposes continuous worker polling, bounded one-shot execution, plus status APIs; Dashboard/API operators can edit allowlisted per-document routing metadata, advancing the Source Draft token and candidate digest without reingestion; the snapshot-freeze and publication loop derives READY candidate projections, persists foundation validation, freezes immutable `local_index.snapshot.v2` manifests, validates Source-level smoke retrieval, publishes vetted local snapshots, validates `http_json` smoke retrieval, publishes remote configuration versions with explicit `resource_kind: remote_config`, rejects unpublished shared Source binding, and persists resolved Knowledge Binding Sets on Published Agent Versions; Enterprise QA and Controlled ReAct enter retrieval through the shared Control Plane Knowledge Retrieval Service; blended single-step, reviewed/fallback, and planner/evaluator-backed agentic retrieval use deterministic binding metadata routing, record provider calls, apply binding failure modes, exact deduplication, WRRF ordering, no-evidence reason codes, and allowlisted one-shot Local Index document-routing summaries | Add richer remote retrieval preview/health-check UX and hierarchical routing beyond the first `100` document candidates |
| Agentic RAG | Agentic retrieval strategy emits governed retrieval plan/step events through the shared Knowledge Retrieval Service and falls back through registered Knowledge Providers when planner/evaluator models are absent; when planner/evaluator models are configured, each rewritten query re-enters service-owned bounded source routing and records round-correlated provider summaries, including Local Index `document_candidates[]` and `selected_documents[]`; Controlled ReAct submits reviewed Retrieval Intent without directly calling providers | Richer trace-safe plan summaries and nested retrieval budget projections |
| Dashboard UI | Implemented for overview, runs, Run Detail Workflow tab backed by backend-owned `workflow_projection`, evidence, receipt, model usage, JSONL Trace drilldown, Run Detail approval actions against resumable approval state through server-side Operator Identity Context, global approval queue API projection and `/approvals` triage page, handoffs, Configuration > Models and Shared Model Connection detail/reference/test/audit views through API-resolved operator identity instead of frontend actor fields, Knowledge Hub Source creation/detail/publication/lifecycle controls with source-owned model selectors and API-resolved operator identity, and the Agents configuration workspace with Dashboard Workflow Lens summary/map/Stage Inspector, Model/Knowledge editing, active published Source binding, Validation Workspace, publish, and rollback through API-resolved operator identity | Production auth/RBAC integration, richer multi-agent operations, shared Prompt templates, model connection import/export, and a real secret vault |
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
