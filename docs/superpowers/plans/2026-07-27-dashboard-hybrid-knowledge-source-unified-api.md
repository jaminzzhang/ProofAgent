# Dashboard Hybrid Knowledge Source And Unified API Implementation Plan

> Implement test-first in small vertical slices. Do not begin a later destructive cutover task until the preceding contract and migration evidence is green.

**Goal:** Deliver the accepted design in `docs/superpowers/specs/2026-07-27-dashboard-hybrid-knowledge-source-unified-api-design.md`.

**Architecture:** One `/api/config/knowledge-sources` contract fronts focused Configuration, Ingestion, Publication, and Operations application services. PostgreSQL is transactional authority, S3-compatible storage is artifact authority, OpenSearch is derived projection, and Knowledge Worker performs asynchronous intake, review import, and publication preparation. Dashboard is capability-driven.

**Primary stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy/PostgreSQL, S3-compatible storage, OpenSearch, React 19, TypeScript, Vitest, pytest.

---

## Task 1: Freeze V1 Contracts And Permission Vocabulary

**Modify:**

- `proof_agent/contracts/security.py`
- `proof_agent/contracts/__init__.py`
- `dashboard/src/api/types.ts`
- contract and security tests

**Create:**

- `proof_agent/contracts/knowledge_source_api.py`
- `tests/test_knowledge_source_api_contracts.py`

- [ ] Write failing serialization tests for provider capabilities, Source/action projection, cursor page, operation projection, Problem Details, and `knowledge_source.review`.
- [ ] Add strict Pydantic contracts with `schema_version="knowledge-source-api.v1"` and stable enums/codes.
- [ ] Add permission mapping tests proving review is distinct from edit and publish.
- [ ] Mirror the wire contracts in Dashboard TypeScript without mode-specific unions.
- [ ] Run `uv run --extra dev python -m pytest tests/test_knowledge_source_api_contracts.py tests/test_application_security_composition.py -q` and Dashboard typecheck.

## Task 2: Add Expand-Only PostgreSQL Authority

**Modify:**

- `proof_agent/capabilities/persistence/postgres/schema.py`
- `proof_agent/capabilities/persistence/postgres/bundle.py`
- `proof_agent/capabilities/persistence/postgres/knowledge_repository.py`
- `proof_agent/capabilities/persistence/postgres/hybrid_ingestion_repository.py`
- `proof_agent/capabilities/persistence/postgres/metadata_review_repository.py`
- `tests/test_postgres_migrations.py`

**Create:**

- next PostgreSQL migration under `proof_agent/capabilities/persistence/postgres/migrations/versions/`
- focused operation, idempotency, publication-preparation, and cursor repository modules/tests

- [ ] Write failing migration and repository tests for Source `revision`, durable operations, idempotency keys/fingerprints/outcomes, ingestion attempts/cancel state, publication preparations, and opaque cursor queries.
- [ ] Add expand-only tables/columns/indexes and uniqueness/fencing constraints; do not rewrite existing Hybrid authority rows destructively.
- [ ] Implement repository keyset queries that apply limit before materialization and return aggregate summaries independently.
- [ ] Prove exact replay, key mismatch, Source CAS conflict, stale cursor, and concurrent publication fencing.
- [ ] Run PostgreSQL migration/repository suites against the configured test database.

## Task 3: Introduce Focused Knowledge Application Services

**Modify:**

- `proof_agent/control/knowledge/production_intake.py`
- `proof_agent/control/knowledge/source_publication.py`
- `proof_agent/control/knowledge/__init__.py`

**Create:**

- focused Configuration, Ingestion, Publication, and Operations application modules and unit tests

- [ ] Write port-level failing tests for command authorization, capability computation, idempotency-before-CAS replay, Source/Draft revision rules, and trace-safe problems.
- [ ] Move route orchestration into focused application services; routes perform identity/admission mapping only.
- [ ] Make Source action capabilities use the same policy functions as commands without becoming authorization authority.
- [ ] Keep API process, Knowledge Worker, and Run Executor composition separate.
- [ ] Run focused control-layer tests and architectural import-boundary checks.

## Task 4: Implement Streaming Multipart Intake And Replacement

**Modify:**

