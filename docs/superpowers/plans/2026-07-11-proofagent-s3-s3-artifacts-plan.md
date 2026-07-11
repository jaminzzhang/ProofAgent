# Proof Agent S3 S3 Artifact Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [FRAME | HIGH] Make S3-compatible storage the sole production authority for immutable artifacts, with verified S3-first visibility, safe materialization, retention, orphan collection, and exact-version recovery.

**Architecture:** [FRAME | HIGH] Introduce a provider-neutral Artifact Store port, an S3 adapter, and a local development adapter. Upload unique non-overwritable objects and verify exact version/length/SHA-256, upload the manifest last, then bind references and owner visibility in one PostgreSQL transaction. Invisible upload remnants are orphans, not a resumable Saga.

**Tech Stack:** [FRAME | HIGH] Python 3.12, Pydantic v2, boto3/botocore behind an adapter, PostgreSQL, S3-compatible versioned object storage, pytest, real reference-service integration tests.

---

## Prerequisites and Exit Contract

- [ ] [FRAME | HIGH] Begin after S1 establishes the repository layout and the serialized S2 implementation has merged migration `0002_identity_security`; S3 remains logically independent of S2 policy semantics but owns the next single Alembic head.
- [ ] [KNOWN | HIGH] Read `docs/domain/knowledge-evidence/CONTEXT.md`, `docs/domain/observability/CONTEXT.md`, and `docs/domain/agent-configuration/CONTEXT.md`.
- [ ] [FRAME | HIGH] Require the test and candidate S3 services to support bucket versioning, exact version reads/deletes, conditional non-overwrite puts, stable object length, and SHA-256 verification. A service lacking any capability is incompatible, not silently downgraded.
- [ ] [FRAME | HIGH] Exit only when no unverified object or local path can become production-visible and combined PostgreSQL/S3 recovery verifies every reference digest.

## Task 1: Define Immutable Artifact Contracts and Store Port

**Files:**

- Create: `proof_agent/contracts/artifacts.py`
- Create: `proof_agent/contracts/ports/artifacts.py`
- Modify: `proof_agent/contracts/__init__.py`
- Create: `tests/test_artifact_contracts.py`

- [ ] [FRAME | HIGH] Write red tests for invalid SHA-256, negative length, missing version ID, duplicate manifest member, path traversal in display filename, mutable key reuse, unsupported kind, and a visible owner without a manifest.
- [ ] [FRAME | HIGH] Implement strict frozen DTOs for immutable object version, member, manifest, owner, retention, and visibility. Keep the port equivalent to:

```python
from collections.abc import BinaryIO, Iterator
from datetime import datetime
from typing import Protocol

from proof_agent.contracts.artifacts import ArtifactObjectVersion, ArtifactPutRequest


class ArtifactStore(Protocol):
    def put_immutable(self, request: ArtifactPutRequest, body: BinaryIO) -> ArtifactObjectVersion: ...
    def head_exact(self, ref: ArtifactObjectVersion) -> ArtifactObjectVersion: ...
    def open_exact(self, ref: ArtifactObjectVersion) -> BinaryIO: ...
    def delete_exact(self, ref: ArtifactObjectVersion) -> None: ...
    def iter_versions_before(self, *, prefix: str, before: datetime) -> Iterator[ArtifactObjectVersion]: ...
```

- [ ] [FRAME | HIGH] Use artifact kinds for run trace, Governance Receipt, validation capture, Knowledge source, Knowledge index member, Knowledge manifest, Agent/configuration bundle, evaluation Evidence, release Manifest, HTML report, and Bundle Index.
- [ ] [FRAME | HIGH] Store only exact object key, version ID, SHA-256, length, kind, owner, content type, created/expiry metadata, and visibility/corruption state in PostgreSQL; never store payload blobs.
- [ ] [KNOWN | HIGH] Run `uv run --extra dev python -m pytest tests/test_artifact_contracts.py -v` and mypy.
- [ ] [FRAME | HIGH] Commit with message `Define immutable artifact authority contracts`.

