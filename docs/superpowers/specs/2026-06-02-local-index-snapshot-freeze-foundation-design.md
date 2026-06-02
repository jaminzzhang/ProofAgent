# Local Index Snapshot Freeze Foundation Design

## Scope

This slice turns READY single-revision Local Index artifacts into immutable multi-document snapshot
manifests for preview and the next runtime-routing slice. It adds a derived Candidate Knowledge
Source Snapshot, a lightweight Knowledge Source Draft Version token, foundation validation,
idempotent snapshot freeze, a latest frozen snapshot pointer, and management APIs.

This slice does not make a frozen snapshot production-bindable. It does not update a production
`published_snapshot_id`, add formal Knowledge Source Publication, resolve Agent bindings to
snapshots, perform runtime multi-document routing, run routing-model or smoke-query validation,
resolve citation previews, add replacement revision history, archive documents, upload batches,
poll workers continuously, add Dashboard UI, or add the `http_json` adapter.

## Product Boundary

Knowledge Hub needs two distinct transitions:

```text
managed document state
  -> derived Candidate Knowledge Source Snapshot
  -> Foundation Knowledge Source Publication Validation
  -> idempotent snapshot freeze
  -> Frozen Knowledge Source Snapshot
  -> later routing-smoke and citation validation
  -> later Knowledge Source Publication
  -> production-bindable published snapshot pointer
```

The first transition exists so the next runtime-routing slice can consume a realistic immutable
multi-document snapshot. It must not imply that production publication has already happened.

## Domain Decisions

### Derived Mutable Candidate Projection

The Candidate Knowledge Source Snapshot is not a persisted `candidate.json` mirror. The store
derives it from managed document projections:

- include documents whose active revision state is `ready`;
- require one non-empty relative artifact reference for every included revision;
- exclude queued, processing, failed, and future archived revisions;
- expose excluded-state counts so later Dashboard work can show partial-ingestion status;
- require at least one included READY revision before foundation validation can pass.

The current store has an active-revision `KnowledgeDocument` projection rather than full revision
history. This slice preserves that smaller model. Each frozen manifest still records exact
`document_id`, `revision_id`, and artifact reference so a future replacement and revision-history
slice does not need to migrate retained manifests.

### Knowledge Source Draft Version

Every newly created Knowledge Source receives a `source_draft_version_id`. It is a lightweight
change token, not an immutable Source Draft history record.

The token advances when a state change can alter the next frozen snapshot:

- a document revision becomes READY after artifact build completion;
- future artifact-affecting Source configuration edits;
- future document replacement readiness or archive membership changes.

The token does not advance for:

- upload staging;
- rejected upload state or rejected-byte purge;
- worker claim, lease renewal, defer, retry counter, or failure metadata;
- snapshot freeze itself;
- latest snapshot pointer updates.

For backward-compatible loading, persisted Knowledge Sources that predate the field may carry
`None`. The first candidate read, validation, or freeze operation normalizes the Source under the
store lock by minting and persisting a token before returning the candidate or writing a validation
record. Newly created Sources always have a token.

### Foundation Validation Is Not Production Validation

Foundation validation proves the minimum immutable-input requirements for snapshot freeze:

- target Source exists and uses provider `local_index`;
- the derived candidate contains at least one READY revision;
- every included document has a relative artifact path contained beneath the store root;
- every referenced artifact exists and passes the reusable Local Index artifact compatibility
  check against its persisted Knowledge Ingestion Job build spec and fingerprint;
- the validation record binds the current `source_draft_version_id` and deterministic candidate
  digest;
- pending required reingestion count is zero. The current slice has no reingestion workflow, so
  this count is structurally zero until that workflow is added.

Foundation validation does not test routing-model connectivity, execute a smoke query, or resolve
citations. Its persisted `validation_level` is exactly `foundation`. A frozen snapshot created
from it is available for preview and routing development only. A failed validation raises a
value-safe error and does not persist a validation record.

The candidate digest is the canonical JSON hash of the normalized included-document manifest
inputs sorted by `document_id`: `document_id`, `revision_id`, `filename`, `content_type`,
`content_hash`, `artifact_path`, and `routing_metadata`. Excluded-state counts are intentionally
not part of the digest because they do not change the frozen retrieval corpus.

### Snapshot Manifest References Reusable Artifacts

Snapshot freeze writes one immutable `local_index.snapshot.v2` manifest. It does not copy artifact
directories and does not build a merged snapshot index.

```text
{store_root}/
  knowledge_sources/{source_id}/
    source.json
    snapshot_validations/{validation_id}.json
    snapshots/{snapshot_id}/
      snapshot.json
  artifacts/{content_hash}/{ingestion_config_fingerprint}/
    artifact_meta.json
    ...
```

The manifest references each READY revision artifact by relative path. The next runtime-routing
slice will select bounded manifest entries and load those revision artifacts individually.

### Frozen And Published Pointers Stay Separate

The Source stores:

```text
latest_snapshot_id
published_snapshot_id
```

`latest_snapshot_id` points to the most recent Frozen Knowledge Source Snapshot and is suitable for
preview and routing-smoke development. `published_snapshot_id` remains `None` in this slice and is
reserved for later formal Knowledge Source Publication. No Agent binding resolver may treat
`latest_snapshot_id` as production-bindable.

## Contracts

Extend `KnowledgeSource` with optional backward-compatible projection fields:

