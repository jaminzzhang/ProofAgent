# Local Index Snapshot Freeze Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a derived Local Index candidate snapshot, Source Draft version token, foundation validation record, and idempotent immutable `local_index.snapshot.v2` freeze API without making frozen snapshots production-bindable.

**Architecture:** Keep the candidate as a lock-protected projection of managed READY documents rather than a persisted mirror. Persist passed foundation validations and immutable snapshot manifests beside each Source, reuse the existing content-addressed revision artifacts, and advance only `latest_snapshot_id`; leave `published_snapshot_id`, Agent binding resolution, and runtime multi-document routing for later slices.

**Tech Stack:** Python 3.12, Pydantic v2 frozen contracts, FastAPI, file-backed JSON storage with `filelock`, SHA-256 canonical JSON digests, pytest, Ruff, mypy

---

## Scope Boundary

This plan implements Slice A from:

- `docs/adr/0017-mutable-candidate-snapshot-projection.md`
- `docs/superpowers/specs/2026-06-02-local-index-snapshot-freeze-foundation-design.md`

Do not modify `proof_agent/capabilities/knowledge/local_index_snapshot.py` or the registered runtime
provider in this slice. Runtime still consumes the existing single-artifact
`local_index.snapshot.v1` contract. Slice B will add `local_index.snapshot.v2` loading and bounded
multi-document routing.

## File Map

**Create:**
- `proof_agent/capabilities/knowledge/ingestion/artifacts.py` - optional-dependency-safe revision-artifact metadata and compatibility checks shared by ingestion build and snapshot validation.
- `tests/test_knowledge_ingestion_artifacts.py` - focused compatibility-helper tests that import without LlamaIndex.
- `tests/test_knowledge_snapshot_store.py` - focused Source Draft token, candidate projection, foundation validation, and freeze lifecycle tests.

**Modify:**
- `proof_agent/errors.py` - register stable `PA_INGESTION_005`.
- `proof_agent/contracts/agent_configuration.py` - extend `KnowledgeSource`; add candidate, validation, snapshot-document, and snapshot-manifest contracts.
- `proof_agent/contracts/__init__.py` - export the new public contracts.
- `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py` - use the shared artifact helper while preserving builder behavior.
- `proof_agent/configuration/local_store.py` - mint Source Draft tokens, derive candidates, persist validations and manifests, freeze idempotently, and atomically update the latest frozen pointer.
- `proof_agent/delivery/configuration_api.py` - expose candidate, validation, freeze, list, and detail management endpoints; map `PA_INGESTION_005` to HTTP `409`.
- `tests/test_agent_configuration_contracts.py` - verify JSON-safe frozen snapshot contracts and the new stable error code.
- `tests/test_agent_configuration_api.py` - verify management endpoint payloads and `404`/`400`/`409`/`503` boundaries.
- `docs/technical-design.md` - record the implemented foundation-freeze boundary and `PA_INGESTION_005`.
- `docs/developer-guide.md` - document the preview-only freeze workflow and management endpoints.
- `docs/development-progress.md` - update the implementation snapshot and remaining Knowledge Hub roadmap.

## Task 1: Frozen Snapshot Contracts And Stable Conflict Error

**Files:**
- Modify: `proof_agent/errors.py:16-20`
- Modify: `proof_agent/contracts/agent_configuration.py:128-168`
- Modify: `proof_agent/contracts/__init__.py:2-16`
- Modify: `proof_agent/contracts/__init__.py:96-175`
- Modify: `tests/test_agent_configuration_contracts.py:106-259`

- [ ] **Step 1: Write failing contract tests**

Extend `tests/test_agent_configuration_contracts.py` to assert:

