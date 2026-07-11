# Proof Agent S1 PostgreSQL Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Make PostgreSQL the sole production authority for mutable structured state while preserving deterministic local development behind focused ports.

**Architecture:** [FRAME | HIGH] Define use-case-shaped immutable DTOs and repository/unit-of-work ports in the contracts layer, adapt current filesystem stores behind those ports, then add SQLAlchemy Core/psycopg PostgreSQL adapters and explicit Alembic expand-only migrations. No database model or SDK type crosses a port.

**Tech Stack:** [FRAME | HIGH] Python 3.12, Pydantic v2, SQLAlchemy 2 Core, psycopg 3, Alembic, PostgreSQL, pytest, Docker-backed integration tests.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin only after S0 is merged, reviewed, and green.
- [ ] [KNOWN | HIGH] Read `docs/domain/agent-configuration/CONTEXT.md`, `docs/domain/knowledge-evidence/CONTEXT.md`, `docs/domain/observability/CONTEXT.md`, and the actual paths routed by `CONTEXT-MAP.md`; use the map if any named path has moved.
- [ ] [FRAME | HIGH] Exit only when production composition cannot instantiate a local mutable store, every repository integration suite runs against real PostgreSQL without skips, and migrations are explicit, locked, expand-only, and repeatable.

## Task 1: Define Focused Persistence DTOs and Ports

**Files:**

- Create: `proof_agent/contracts/persistence.py`
- Create: `proof_agent/contracts/ports/__init__.py`
- Create: `proof_agent/contracts/ports/agent_lifecycle.py`
- Create: `proof_agent/contracts/ports/shared_assets.py`
- Create: `proof_agent/contracts/ports/run_metadata.py`
- Create: `proof_agent/contracts/ports/conversations.py`
- Create: `proof_agent/contracts/ports/case_memory.py`
- Create: `proof_agent/contracts/ports/audit.py`
- Create: `proof_agent/contracts/ports/unit_of_work.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_persistence_ports.py`

- [ ] [FRAME | HIGH] Write red tests with in-memory fakes for one use case per port: save/get draft, atomically publish a version, resolve shared-asset versions, append/read run metadata, append conversation turn, admit/expire Case Memory, append audit metadata, and rollback a multi-repository unit of work.
- [ ] [FRAME | HIGH] Reuse existing public Agent/Knowledge/model/tool/conversation/run contracts where their semantics fit; add persistence-only immutable IDs, version refs, pagination cursors, and audit actor facts without importing SQLAlchemy.
- [ ] [FRAME | HIGH] Keep ports use-case-shaped. A representative boundary is:

```python
from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from proof_agent.contracts.agent_configuration import AgentDraft, PublishedAgentVersion


class AgentLifecycleRepository(Protocol):
    def get_draft(self, agent_id: str) -> AgentDraft | None: ...
    def save_draft(self, draft: AgentDraft, *, expected_revision: int) -> AgentDraft: ...
    def get_published(self, agent_id: str, version: str) -> PublishedAgentVersion | None: ...
    def list_published(self, agent_id: str) -> Sequence[PublishedAgentVersion]: ...


class ConfigurationUnitOfWork(Protocol, AbstractContextManager["ConfigurationUnitOfWork"]):
    agents: AgentLifecycleRepository
    knowledge: "KnowledgeAssetRepository"
    models: "ModelAssetRepository"
    tools: "ToolAssetRepository"
    audit: "AuditRepository"

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
```

- [ ] [FRAME | HIGH] Do not put artifact bytes, raw provider tokens, raw secrets, ORM objects, database sessions, or filesystem paths in these ports.
- [ ] [KNOWN | HIGH] Run `uv run --extra dev python -m pytest tests/test_persistence_ports.py -v` and mypy.
- [ ] [FRAME | HIGH] Commit with message `Introduce focused persistence ports`.

## Task 2: Adapt Existing Local Stores Behind the Ports

**Files:**

