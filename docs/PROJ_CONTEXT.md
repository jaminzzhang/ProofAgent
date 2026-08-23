# Project Context

## Current implementation facts

- `[KNOWN | HIGH]` The active Python product package is `proof_agent`; its main
  runtime composition enters through `proof_agent/bootstrap/composition.py`.
- `[KNOWN | HIGH]` The independent Knowledge Source Service implementation package
  is `knowledge_source_service/` at the repository root, alongside `proof_agent/`.
  Its independent distribution metadata and container build files remain under
  `services/knowledge-source-service/`. Its public query resource is
  `/v1/knowledge-queries`, and its API, Query Executor, Knowledge Worker,
  Synchronization Scheduler, and migration roles have independent entry points.
- `[KNOWN | HIGH]` As of 2026-08-19, ADR-0210 makes KSS the only executable
  knowledge authority. A knowledge-enabled Published Agent Version owns one
  exact `ResolvedKnowledgeSourceServiceBinding`; ProofAgent queries through
  `proof_agent/capabilities/knowledge/source_service_client.py` and applies its
  own exact Admission Scorer. Package, shared-source and Hybrid bindings are
  rejected, and production fails closed without a local fallback.
- `[KNOWN | HIGH]` ProofAgent's old Hybrid provider, ingestion, publication,
  worker, repository, source-management API, CLI and Dashboard paths have been
  physically removed. KSS's own Knowledge Worker remains. Former Hybrid-bound
  Published Agent Versions are historical records and no longer replayable or
  usable as rollback targets.
- `[KNOWN | HIGH]` As of 2026-08-20, Agent Configuration Workspace local slices
  cover Draft inventory/read/update, validation, development publication, Agent
  Version pointer rollback, Workflow Stage Configuration save/preview, raw
  Contract GET/PATCH, and Business Flow Skill Pack specialized read/create/update/
  delete. Skill Pack commands now cross one Workspace interface, update manifest
  binding and package-local definition in one revision CAS transaction, and append
  Draft/global audit atomically. A temporary local inspector owns compilation and
  projection, while Dashboard sends the current projection revision and creates a
  complete Skill Pack with one command. Package-local definition safety is shared
  by manifest, raw Contract and Skill Pack adapters; Dashboard freezes stale edits
  until an explicit latest-version reload. Slice 7 passed main-agent verification
  and independent review with no blocking findings. A disposable PostgreSQL 17.5
  service subsequently passed the Configuration UoW tests and the complete
  PostgreSQL-marked suite. An independent follow-up review found no P0–P3; this
  remains local evidence, not production approval.
- `[COMPUTED | HIGH]` Slice 7 plus the real-PostgreSQL follow-up passed 2050 backend tests,
  197 Dashboard tests and 35 Chat tests; both production builds passed. Ruff,
  strict mypy over 354 source files, domain-context, diff and lock checks passed.
  This does not authorize production.
- `[KNOWN | HIGH]` As of 2026-08-22, Production Agent Detail restores governed
  Contract, Workflow, Skill Pack, exact KSS Release and publication-configuration
  interactions through the Agent Configuration Workspace. The publication tab is
  a read-only authoring snapshot over one Draft revision plus live KSS and Shared
  Model Connection facts. It explicitly reports `workspace_draft_not_bound`:
  the current formal publisher still uses independent candidate inputs, and the
  Dashboard exposes no publish or activate command.
- `[COMPUTED | HIGH]` Slice 8E passed 2039 backend tests, 217 Dashboard tests and
  35 Chat tests. Ruff, mypy over 357 source files, TypeScript, all UI builds,
  domain-context, diff and lock checks passed. Eleven real-PostgreSQL tests were
  skipped because the current shell had no `PROOF_AGENT_TEST_POSTGRES_DSN`, so
  the Slice 8E evidence remains `PASS_WITH_ENV_LIMITATION`, not production approval.
- `[KNOWN | HIGH]` As of 2026-08-23, Slice 8F closes the verified Agent Detail
  Development flow gaps without changing publication authority. Metadata PATCH
  honors a caller-provided Draft revision; the Dashboard exposes saved/unsaved and
  Validation-freshness state, blocks Validation of unsaved configuration and
  publication from stale Validation, counts Draft Validation Records directly,
  and confirms Agent Version pointer rollback. Development auth session projection
  now returns the local Operator instead of raising a missing-middleware 500.
- `[COMPUTED | HIGH]` Slice 8F passed 96 focused backend tests with 4
  environment skips (91 Agent Configuration API plus 5 security-composition tests),
  221 Dashboard tests, Agent Detail 62 tests, Dashboard build,
  Ruff, focused mypy, domain-context and diff checks. A temporary local store real
  browser run verified metadata revision 2→3, auth session 200, unsaved/stale
  lifecycle blockers, Validation count 1 and rollback confirmation. This remains
  local Development evidence; Production PostgreSQL, Phase F publication, online
  KSS smoke and deployment Gates were not executed.
- `[KNOWN | HIGH]` As of 2026-08-23, Slice 8G aligns every Agent Detail
  configuration surface with its current write authority. Workflow no longer
  reintroduces retired runtime fields; Model writes `react.max_plan_rounds` and
  always exposes Review controls; Tools writes only `capabilities.tools`;
  optional Contract sections can be inserted; and save actions cannot commit a
  different module's unsaved state or advance the revision on a no-op.