```python
source = KnowledgeSource(
    source_id="ks_policy",
    name="Policy",
    provider="local_index",
    params={},
    created_at="2026-06-02T00:00:00Z",
    updated_at="2026-06-02T00:00:00Z",
)
assert source.source_draft_version_id is None
assert source.latest_snapshot_id is None
assert source.published_snapshot_id is None

document = KnowledgeSourceSnapshotDocument(
    document_id="doc_001",
    revision_id="rev_001",
    filename="policy.md",
    content_type="text/markdown",
    content_hash="a" * 64,
    artifact_path="artifacts/content/fingerprint",
    routing_metadata={"department": "claims"},
)
candidate = CandidateKnowledgeSourceSnapshot(
    source_id="ks_policy",
    source_draft_version_id="ksdraft_001",
    candidate_digest="b" * 64,
    included_documents=(document,),
    queued_document_count=0,
    processing_document_count=0,
    failed_document_count=0,
    archived_document_count=0,
    required_reingestion_count=0,
)
assert candidate.model_dump(mode="json")["included_documents"][0]["routing_metadata"] == {
    "department": "claims"
}
```

Construct and serialize `FoundationKnowledgeSourceValidation` and
`KnowledgeSourceSnapshotManifest`; assert their `validation_level`, `state`, and
`schema_version` literals. Assert snapshot routing metadata is recursively frozen. Extend the
stable-error assertion with:

```python
assert ErrorCode.PA_INGESTION_005.value == "PA_INGESTION_005"
```

- [ ] **Step 2: Run the contract tests and confirm the red state**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py -q
```

Expected: FAIL because the snapshot contracts and `PA_INGESTION_005` are not defined.

- [ ] **Step 3: Add the minimal frozen contracts**

Extend `KnowledgeSource`:

```python
source_draft_version_id: str | None = None
latest_snapshot_id: str | None = None
published_snapshot_id: str | None = None
```

Add:

```python
class KnowledgeSourceSnapshotDocument(FrozenModel):
    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: str
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)


class CandidateKnowledgeSourceSnapshot(FrozenModel):
    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    included_documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    queued_document_count: int
    processing_document_count: int
    failed_document_count: int
    archived_document_count: int
    required_reingestion_count: int


class FoundationKnowledgeSourceValidation(FrozenModel):
    validation_id: str
    source_id: str
    source_draft_version_id: str
    candidate_digest: str
    validation_level: Literal["foundation"]
    status: Literal["passed"]
    document_count: int
    required_reingestion_count: int
    created_at: str
    created_by: str


class KnowledgeSourceSnapshotManifest(FrozenModel):
    schema_version: Literal["local_index.snapshot.v2"]
    snapshot_id: str
    source_id: str
    state: Literal["READY"]
    validation_level: Literal["foundation"]
    source_draft_version_id: str
    candidate_digest: str
    foundation_validation_id: str
    documents: tuple[KnowledgeSourceSnapshotDocument, ...]
    created_at: str
    created_by: str
```

Use the existing `freeze_value()` plus field serializer pattern for `routing_metadata`. Export the
four new contracts. Add `PA_INGESTION_005` to `ErrorCode`.

- [ ] **Step 4: Re-run the contract tests**

Run the Task 1 pytest command again.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/errors.py proof_agent/contracts/agent_configuration.py \
  proof_agent/contracts/__init__.py tests/test_agent_configuration_contracts.py
git commit -m "Add local index snapshot freeze contracts"
```

## Task 2: Optional-Dependency-Safe Artifact Compatibility Helper

**Files:**
- Create: `proof_agent/capabilities/knowledge/ingestion/artifacts.py`
- Create: `tests/test_knowledge_ingestion_artifacts.py`
- Modify: `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py:33-42`
- Modify: `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py:171-186`
- Modify: `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py:274-307`

- [ ] **Step 1: Write failing helper tests**

Create `tests/test_knowledge_ingestion_artifacts.py` with a local artifact fixture and cover:

```python
assert is_compatible_local_index_artifact(
    artifact_path,
    build_spec=build_spec,
    ingestion_config_fingerprint=fingerprint,
)
```

Also assert `False` for a missing directory, missing required LlamaIndex file, malformed sidecar,
wrong schema version, changed content hash, and changed fingerprint. Prove the helper import stays
lightweight with a fresh-interpreter smoke command:

```bash
uv run --extra dev python -c \
  'import sys; import proof_agent.capabilities.knowledge.ingestion.artifacts; assert "llama_index" not in sys.modules'
```

- [ ] **Step 2: Verify the helper tests fail without the new module**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_ingestion_artifacts.py -q
```

Expected: FAIL because `proof_agent.capabilities.knowledge.ingestion.artifacts` does not exist.

- [ ] **Step 3: Extract metadata and compatibility logic**

Move these builder-only constants and helpers into `artifacts.py`:

```python
from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any, cast