## Task 2: Implement Local and S3-Compatible Artifact Adapters

**Files:**

- Create: `proof_agent/capabilities/artifacts/__init__.py`
- Create: `proof_agent/capabilities/artifacts/filesystem.py`
- Create: `proof_agent/capabilities/artifacts/s3.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `tests/test_filesystem_artifact_store.py`
- Create: `tests/test_s3_artifact_store.py`
- Create: `tests/integration/compose.s3.yaml`
- Create: `tests/integration/reference-services.lock.json`

- [ ] [FRAME | HIGH] Add `boto3>=1.35,<2` to an `s3` extra and to the later `production` extra; SDK types stay inside `s3.py`.
- [ ] [FRAME | HIGH] Drive the local adapter with immutable put/head/get/delete and corruption tests; use it only for development/tests.
- [ ] [FRAME | HIGH] Drive the S3 adapter against an actual versioned S3-compatible reference service. Pin the service image by digest in `reference-services.lock.json`; Compose reads that lock through the test launcher and has no mutable default tag.
- [ ] [FRAME | HIGH] Generate opaque object keys as `objects/{random_partition}/{uuid4}` containing no user text, owner ID, media role, or filename, then send a conditional non-overwrite put. Keep a sanitized attachment/display name only in validated PostgreSQL/Manifest metadata and require a returned nonempty version ID.
- [ ] [FRAME | HIGH] Verify each put by exact-version head plus exact-version stream SHA-256/length. Do not trust ETag as a content digest.
- [ ] [FRAME | HIGH] Add startup compatibility checks for versioning, exact read/delete, conditional put, checksum behavior, clock assumptions, and credentials resolved through S2 Secret Handles or deployment identity.
- [ ] [FRAME | HIGH] Commit with message `Add S3-compatible immutable artifact adapter`.

## Task 3: Persist Exact Artifact References and Visibility

**Files:**

- Create: `proof_agent/contracts/ports/artifact_references.py`
- Create: `proof_agent/capabilities/persistence/postgres/artifact_repository.py`
- Create: `proof_agent/capabilities/persistence/postgres/migrations/versions/0003_artifacts.py`
- Create: `tests/test_postgres_artifact_repository.py`

- [ ] [FRAME | HIGH] Write red tests for immutable reference insert, unique `(bucket,key,version_id)`, owner-manifest consistency, conditional owner visibility, logical expiry, corruption quarantine, and reference-preserving physical-delete eligibility.
- [ ] [FRAME | HIGH] Add `artifact_objects`, `artifact_manifests`, `artifact_manifest_members`, and `artifact_owner_bindings` tables. Store no bytes and no provider SDK serialization.
- [ ] [FRAME | HIGH] Implement one unit-of-work method that inserts verified references, binds the manifest, changes owner visibility, and—when owner is a Run Attempt—commits terminal state plus `result_available=true` under the live claim token/attempt/epoch condition.
- [ ] [FRAME | HIGH] A PostgreSQL-only infrastructure failure may commit terminal state with `result_available=false` and no manifest binding. It cannot be treated as a governed audience result.
- [ ] [FRAME | HIGH] Commit with message `Persist verified artifact references and visibility`.

## Task 4: Implement S3-First Manifest-Last Finalization

**Files:**

- Create: `proof_agent/control/artifacts/__init__.py`
- Create: `proof_agent/control/artifacts/finalization.py`
- Create: `tests/test_artifact_finalization.py`
- Modify: `proof_agent/control/workflow/harness_helpers.py`
- Modify: `proof_agent/delivery/agent_package_execution.py`
- Modify: `proof_agent/observability/storage/run_store.py`

- [ ] [FRAME | HIGH] Write one red failure-injection test per boundary: freeze failure, member upload failure, exact verification failure, manifest upload failure, PostgreSQL visibility failure, duplicate finalization, cancellation race, and stale Executor commit.
- [ ] [FRAME | HIGH] Implement this exact order:

```text
freeze immutable member bytes and compute length/SHA-256
put every member under a unique key
head/get every exact returned version and verify length/SHA-256
serialize a canonical manifest containing only verified exact refs
put and verify the manifest last
open one PostgreSQL transaction
insert refs + bind manifest + make owner visible + commit terminal facts
commit once
```

- [ ] [FRAME | HIGH] Do not create `PENDING_UPLOAD`, resumable per-object checkpoints, compensating cross-store transactions, or automatic replay of uncertain model/tool work.
- [ ] [FRAME | HIGH] If upload/finalization fails before visibility, retry only within the Attempt deadline, then write an explicit infrastructure failure with `result_available=false`. Uploaded but invisible exact versions remain eligible for orphan collection.
- [ ] [FRAME | HIGH] Keep `RunStore` as a local adapter/projection only; production run reads resolve manifest-bound exact S3 objects.
- [ ] [FRAME | HIGH] Commit with message `Finalize artifacts before PostgreSQL visibility`.

## Task 5: Migrate Knowledge and Validation Artifacts

**Files:**

- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/artifacts.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Modify: `proof_agent/capabilities/knowledge/local_index_snapshot.py`
- Modify: `proof_agent/bootstrap/knowledge_resolution.py`
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `proof_agent/observability/api/routers/runs.py`
- Modify: existing Knowledge/validation tests

- [ ] [FRAME | HIGH] Replace production `artifact_path`, `snapshot_path`, and `artifact_root` authority with exact Artifact refs. Local paths may exist only inside an isolated temporary build/materialization workspace.
- [ ] [FRAME | HIGH] Make Knowledge Worker build and validate the complete Local Index in a temporary directory, finalize all index members and manifest through Task 4, then publish the Knowledge revision/snapshot in the same PostgreSQL visibility transaction.
- [ ] [FRAME | HIGH] Make validation captures, trace, Receipt, and evaluation artifacts use the same manifest-last boundary and independent retention metadata.
- [ ] [FRAME | HIGH] Update APIs to resolve only visible, unexpired, non-corrupt exact refs and to return sanitized unavailability when verification fails.
- [ ] [KNOWN | HIGH] Run existing Knowledge ingestion, snapshot, local-index, RunStore, run API, and validation-capture suites.
- [ ] [FRAME | HIGH] Commit with message `Publish run and Knowledge artifacts through S3`.

## Task 6: Add Verified Digest-Keyed Materialization Cache

**Files:**

- Create: `proof_agent/capabilities/artifacts/materialization.py`
- Create: `tests/test_artifact_materialization.py`
- Modify: `proof_agent/capabilities/knowledge/local_index.py`
- Modify: `proof_agent/capabilities/knowledge/local_index_snapshot.py`
- Defer explicit Executor wiring to: `2026-07-11-proofagent-s4-run-queue-executor-plan.md`, Task 4

- [ ] [FRAME | HIGH] Write red tests for cold read, cache hit, concurrent same-digest reads, short object, wrong digest, missing manifest member, corrupt member, interrupted download, eviction, and cache loss.
- [ ] [FRAME | HIGH] Download into a private temporary path, stream-check exact length/SHA-256, fsync, chmod read-only, and atomically rename to `{cache_root}/sha256/{digest}` only after verification.
- [ ] [FRAME | HIGH] Use per-digest locking and verify every Knowledge manifest member before opening the index; never expose a partially populated directory.
- [ ] [FRAME | HIGH] Cache eviction cannot delete S3 objects, PostgreSQL refs, or alter visibility. A cache miss is always recoverable from exact S3 versions.
- [ ] [FRAME | HIGH] Commit with message `Verify and materialize immutable artifacts`.

## Task 7: Enforce Retention and Reference-Safe Orphan Collection

**Files:**

- Create: `proof_agent/observability/retention.py`
- Create: `proof_agent/observability/artifact_gc.py`
- Create: `tests/test_artifact_retention.py`
- Create: `tests/test_artifact_gc.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Encode the approved application-visible lifetimes: validation capture 7 days, Case Memory 30 days, Operator Chat raw text 90 days, trace-safe run/Receipt/config/security audit 365 days, and Knowledge/config artifacts while referenced.
- [ ] [FRAME | HIGH] On logical expiry, remove ordinary query/download/Dashboard visibility immediately. Recovery copies may remain encrypted for at most seven additional days and are not ordinary history.
- [ ] [FRAME | HIGH] Write red GC tests proving: no orphan is deleted before 24 hours; referenced/visible/recovery-protected versions are preserved; exact-version delete is used; a race that gains a reference prevents deletion; repeated GC is idempotent; failures emit backlog/oldest-age metrics and alerts.
- [ ] [FRAME | HIGH] Treat any orphan older than seven days as an operational alert and release-health failure until collection succeeds or the reference classification is corrected.
- [ ] [FRAME | HIGH] Add `proof-agent artifacts expire`, `proof-agent artifacts gc`, and `proof-agent artifacts verify-references` commands with dry-run JSON output and audited production mutations.
- [ ] [FRAME | HIGH] Keep S3 bucket lifecycle rules subordinate to reference policy; a lifecycle rule must not physically delete a still-referenced exact version.
- [ ] [FRAME | HIGH] Commit with message `Enforce artifact retention and orphan collection`.