- `[COMPUTED | HIGH]` Slice 8G passed 225 Dashboard tests, the Dashboard
  production build, 96 focused backend tests with 4 environment skips, Ruff,
  strict Mypy over 357 source files, domain-context and diff checks. A temporary
  Development browser run saved canonical Model configuration, completed exact
  revision Validation with expected `REFUSED_NO_EVIDENCE`, published an immutable
  Development version, observed separate Run/Validation counts, and confirmed
  active-pointer rollback. This is local workflow evidence, not Production
  publication or deployment approval.
- `[KNOWN | HIGH]` As of 2026-08-13, Dashboard KSS management uses the
  same-origin `/api/config/knowledge-service` BFF. ProofAgent resolves the KSS
  operator credential from Vault and calls the independent service through the
  active Egress Policy; browser responses contain only readiness and catalog
  projections. The UI can create Space, Source, and Base resources and list
  Source Versions and Releases. KSS remains the catalog authority.
- `[KNOWN | HIGH]` `AGENTS-COMMON.md` requires PostgreSQL authority for mutable
  production state, S3-compatible immutable artifacts, and fail-closed
  production composition.
- `[KNOWN | HIGH]` Local acceptance on 2026-08-12 covers strict contracts,
  heterogeneous intake, immutable Source/Release authority, real
  PostgreSQL/MinIO/OpenSearch retrieval, bounded Agentic retrieval, durable
  synchronization, ProofAgent integration, and a retained production-shaped
  Docker Compose deployment. KSS runs five isolated roles from non-root image
  `97c2db1f…`, owns a separate PostgreSQL database through its dedicated
  non-superuser login role, and is exposed at `https://proof-agent.localhost:8444`.
  This is local deployment verification, not production approval.
- `[KNOWN | HIGH]` The 2026-08-13 retained deployment rebuilt ProofAgent image
  `f74462bb…` and KSS image `53747fd5…`. The deployment verifier passed, and a
  production-composed BFF client read `ready` plus 3 Spaces, 6 Sources, 3 Bases,
  6 Source Versions, and 3 Releases. Existing browser sessions were invalidated
  by the immutable Permission Mapping epoch change and require a new OIDC login.
- `[KNOWN | HIGH]` Product Release Authority uses the versioned
  `initial-private-pilot-v2` policy to compute five fail-closed risk Gates from
  raw pipeline facts. Exact Evidence and detached workload-identity attestations
  reuse the existing Artifact Store and Release Bundle Index; the verifier can
  reach `GO` only with deployment-owned public trust.
- `[KNOWN | HIGH]` Production Candidate Binding v2 identifies ProofAgent and KSS
  independently. KSS contributes exact OCI, Python distribution, canonical
  OpenAPI and ordered migration-contract digests; the DCM also binds KSS,
  OpenSearch and the private knowledge-model plane. The formal KSS five-role
  Compose has an independent lifecycle under `deploy/production/knowledge/`.
- `[KNOWN | HIGH]` Metadata Review V2 remains a maintenance-window direct
  cutover. The normal Blue/Green expand-only migration rejects revisions `0020`
  and `0021`; the explicit cutover command requires stopped writes, stopped
  Workers and exact pre-cutover backup Evidence.

The Graphify map was queried during the 2026-08-18 authority cutover to check the
former composition, knowledge-resolution and provider seams. The cutover itself
is governed by ADR-0210 and current code; Graphify is navigation evidence, not
release approval.

## Feature index

| Feature ID | Status | Evidence directory | Governing design |
| --- | --- | --- | --- |
| `knowledge-source-service` | `PARTIAL_VERIFICATION` | `docs/features/knowledge-source-service/` | ADR-0210 and `docs/superpowers/specs/2026-08-11-knowledge-source-service-design.md` |
| `production-agent-lifecycle` | `PARTIAL_VERIFICATION` | `docs/features/production-agent-lifecycle/` | ADR-0124 and `docs/superpowers/plans/2026-07-11-proofagent-s5-sole-agent-migration-plan.md` |
| `product-release-authority` | `VERIFIED_LOCAL` | `docs/features/product-release-authority/` | ADR-0132 and ADR-0208 |
| `agent-configuration-workspace` | `VERIFIED_LOCAL` | `docs/features/agent-configuration-workspace/` | ADR-0009、ADR-0011 与 2026-08-18 架构评审 Phase 3 |

## Status vocabulary

- `SCOPING`: behavior or authority remains undecided.
- `TDD_INPUT_READY`: scope and acceptance evidence are sufficient to start RED.
- `IMPLEMENTING`: at least one TDD slice is active, but feature acceptance is not
  complete.
- `PARTIAL_VERIFICATION`: implementation and default local checks pass, but one or
  more named P1 environment-backed checks remain unexecuted; this is not production
  approval.
- `VERIFIED_LOCAL`: recorded local acceptance checks pass; local Docker evidence
  may exist, but the status is not production approval or a formal release Gate.
- `BLOCKED`: a named dependency or decision prevents meaningful progress.