- Modify: `proof_agent/configuration/local_store.py`
- Modify: `proof_agent/observability/storage/run_store.py`
- Modify: `proof_agent/observability/storage/conversation_store.py`
- Modify: `proof_agent/capabilities/memory/local_store.py`
- Create: `proof_agent/capabilities/persistence/local/__init__.py`
- Create: `proof_agent/capabilities/persistence/local/bundle.py`
- Modify: `proof_agent/bootstrap/composition.py`
- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `proof_agent/bootstrap/model_resolution.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Modify: `proof_agent/capabilities/tools/gateway.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/delivery/published_agents.py`
- Modify: `proof_agent/observability/api/dependencies.py`
- Modify: current local-store tests

- [ ] [FRAME | HIGH] Type consumers against ports before changing behavior. Add a dependency-layout test that delivery/control modules cannot import `LocalAgentConfigurationStore`, `RunStore`, `ConversationStore`, or `LocalMemoryStore` directly.
- [ ] [FRAME | HIGH] Build `LocalPersistenceBundle` as the explicit `development` composition only. It may delegate to existing classes temporarily, but each exposed repository must implement only its focused port.
- [ ] [FRAME | HIGH] Split multi-record publication orchestration from `LocalAgentConfigurationStore`; keep filesystem locking inside the local adapter and policy decisions in Control/Delivery services.
- [ ] [KNOWN | HIGH] Run existing Agent configuration, run-store, conversation, Knowledge Worker, model connection, tool source, and local-memory tests after each consumer migration.
- [ ] [FRAME | HIGH] Commit with message `Adapt local stores to focused persistence ports`.

## Task 3: Add Explicit PostgreSQL Dependencies and Migration Harness

**Files:**

- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `alembic.ini`
- Create: `proof_agent/capabilities/persistence/postgres/__init__.py`
- Create: `proof_agent/capabilities/persistence/postgres/database.py`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/env.py`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/script.py.mako`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/versions/0001_foundation.py`
- Create: `tests/postgres_fixtures.py`
- Create: `tests/test_postgres_migrations.py`

- [ ] [FRAME | HIGH] Add explicit optional extras and make the later production extra depend on them:

```toml
postgres = [
  "alembic>=1.13,<2",
  "psycopg[binary,pool]>=3.2,<4",
  "sqlalchemy>=2.0,<3"
]
```

- [ ] [FRAME | HIGH] Write red migration tests against an empty real PostgreSQL database: upgrade to head; re-run idempotently; acquire one advisory migration lock; reject an application schema newer than supported; prove downgrade is not part of the production release command.
- [ ] [FRAME | HIGH] Create the first expand-only schema with UTC timestamps, immutable version rows, foreign keys, unique business identities, optimistic draft revisions, and no artifact byte columns:

```text
agent_drafts, agent_versions
knowledge_sources, knowledge_source_versions, knowledge_snapshots
model_connections, model_connection_versions
tool_sources, tool_source_versions
configuration_validations
runs, run_attempts
conversations, conversation_turns
case_memory_records
audit_events
```

- [ ] [FRAME | HIGH] Use database-generated UUIDv7 or another full-width 128-bit collision-resistant identifier for Run, Attempt, conversation, artifact-owner, and audit identities; remove short random ID authority. Add constraints for unique published `(agent_id, version)`, immutable version ownership, monotonic draft revision, unique Run identity, valid conversation-turn ordering, and Case Memory `expires_at`.
- [ ] [FRAME | HIGH] Implement `proof-agent database current`, `proof-agent database upgrade`, and `proof-agent database check` commands; no application startup path calls `upgrade`.
- [ ] [KNOWN | HIGH] Run migration tests with `PROOF_AGENT_TEST_POSTGRES_DSN` and confirm they fail rather than skip when the variable is required in CI.
- [ ] [FRAME | HIGH] Commit with message `Add locked PostgreSQL migration foundation`.

## Task 4: Implement Agent and Shared-Asset PostgreSQL Repositories

**Files:**

- Create: `proof_agent/capabilities/persistence/postgres/agent_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/knowledge_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/model_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/tool_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/configuration_uow.py`
- Create: `tests/test_postgres_agent_repository.py`
- Create: `tests/test_postgres_shared_asset_repositories.py`
- Modify: `proof_agent/configuration/importer.py`
- Modify: `proof_agent/configuration/compiler.py`
- Modify: `proof_agent/delivery/configuration_api.py`

- [ ] [FRAME | HIGH] Drive each repository with create/read/update-conflict/list tests, then add immutable publication and reference-integrity tests.
- [ ] [FRAME | HIGH] Implement publication as one database transaction that freezes the exact Agent configuration plus shared-asset version references and writes the audit fact. A draft edit after publication cannot change that version.
- [ ] [FRAME | HIGH] Use database constraints plus conditional updates for concurrency; do not emulate optimistic locking with a read followed by an unconditional write.
- [ ] [FRAME | HIGH] Add atomic activation/rollback primitives for versioned configuration, while S2 supplies the security-specific validation rules.
- [ ] [FRAME | HIGH] Commit with message `Persist Agent lifecycle and shared assets in PostgreSQL`.