from proof_agent.contracts import KnowledgeArtifactBuildSpec


ARTIFACT_SCHEMA_VERSION = "local_index.artifact.v1"
ARTIFACT_META_FILENAME = "artifact_meta.json"
REQUIRED_LLAMA_INDEX_FILES = (
    "docstore.json",
    "index_store.json",
    "graph_store.json",
    "default__vector_store.json",
    "image__vector_store.json",
)

def local_index_artifact_metadata(
    *,
    build_spec: KnowledgeArtifactBuildSpec,
    ingestion_config_fingerprint: str,
) -> dict[str, str]:
    return {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "provider": build_spec.provider,
        "engine_name": build_spec.engine_name,
        "engine_version": build_spec.engine_version,
        "parser_identity": build_spec.parser_fingerprint_identity,
        "content_hash": build_spec.content_hash,
        "ingestion_config_fingerprint": ingestion_config_fingerprint,
    }

def is_compatible_local_index_artifact(
    artifact_path: Path,
    *,
    build_spec: KnowledgeArtifactBuildSpec,
    ingestion_config_fingerprint: str,
) -> bool:
    if not artifact_path.is_dir():
        return False
    if any(not (artifact_path / filename).is_file() for filename in REQUIRED_LLAMA_INDEX_FILES):
        return False
    metadata = _read_json_object(artifact_path / ARTIFACT_META_FILENAME)
    return metadata is not None and all(
        metadata.get(key) == value
        for key, value in local_index_artifact_metadata(
            build_spec=build_spec,
            ingestion_config_fingerprint=ingestion_config_fingerprint,
        ).items()
    )


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return cast(dict[str, Any], payload)
```

Keep this module limited to standard-library imports plus `KnowledgeArtifactBuildSpec`; it must not
import LlamaIndex, the builder, provider registry, or model bridge. Update the builder to import and
use the helper. Continue importing the moved constants into `local_index_builder.py` so existing
builder tests and callers keep their current import path. Give `artifacts.py` its own private JSON
sidecar reader; retain the builder's `_read_json_object()` because stale-temporary housekeeping
still uses it for `artifact_temp.json`.

- [ ] **Step 4: Re-run helper and builder regression tests**

Run:

```bash
uv run --extra dev python -m pytest tests/test_knowledge_ingestion_artifacts.py -q
uv run --extra dev python -c \
  'import sys; import proof_agent.capabilities.knowledge.ingestion.artifacts; assert "llama_index" not in sys.modules'
uv run --extra dev --extra tree python -m pytest tests/test_local_index_revision_builder.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion/artifacts.py \
  proof_agent/capabilities/knowledge/ingestion/local_index_builder.py \
  tests/test_knowledge_ingestion_artifacts.py
git commit -m "Extract local index artifact compatibility checks"
```

## Task 3: Source Draft Token And Derived Candidate Projection

**Files:**
- Create: `tests/test_knowledge_snapshot_store.py`
- Modify: `proof_agent/configuration/local_store.py:257-303`
- Modify: `proof_agent/configuration/local_store.py:586-626`
- Modify: `proof_agent/configuration/local_store.py:812-846`
- Modify: `proof_agent/configuration/local_store.py:1213-1276`
- Modify: `proof_agent/configuration/local_store.py:1324-1358`

- [ ] **Step 1: Write failing Source token and candidate tests**

Create `tests/test_knowledge_snapshot_store.py`. Reuse the ingestion-store test pattern to create a
Local Index Source and persist managed `KnowledgeDocument` plus `KnowledgeIngestionJob` projections.
Cover:

- Source creation mints `source_draft_version_id` and keeps both snapshot pointers `None`.
- First candidate read normalizes and persists a token for a manually downgraded legacy
  `source.json` without the new field.
- Candidate projection includes only READY documents and reports queued, processing, failed, and
  archived counts.
- Candidate projection rejects non-`local_index` Sources and READY documents without an artifact
  reference using `PA_INGESTION_001`.
- Candidate documents are sorted by `document_id`; the digest is stable across persistence order
  and changes when one included manifest input changes.
- Completing an ingestion job advances the Source token once; upload staging, accepted queued
  promotion, claim, renewal, defer, retry, failure, rejected upload, and purge paths do not advance
  it.

- [ ] **Step 2: Verify the store tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_knowledge_snapshot_store.py -q
```