- `proof_agent/delivery/production_knowledge_api.py` or its unified replacement
- `proof_agent/capabilities/knowledge/hybrid/intake.py`
- `proof_agent/control/knowledge/production_intake.py`
- S3 artifact adapter and intake integration tests

- [ ] Write failing API tests for one multipart PDF, byte/page/media limits, request interruption, response-loss replay, idempotency mismatch, Source CAS, and no direct storage locator exposure.
- [ ] Stream to a system-generated quarantine key while hashing and enforcing limits; do not buffer Base64 content.
- [ ] Persist upload, operation, idempotency result, Source revision, and work visibility through short authoritative transactions.
- [ ] Add explicit replacement at `/documents/{document_id}/revisions`; preserve the prior candidate through pending/failed replacement.
- [ ] Remove document batch/Base64 handlers only after new client tests are green.
- [ ] Run unit plus `tests/integration/test_hybrid_intake_postgres_s3_e2e.py`.

## Task 5: Add Attempts, Manual Retry, And Fenced Cancellation

**Modify:**

- `proof_agent/capabilities/knowledge/ingestion/hybrid_worker.py`
- `proof_agent/capabilities/persistence/postgres/hybrid_ingestion_repository.py`
- `proof_agent/contracts/knowledge_operations.py`
- `tests/test_hybrid_knowledge_worker.py`
- `tests/test_postgres_hybrid_ingestion_repository.py`

- [ ] Write failing transition tests for two automatic retries, manual attempt append, immediate queued cancellation, claimed cancellation, and late-result rejection.
- [ ] Persist immutable attempt history under a stable revision-bound job.
- [ ] Add `CANCEL_REQUESTED` handling and cancellation checks around provider calls and artifact publication.
- [ ] Implement idempotent Retry/Cancel commands and action blockers; file defects require replacement.
- [ ] Verify Source revision advances without Draft version churn until READY changes candidate membership.

## Task 6: Move Metadata Workbook Import Behind Worker

**Modify:**

- `proof_agent/capabilities/knowledge/hybrid/workbook.py`
- `proof_agent/capabilities/persistence/postgres/metadata_review_repository.py`
- unified Knowledge Source API and worker composition
- workbook/review tests

- [ ] Write failing multipart, idempotency, exact-revision binding, unsafe-XLSX, and atomic review-batch tests.
- [ ] Stage one `.xlsx` through the same governed binary boundary and return a durable operation.
- [ ] Move validation and review construction into Knowledge Worker; commit all reviews or none.
- [ ] Require `knowledge_source.review` for correct/approve/reject and retain independent review CAS identity.
- [ ] Delete the synchronous Base64 workbook request after Dashboard client cutover.

## Task 7: Split Publication Preparation From Authority Commit

**Modify:**

- `proof_agent/bootstrap/production_hybrid_publication.py`
- `proof_agent/capabilities/knowledge/hybrid/publication.py`
- publication repositories and worker role composition
- `tests/test_knowledge_source_publication.py`

- [ ] Write failing tests proving preparation is durable/asynchronous and publish performs no model, S3, or OpenSearch call.
- [ ] Move manifest, embedding, staged projection, read-back, attestation, and smoke retrieval into a fenced worker operation.
- [ ] Persist a one-use Prepared Hybrid Knowledge Publication bound to Draft/candidate/generation/manifest/attestation identities.
- [ ] Reduce publish to idempotency, permission, freshness, and one short PostgreSQL CAS.
- [ ] Test stale validation, competing attempts, response replay, staged orphan recovery, and harmless sequence gaps.

## Task 8: Replace The Public Router With One Contract

**Modify:**

- `proof_agent/observability/api/app.py`
- `proof_agent/delivery/production_knowledge_api.py`
- `proof_agent/delivery/configuration_api.py`
- API and security tests

**Create or rename:**

- one unified `proof_agent/delivery/knowledge_source_api.py`

- [ ] Write route matrix tests that run the same contract suite against production and disposable-local compositions.
- [ ] Implement provider capabilities, Source detail actions, cursor envelopes, operation polling, and Problem Details middleware/mapping.
- [ ] Ensure production composition fails closed when required authorities are absent.
- [ ] Mount exactly one Knowledge Source router in every Dashboard-serving mode.
- [ ] Keep old router code temporarily unreachable only until migration and Dashboard tasks pass; do not expose parallel public routes.