## Task 5: Implement Run, Conversation, Case Memory, and Audit Repositories

**Files:**

- Create: `proof_agent/capabilities/persistence/postgres/run_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/conversation_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/case_memory_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/audit_repository.py`
- Create: `tests/test_postgres_run_repository.py`
- Create: `tests/test_postgres_conversation_repository.py`
- Create: `tests/test_postgres_case_memory_repository.py`
- Create: `tests/test_postgres_audit_repository.py`
- Modify: `proof_agent/control/workflow/harness_helpers.py`
- Modify: `proof_agent/evaluation/sample_production.py`
- Modify: `proof_agent/evaluation/subject_exports.py`
- Modify: `proof_agent/evaluation/campaigns.py`

- [ ] [FRAME | HIGH] Write red tests for immutable Run request metadata, Attempt append/conditional update primitives, ordered conversation turns, Case Memory scope/expiry, and append-only audit metadata.
- [ ] [FRAME | HIGH] Keep S1 Run state operations minimal but S4-ready: unique IDs, attempts, state/version column, transaction-scoped conditional transition, and no synchronous execution policy in the repository.
- [ ] [FRAME | HIGH] Make expired Case Memory absent from ordinary reads immediately; physical deletion scheduling belongs to S3 retention.
- [ ] [FRAME | HIGH] Store trace-safe audit metadata only; raw trace/Receipt/validation bytes become S3 references in S3.
- [ ] [FRAME | HIGH] Commit with message `Persist run conversation memory and audit metadata`.

## Task 6: Add Explicit Local and Production Composition Roots

**Files:**

- Create: `proof_agent/capabilities/persistence/bundle.py`
- Create: `proof_agent/capabilities/persistence/postgres/bundle.py`
- Create: `proof_agent/bootstrap/application_services.py`
- Modify: `proof_agent/observability/api/app.py`
- Modify: `proof_agent/observability/api/dependencies.py`
- Modify: `proof_agent/delivery/cli.py`
- Create: `tests/test_application_composition.py`

- [ ] [FRAME | HIGH] Define `PROOF_AGENT_MODE=development|production` with no implicit default in deploy commands. Local developer commands may select `development` explicitly; the production entry point requires PostgreSQL configuration.
- [ ] [FRAME | HIGH] Write a red test proving production composition rejects a missing DSN and never instantiates a local adapter; write the reciprocal development test proving the offline deterministic demo still works.
- [ ] [FRAME | HIGH] Construct one `PersistenceBundle` per application/process, inject ports through `application.state`/service constructors, and centralize transaction lifecycle.
- [ ] [FRAME | HIGH] Add `/api/health` only as a compatibility alias; S6 will define normative `/livez` and `/readyz`.
- [ ] [KNOWN | HIGH] Run API, configuration, conversation, run, evaluation, and CLI smoke suites in both modes where applicable.
- [ ] [FRAME | HIGH] Commit with message `Select PostgreSQL persistence for production composition`.

## Task 7: Put Real PostgreSQL Tests in CI

**Files:**

- Modify: `.github/workflows/ci.yml`
- Create: `tests/integration/conftest.py`
- Modify: `pyproject.toml` pytest markers

- [ ] [FRAME | HIGH] Add a pinned PostgreSQL service container and health check to CI; expose a throwaway DSN only to integration tests.
- [ ] [FRAME | HIGH] Separate fast unit tests from `postgres_integration`, but require both jobs. A skip in the required integration job is a failure.
- [ ] [FRAME | HIGH] Run migration, concurrency, rollback, constraint, and repository tests against the service; do not substitute SQLite.
- [ ] [FRAME | HIGH] Commit with message `Require PostgreSQL repository integration tests`.

## Task 8: S1 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
PROOF_AGENT_TEST_POSTGRES_DSN=postgresql+psycopg://proofagent:proofagent@127.0.0.1:55432/proofagent_test \
  uv run --extra dev --extra postgres python -m pytest \
  tests/test_postgres_migrations.py \
  tests/test_postgres_agent_repository.py \
  tests/test_postgres_shared_asset_repositories.py \
  tests/test_postgres_run_repository.py \
  tests/test_postgres_conversation_repository.py \
  tests/test_postgres_case_memory_repository.py \
  tests/test_postgres_audit_repository.py -v
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra postgres mypy proof_agent
uv run --extra dev proof-agent demo
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Independently review schema invariants, transaction ownership, port depth, local-fallback negatives, migration locking, and concurrency behavior.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S1 commit in the master plan, and only then unblock S2 and S3.