Expected: FAIL because Source token minting and candidate projection are not implemented.

- [ ] **Step 3: Implement token minting and candidate derivation**

Add a generated draft token:

```python
def _new_source_draft_version_id() -> str:
    return f"ksdraft_{uuid4().hex[:8]}"
```

Mint it during `create_knowledge_source()`. Add:

```python
def get_candidate_knowledge_source_snapshot(
    self,
    source_id: str,
) -> CandidateKnowledgeSourceSnapshot:
    with locked(self._store_lock_path(), timeout_seconds=STORE_LOCK_TIMEOUT_SECONDS):
        source = self._normalized_local_index_source_unlocked(source_id)
        return self._candidate_knowledge_source_snapshot_unlocked(source)
```

The unlocked derivation:

1. iterate managed document projections;
2. count excluded states;
3. include only READY revisions with non-empty relative artifact references;
4. construct `KnowledgeSourceSnapshotDocument(..., routing_metadata={})`;
5. sort included documents by `document_id`;
6. SHA-256 hash compact sorted-key JSON for included document payloads only;
7. return required reingestion count `0`.

Use `_write_json_atomic()` for `source.json`, because draft-token normalization and pointer updates
must not expose a partially written Source record. When `complete_knowledge_ingestion_job()` moves a
document to `ready`, mint and persist a new Source token under the existing store lock after writing
the document and completed job.

- [ ] **Step 4: Re-run snapshot-store and existing ingestion-store tests**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_knowledge_snapshot_store.py \
  tests/test_knowledge_ingestion_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/configuration/local_store.py tests/test_knowledge_snapshot_store.py
git commit -m "Derive local index candidate snapshots"
```

## Task 4: Foundation Validation And Idempotent Snapshot Freeze

**Files:**
- Modify: `proof_agent/configuration/local_store.py:286-303`
- Modify: `proof_agent/configuration/local_store.py:525-550`
- Modify: `proof_agent/configuration/local_store.py:812-846`
- Modify: `proof_agent/configuration/local_store.py:1213-1304`
- Modify: `proof_agent/configuration/local_store.py:1394-1406`
- Modify: `tests/test_knowledge_snapshot_store.py`

- [ ] **Step 1: Write failing foundation validation tests**

Extend `tests/test_knowledge_snapshot_store.py` with a fixture that writes a compatible revision
artifact sidecar plus required LlamaIndex storage files. Cover:

- Foundation validation persists `snapshot_validations/{validation_id}.json`.
- The record binds Source token, candidate digest, document count, required reingestion count,
  actor, `validation_level="foundation"`, and `status="passed"`.
- Validation rejects an empty candidate, escaped artifact path, missing artifact, missing
  ingestion job, mismatched document/job artifact reference, and incompatible sidecar with
  `PA_INGESTION_001`.
- Failed validation does not persist any validation record.

- [ ] **Step 2: Write failing freeze lifecycle tests**

Cover:

- Freeze writes `snapshots/{snapshot_id}/snapshot.json` with
  `schema_version="local_index.snapshot.v2"` and multiple document-revision artifact references.
- Freeze updates `latest_snapshot_id` and leaves `published_snapshot_id is None`.
- Freeze rejects unknown validation id with `KeyError`.
- Freeze rejects a manually corrupted validation record stored under the target Source but declaring
  another Source, a stale token, changed digest, or an incompatible deterministic manifest with
  `PA_INGESTION_005`.
- Freeze normalizes malformed supplied validation JSON and malformed existing deterministic
  manifest JSON into value-safe `PA_INGESTION_005` rather than leaking Pydantic or JSON errors.
- Repeated freeze with the same validation reuses one manifest.
- Re-validation of an unchanged candidate still reuses the existing manifest and its original
  `foundation_validation_id`.
- A simulated interruption after manifest persistence but before Source pointer update leaves an
  unpointed valid manifest; replay reuses it and repairs the pointer.

- [ ] **Step 3: Verify the lifecycle tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_knowledge_snapshot_store.py -q
```