## Task 9: Build The Capability-Driven Dashboard Client

**Modify:**

- `dashboard/src/api/types.ts`
- `dashboard/src/api/client.ts`
- API client tests

**Create:**

- focused Knowledge capability, cursor, operation polling, multipart upload, and idempotency helpers/hooks

- [ ] Write failing tests for capability load, Problem Details mapping, cursor restart, stable Idempotency Key replay, bounded upload concurrency, hidden-page polling pause, and terminal Source reload.
- [ ] Remove provider inventory and deployment-mode inference from the client.
- [ ] Use `FormData` for PDF and workbook commands; report per-file outcomes.
- [ ] Centralize operation polling with server guidance and bounded backoff.
- [ ] Remove Base64 and batch request types after all callers migrate.

## Task 10: Deliver The Seven-Tab Hybrid Workspace

**Modify:**

- `dashboard/src/pages/KnowledgePage.tsx`
- `dashboard/src/pages/KnowledgeDetailPage.tsx`
- `dashboard/src/components/knowledge/*`
- `dashboard/src/i18n/messages.ts`
- page/component tests

- [ ] Write failing UI tests for Hybrid creation from capabilities and the seven-tab layout.
- [ ] Implement Overview and Documents first as a usable create → upload → operation vertical slice.
- [ ] Add Reviews and workbook operation flow with permission-aware actions.
- [ ] Add Versions & Publish with preparation polling, confirmation, publication history, and Agent upgrade opportunity only.
- [ ] Add Operations, read-only Provider & Health, and permission-gated Audit.
- [ ] Prove disabled/hidden controls follow action capabilities and every command still handles authoritative rejection.
- [ ] Run Dashboard unit tests, typecheck, and a production-composition browser smoke test.

## Task 11: Add The One-Shot Development Migrator

**Create:**

- explicit CLI migration module and focused tests

**Modify:**

- CLI registration and deployment/development guide

- [x] Write failing dry-run, manifest, backup verification, Source ID conflict, missing-original, secret-value rejection, and partial-item failure tests.
- [x] Import supported `local_index` metadata and originals through new intake; never import cached index artifacts.
- [x] Import supported `http_json` non-secret config and credential references as unpublished/unverified Draft state.
- [x] Exclude package-local Markdown and reject production-only unsupported providers.
- [x] Emit a machine-readable and operator-readable migration manifest without mutating on dry-run.

## Task 12: Atomic Cutover And Deletion Of The Development Implementation

**Modify:**

- `proof_agent/observability/api/app.py`
- deployment composition and guides
- Dashboard and end-to-end tests

**Delete after evidence is green:**

- file-backed deployable Knowledge Hub router/store paths and mode-specific DTOs
- document/workbook Base64 and batch endpoints
- local-storage production fallback

- [ ] Run migrations and new API/Dashboard smoke checks in the inactive blue-green slot.
- [x] Run migrator dry-run or explicitly record disposable-environment skip.
- [x] Prove package-local Markdown demos and test fakes remain independent and green.
- [x] Delete unreachable legacy implementation and all compatibility tests expecting it.
- [x] Run the complete Knowledge, security, PostgreSQL, API, Dashboard, and deployment test suites plus `python3 scripts/check-domain-contexts.py` and `git diff --check`.
- [x] Update `docs/operations-deployment-development-guide.zh-CN.md` and `docs/development-progress.md` with implemented evidence only; do not mark production-ready from local tests alone.

## Release Gates

- [x] Same contract suite passes against production and disposable-local composition.
- [x] 10,000-document cursor and aggregate tests remain bounded.
- [x] Multipart memory/size tests prove no Base64 amplification and no browser S3 authority.
- [x] Crash/replay tests cover response loss, worker restart, cancellation, stale claim, stale validation, and CAS conflict.
- [x] Security tests cover all five Knowledge permissions plus `audit.view` and safe Problem Details.
- [x] Publication commit test proves zero calls to private models, S3, and OpenSearch.
- [x] Dashboard end-to-end test closes create → upload → review → prepare → Source publish and stops before Agent activation.