## Task 8: Add Exact-Version Recovery and Combined Verification

**Files:**

- Create: `proof_agent/observability/recovery.py`
- Create: `tests/test_artifact_recovery.py`
- Modify: `proof_agent/delivery/cli.py`

- [ ] [FRAME | HIGH] Write red tests for restored missing version, wrong version, wrong length/digest, expired owner visibility, corrupt manifest/member, incomplete PostgreSQL restore, and a fully valid restore.
- [ ] [FRAME | HIGH] Add `proof-agent recovery verify --at RFC3339` that reapplies current retention rules, hides already-expired data, verifies 100% of exact refs and manifest members, validates the sole Agent references, and emits a machine-readable report. It must never repair by selecting a different object version.
- [ ] [FRAME | HIGH] Leave authenticated smoke Run and timed RPO/RTO orchestration to S6/S7, but expose all deterministic cross-store verification primitives here.
- [ ] [FRAME | HIGH] Commit with message `Verify exact-version artifact recovery`.

## Task 9: S3 Full Verification and Review

- [ ] [KNOWN | HIGH] Run:

```bash
PROOF_AGENT_TEST_POSTGRES_DSN=postgresql+psycopg://proofagent:proofagent@127.0.0.1:55432/proofagent_test \
PROOF_AGENT_TEST_S3_ENDPOINT=http://127.0.0.1:59000 \
  uv run --extra dev --extra postgres --extra s3 python -m pytest \
  tests/test_artifact_contracts.py \
  tests/test_filesystem_artifact_store.py \
  tests/test_s3_artifact_store.py \
  tests/test_postgres_artifact_repository.py \
  tests/test_artifact_finalization.py \
  tests/test_artifact_materialization.py \
  tests/test_artifact_retention.py \
  tests/test_artifact_gc.py \
  tests/test_artifact_recovery.py -v
uv run --extra dev python -m pytest tests/ -v
uv run --extra dev ruff check proof_agent tests
uv run --extra dev --extra openai --extra postgres --extra s3 mypy proof_agent
python3 scripts/check-domain-contexts.py
git diff --check
```

- [ ] [FRAME | HIGH] Independently review exact-version semantics, verification cost/correctness, visibility transaction, failure/cancel races, cache atomicity, retention/reference safety, orphan grace, and recovery behavior.
- [ ] [FRAME | HIGH] Resolve all P0/P1 findings, record the S3 commit in the master plan, and only then unblock S4/S5.