Expected: FAIL because validation and freeze store operations do not exist.

- [ ] **Step 4: Add validation and snapshot persistence paths**

Add:

```python
knowledge_sources/{source_id}/snapshot_validations/{validation_id}.json
knowledge_sources/{source_id}/snapshots/{snapshot_id}/snapshot.json
```

Add path, read, and atomic-write helpers for validation records. Add path, read, list, and
atomic-write helpers for snapshot manifests. Resolve artifact references beneath `root_dir` using
a containment check; reject absolute paths, `..` escapes, missing jobs, job/document mismatches, and
incompatible artifacts with value-safe `PA_INGESTION_001`.

When freeze reads a supplied validation or an existing deterministic manifest, catch malformed JSON
and Pydantic validation failures and raise `_snapshot_freeze_conflict(...)`. Unknown supplied
validation ids still raise `KeyError`, allowing the API to preserve the deliberate HTTP `404`
boundary.

Add:

```python
validate_candidate_knowledge_source_snapshot_foundation(
    *,
    source_id: str,
    actor: str,
) -> FoundationKnowledgeSourceValidation

freeze_candidate_knowledge_source_snapshot(
    *,
    source_id: str,
    validation_id: str,
    actor: str,
) -> KnowledgeSourceSnapshotManifest

get_knowledge_source_snapshot(
    *,
    source_id: str,
    snapshot_id: str,
) -> KnowledgeSourceSnapshotManifest | None

list_knowledge_source_snapshots(
    source_id: str,
) -> list[KnowledgeSourceSnapshotManifest]
```

Validation derives the candidate and verifies all revision artifacts under the store lock before
persisting a passed record. Freeze derives:

```python
snapshot_id = "kssnapshot_" + sha256(
    f"{source.source_id}:{source.source_draft_version_id}:{candidate.candidate_digest}".encode()
).hexdigest()[:16]
```

Freeze writes the immutable manifest before atomically updating `source.latest_snapshot_id`. If the
deterministic manifest already exists, validate its Source, READY state, foundation level, token,
digest, and documents; reuse its original validation/audit metadata and repair the pointer. Add:

```python
def _snapshot_freeze_conflict(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_005",
        message,
        "Refresh the candidate snapshot, validate it again, and retry snapshot freeze.",
    )
```

Keep messages value-safe: do not include document content, secrets, or escaped filesystem paths.

- [ ] **Step 5: Re-run snapshot-store and artifact-helper tests**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_knowledge_snapshot_store.py \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_knowledge_ingestion_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/configuration/local_store.py tests/test_knowledge_snapshot_store.py
git commit -m "Freeze foundation-validated local index snapshots"
```

## Task 5: Snapshot Freeze Management API

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py:103-137`
- Modify: `proof_agent/delivery/configuration_api.py:140-303`
- Modify: `proof_agent/delivery/configuration_api.py:687-707`
- Modify: `proof_agent/delivery/configuration_api.py:791-852`
- Modify: `tests/test_agent_configuration_api.py:18-90`
- Modify: `tests/test_agent_configuration_api.py:390-450`

- [ ] **Step 1: Write failing API lifecycle tests**

Add a test helper that prepares one READY Local Index document and compatible artifact through the
store. Cover:

```text
GET  /api/config/knowledge-sources/{source_id}/candidate-snapshot
POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/validate-foundation
POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/freeze
GET  /api/config/knowledge-sources/{source_id}/snapshots
GET  /api/config/knowledge-sources/{source_id}/snapshots/{snapshot_id}
```

Assert Source create, list, and detail payloads expose `source_draft_version_id`,
`latest_snapshot_id`, and `published_snapshot_id`. Assert freeze returns preview-only snapshot v2
data and detail/list replay the same manifest.

- [ ] **Step 2: Write failing API error tests**

Cover:

- unknown Source and unknown supplied validation or snapshot ids return HTTP `404`;
- non-`local_index` Source and invalid artifact candidate return HTTP `400`;
- stale validation after a later READY transition returns HTTP `409` with
  `detail.code == "PA_INGESTION_005"`;
- candidate read, validation, and freeze each map `PA_INGESTION_004` lock timeout to HTTP `503`
  without a second attempted state write.