```python
source_draft_version_id: str | None = None
latest_snapshot_id: str | None = None
published_snapshot_id: str | None = None
```

Add frozen contracts:

```python
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


class KnowledgeSourceSnapshotDocument(FrozenModel):
    document_id: str
    revision_id: str
    filename: str
    content_type: str
    content_hash: str
    artifact_path: str
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)


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

`routing_metadata` is included from the first manifest schema even though the current active
document projection does not yet expose edits. It defaults to an empty mapping and gives the next
runtime-routing slice a stable manifest boundary.

## Store Operations

Add these `LocalAgentConfigurationStore` operations:

```python
get_candidate_knowledge_source_snapshot(source_id: str) -> CandidateKnowledgeSourceSnapshot

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

list_knowledge_source_snapshots(source_id: str) -> list[KnowledgeSourceSnapshotManifest]
```

Candidate reads, validation, and freeze use the existing store-root lock. Artifact verification
must remain optional-dependency-safe: extract the reusable sidecar compatibility check from the
LlamaIndex builder into `proof_agent.capabilities.knowledge.ingestion.artifacts`, an ingestion
artifact helper that does not import LlamaIndex.

When `complete_knowledge_ingestion_job()` moves one document into `ready`, it also advances the
Source draft token under the same store lock. Non-membership-changing transitions leave the token
unchanged.

Freeze executes in this order under the store lock:

1. load and normalize the Source draft token;
2. require the supplied passed foundation validation record;
3. re-derive the candidate projection;
4. require exact token and digest match;
5. derive deterministic `snapshot_id` from `source_id`, draft token, and candidate digest;
6. if the matching manifest already exists, validate and reuse it;
7. otherwise atomically write immutable `snapshot.json`;
8. atomically update `source.latest_snapshot_id`;
9. return the frozen manifest.

Writing the immutable manifest before the Source pointer makes replay safe: a crash may leave an
unpointed but valid frozen manifest, and a retry reuses it before repairing the pointer. The reverse
order is forbidden because it could create a pointer to a missing manifest.

The deterministic snapshot identity intentionally excludes `validation_id`. Re-validating an
unchanged candidate may create a newer passed validation record, but freeze still reuses the
existing manifest and its original `foundation_validation_id`.

## API

Add management endpoints:

```text
GET  /api/config/knowledge-sources/{source_id}/candidate-snapshot
POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/validate-foundation
POST /api/config/knowledge-sources/{source_id}/candidate-snapshot/freeze
GET  /api/config/knowledge-sources/{source_id}/snapshots
GET  /api/config/knowledge-sources/{source_id}/snapshots/{snapshot_id}
```

Validation accepts:

```json
{"actor": "local-user"}
```

Freeze accepts:

```json
{"validation_id": "ksvalidation_ab12cd34", "actor": "local-user"}
```

Knowledge Source list and detail payloads expose `source_draft_version_id`, `latest_snapshot_id`,
and `published_snapshot_id`. `published_snapshot_id` remains `null` in this slice.

There is deliberately no `/publish` endpoint yet.

## Error Rules

Add `PA_INGESTION_005` for snapshot-freeze state conflicts:

- stale validation token;
- changed candidate digest;
- validation record that belongs to another Source or validation level;
- existing deterministic snapshot id with incompatible manifest content.

Map `PA_INGESTION_005` to HTTP `409`.

Use existing errors for existing boundaries:

- unknown Source, supplied validation id, or snapshot: HTTP `404`;
- non-`local_index` Source, empty candidate, missing artifact reference, escaped artifact path, or
  incompatible artifact: `PA_INGESTION_001`, HTTP `400`;
- store-lock timeout: `PA_INGESTION_004`, HTTP `503`.

Errors remain value-safe and never include document content, secrets, or filesystem paths outside
the store boundary.

## Test Strategy

Add contract tests for JSON-safe frozen snapshot contracts and `PA_INGESTION_005`.

Add store tests proving:

- Source creation mints a draft token;
- legacy Source token normalization happens under the first candidate read;
- candidate projection is derived rather than persisted;
- only READY documents enter the candidate projection;
- job completion advances the token, while lease, retry, defer, failure, rejected upload, and purge
  transitions do not;
- foundation validation rejects empty candidates, unsafe artifact paths, missing artifacts, and
  incompatible sidecars;
- failed foundation validation does not persist a validation record;
- validation persists token and candidate digest;
- freeze rejects stale validation after a later READY transition;
- freeze writes `local_index.snapshot.v2` manifest with multiple immutable revision references;
- freeze reuses a matching snapshot after replay;
- freeze writes manifest before latest pointer and repairs an unpointed manifest after retry;
- `published_snapshot_id` stays `None`.

Add API tests for candidate summary, foundation validation, freeze, list, detail, `404`, `400`,
`409`, and store-lock `503` projection.

Keep runtime loading on `local_index.snapshot.v1` unchanged in this slice. Slice B introduces the
`v2` runtime loader and multi-document routing.

## Verification

Run:

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py \
  tests/test_knowledge_ingestion_store.py \
  tests/test_agent_configuration_api.py -q
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/ -q
uv run --extra dev --extra ingestion --extra tree ruff check proof_agent tests
uv run --extra dev --extra dashboard --extra ingestion --extra openai --extra tree mypy proof_agent
git diff --check
uv run --extra dev --extra tree proof-agent demo
```