- [ ] **Step 3: Verify the API tests fail**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest \
  tests/test_agent_configuration_api.py -q
```

Expected: FAIL because the management routes and request bodies do not exist.

- [ ] **Step 4: Add request contracts and endpoints**

Add:

```python
class KnowledgeSourceFoundationValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor: str = "local-user"


class KnowledgeSourceSnapshotFreezeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    validation_id: str = Field(min_length=1)
    actor: str = "local-user"
```

Implement the five routes near the existing Source ingestion endpoints. Return
`model_dump(mode="json")` payloads for candidate, validation, and manifest contracts. Catch
`KeyError` for unknown Source, validation, and snapshot identities and project HTTP `404`. Extend:

```python
def _proof_agent_http_exception(exc: ProofAgentError) -> HTTPException:
    status_code = {
        "PA_INGESTION_004": 503,
        "PA_INGESTION_005": 409,
    }.get(exc.code, 400)
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "fix": exc.fix},
    )
```

Do not add `/publish`, mutate `published_snapshot_id`, or change Agent binding YAML in this task.

- [ ] **Step 5: Re-run focused API and store tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest \
  tests/test_agent_configuration_api.py \
  tests/test_knowledge_snapshot_store.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/delivery/configuration_api.py tests/test_agent_configuration_api.py
git commit -m "Expose local index snapshot freeze API"
```

## Task 6: Documentation And Full Verification

**Files:**
- Modify: `docs/technical-design.md:642-669`
- Modify: `docs/technical-design.md:1085-1094`
- Modify: `docs/developer-guide.md:382-415`
- Modify: `docs/development-progress.md:19-21`
- Modify: `docs/development-progress.md:76-77`

- [ ] **Step 1: Update implementation-facing documentation**

Document:

- candidate snapshot is derived from READY managed revisions under the store lock;
- Source Draft token advances on candidate membership changes, not lease/retry noise;
- foundation validation proves artifact compatibility and freezes immutable
  `local_index.snapshot.v2` manifests;
- `latest_snapshot_id` is preview/routing-smoke only;
- `published_snapshot_id` stays unset until formal Source Publication validation exists;
- runtime still consumes the existing single-artifact v1 path in this slice;
- remaining roadmap: formal Source Publication API, continuous polling, max-50 atomic batch upload,
  runtime v2 multi-document routing, trusted `http_json`.

Extend the technical error table to include `PA_INGESTION_005` as snapshot-freeze state conflict.

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py \
  tests/test_knowledge_ingestion_artifacts.py \
  tests/test_local_index_revision_builder.py \
  tests/test_knowledge_ingestion_store.py \
  tests/test_knowledge_snapshot_store.py \
  tests/test_agent_configuration_api.py -q
```

Expected: PASS.

- [ ] **Step 3: Run full regression tests**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/ -q
```

Expected: PASS. PDF-specific parser tests may skip only when the optional `ingestion` extra is not
installed; run the ingestion-extra verification below before completion.

- [ ] **Step 4: Run ingestion-extra verification**

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_knowledge_document_parsers.py \
  tests/test_knowledge_ingestion_worker.py \
  tests/test_local_index_revision_builder.py \
  tests/test_knowledge_snapshot_store.py -q
```

Expected: PASS with PDF-specific tests executed rather than skipped.

- [ ] **Step 5: Run static checks and deterministic demo**

Run:

```bash
uv run --extra dev --extra ingestion --extra tree ruff check proof_agent tests
uv run --extra dev --extra dashboard --extra ingestion --extra openai --extra tree mypy proof_agent
git diff --check
uv run --extra dev --extra tree proof-agent demo
```

Expected: Ruff, mypy, and diff checks pass. Demo preserves:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 6: Commit documentation**

```bash
git add docs/technical-design.md docs/developer-guide.md docs/development-progress.md
git commit -m "Document local index snapshot freeze foundation"
```

- [ ] **Step 7: Inspect final history and worktree**

Run:

```bash
git status --short --branch
git log --oneline --decorate -7
```

Expected: clean `codex/local-index-snapshot-freeze-foundation` worktree with the design commit and
six focused implementation/documentation commits.
