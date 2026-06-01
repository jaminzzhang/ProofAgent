# Local Index Ingestion Worker Foundation Design

## Scope

This slice adds the recoverable local worker foundation for Dashboard-managed `local_index`
Knowledge Sources. It persists quarantined upload validation and ingestion work, claims one task
per `proof-agent knowledge-worker --once` invocation, parses Markdown and text-based PDF originals,
builds or reuses one immutable compatible artifact, and records stable success or failure state.

This slice does not add candidate Knowledge Source snapshots, Source publication APIs, runtime
multi-document routing, batch-upload APIs, replacement uploads, document archive, Dashboard UI,
or continuous worker polling.

## Storage Boundary

`LocalAgentConfigurationStore` remains the file-backed persistence boundary. The upload API stores
one `QuarantinedKnowledgeUpload` under a system-generated path and enqueues asynchronous validation
work. It never parses a PDF, creates a Knowledge Document Revision, queues ingestion, or builds an
index synchronously. The API performs request-envelope protection only: it validates the target
`local_index` Source, rejects invalid or empty base64, checks encoded size before decoding, and
enforces the 50 MB decoded-byte limit. It does not trust or synchronously validate filename,
extension, declared MIME type, signature, UTF-8 text, or PDF structure.

Staging acquires the same store-root advisory lock used by worker transitions and atomically
checks Knowledge Source Document Capacity before writing quarantine bytes. It writes `upload.json`
plus `original-upload.bin` into a temporary sibling directory, then publishes the staged upload
with one atomic directory rename. Each queued or processing quarantine upload reserves one slot.
Accepted promotion hands that slot to the managed document, while rejection releases it
immediately even though rejected bytes remain for 24-hour troubleshooting. Managed documents plus
active reservations may never exceed 500.

The foundation endpoint stages one file per request. Dashboard V1 batch upload remains a later API
slice with a maximum of 50 files. That endpoint must reserve full-batch capacity atomically before
writing any quarantine bytes and must leave no staged files if reservation or staging
persistence fails. After successful staging, each upload proceeds independently through the same
asynchronous validator and may reach `accepted` or `rejected` separately.

```text
knowledge_sources/{source_id}/
  source.json
  quarantined_uploads/{upload_id}/
    upload.json
    original-upload.bin
  upload_promotions/{upload_id}.json
  documents/{document_id}/
    document.json
    revisions/{revision_id}/
      original.bin
      parsed-text.txt
      parser-meta.json
  ingestion_jobs/{job_id}.json
  artifacts/{content_hash}/{ingestion_config_fingerprint}/
```
```

`QuarantinedKnowledgeUpload` is a frozen intake contract with:

```text
upload_id
source_id
filename
content_type
size_bytes
storage_path
state: queued | processing | accepted | rejected
attempt_count
claimed_at
claim_token
lease_expires_at
completed_at
error_code
error_message
promoted_document_id
promoted_revision_id
ingestion_job_id
expires_at
purged_at
created_at
updated_at
```

`KnowledgeIngestionJob` is a separate frozen artifact-build contract with:

```text
job_id
source_id
document_id
revision_id
state: queued | processing | ready | failed
attempt_count
auto_retry_count
max_auto_retries
ingestion_config_fingerprint
artifact_build_spec
artifact_path
claimed_at
claim_token
lease_expires_at
completed_at
error_code
error_message
last_error_code
last_error_message
last_failure_classification
next_attempt_at
created_at
updated_at
```

Accepted quarantine validation uses Quarantined Knowledge Upload Promotion to promote the
uploaded bytes into one immutable Managed Knowledge Document Original, persist
parser-identity-bound normalized `parsed-text.txt` plus `parser-meta.json`, create the current MVP
Knowledge Document Revision projection, and enqueue one Knowledge Ingestion Job. The promoted
document, revision, and job identities are derived deterministically from `upload_id`. Rejected
uploads create neither revision nor ingestion job. Their quarantined bytes remain available only
under Rejected Knowledge Upload Retention.

The current `KnowledgeDocument` projection keeps the active revision fields used by the MVP API
and gains `ingestion_job_id` plus `artifact_path`. Full stable-document identity with immutable
revision history remains a later slice.

`KnowledgeArtifactBuildSpec` is persisted inside the ingestion job at promotion time:

```text
provider
engine_name
engine_version
parser_fingerprint_identity
content_hash
parsed_text_sha256
declared_ingestion_model
```

The spec is immutable and secret-safe. It stores credential environment-variable references but
never resolved credential values. `declared_ingestion_model` remains a frozen declaration rather
than an eagerly validated `ModelConfig`, allowing a malformed or missing declaration to create a
diagnosable job that later fails with `PA_INGESTION_001`.

Source create or update persistence runs shared recursive Secret-Safe Knowledge Configuration
Validation before writing `source.json`. Promotion runs the same validation again before writing a
build spec. Parameter names ending in `_env` are allowed; secret-bearing names such as `api_key`,
`authorization`, `bearer`, `password`, `secret`, `access_token`, and `provider_api_key` fail with
`PA_SECRET_001`. Validation reports field paths only and never echoes rejected values.

## Worker Claim And Recovery

The CLI entry point is:

```bash
uv run --extra ingestion --extra tree proof-agent knowledge-worker \
  --config-dir runs/config \
  --once
```

Each `--once` invocation claims at most one persisted task. It selects the oldest task by
`created_at` across queued or lease-expired Quarantined Knowledge Uploads and ready-to-run queued
or lease-expired Knowledge Ingestion Jobs. A queued ingestion job is ready to run only when
`next_attempt_at` is absent or no later than the current time. One invocation never validates a
quarantine upload and builds its artifact in the same process run. Oldest-ready-first scheduling
prevents continuous upload intake from starving artifact construction.

The worker uses one unified store claim operation that compares both task kinds, applies the
per-Source concurrency gate, generates the claim token, and persists the selected transition
while holding the same store-root advisory lock. It does not peek one queue and later claim from
another, which would make oldest-ready-first selection race-prone.

Claiming increments `attempt_count`, generates a fresh opaque `claim_token`, and records
`claimed_at` plus `lease_expires_at`. Quarantine validation moves the upload to `processing`.
Artifact build moves both ingestion job and document projection to `processing`. Every renew,
accept, reject, complete, reschedule, or fail transition requires the current claim token; a stale
worker may not commit state after its token is replaced by lease recovery.

Claim selection applies one per-Source concurrency gate under the same advisory lock. Read
`params.worker_concurrency`, default it to 2, and reject values outside 1 through 8. Count
non-expired `processing` quarantine-validation and artifact-build tasks for that Source. When a
Source reaches its limit, skip its ready tasks and continue oldest-ready-first selection among
eligible tasks from other Sources. Worker concurrency affects scheduling only and does not
participate in artifact fingerprinting.

Source configuration persistence validates `params.worker_concurrency` as an integer from 1
through 8 and rejects invalid values with `PA_INGESTION_001`. Claim repeats that check
defensively for manually altered or legacy `source.json` files. It does not silently clamp an
invalid value or let one malformed Source block eligible work from other Sources: it skips that
Source, continues selection, and reports one stable configuration-error worker result for
operator diagnosis. A later Dashboard slice may project the same condition as a Source warning.

`KnowledgeWorkerClaimSelection` is the store-to-worker envelope with an optional claimed task plus
zero or more value-safe diagnostics. `KnowledgeWorkerResult` is the corresponding one-shot
worker-to-CLI envelope with an optional task outcome plus diagnostics. Unified claim collects one
`PA_INGESTION_001` diagnostic per malformed Source while continuing selection. A diagnostic
contains only `source_id`, stable error code, and a short message; it never echoes parameter
values. If a valid task exists, the worker executes it and returns both its outcome and the
diagnostics. If no valid task exists but diagnostics do, it returns a diagnostics-only result.
CLI prints diagnostics before an outcome and does not print `no queued knowledge tasks` while
diagnostics exist.

The local file-backed store serializes claim selection and state writes with an OS-level advisory
lock under the store root. This prevents two concurrently started `--once`
processes from claiming the same job. A future distributed queue adapter replaces this local lock
boundary without changing the ingestion-job state machine.

The foundation implements local-filesystem synchronization with `filelock.FileLock`. Store
transitions acquire `{store_root}/.locks/store.lock` with a 5-second blocking timeout. Timeout
fails the current API or CLI operation with `PA_INGESTION_004`; because the store lock is
unavailable, the caller does not attempt another state write. Artifact builds acquire
`{store_root}/.locks/artifacts/{sha256(artifact_key)}.lock` with `timeout=0`; housekeeping attempts
that same lock non-blockingly. Lock files remain outside atomically renamed artifact
directories. Artifact temporary directories are sibling paths on the same filesystem as their
final directories so `os.replace()` publication stays atomic. Shared NFS and distributed locking
remain outside this foundation and belong to a later queue adapter.

Before task claim, every `--once` invocation performs bounded housekeeping without consuming its
one-task allowance. It deletes quarantined bytes for rejected uploads whose `expires_at` is no
later than the current time and records `purged_at` while retaining the minimal rejected-upload
status record and stable error metadata. It also removes stale sibling artifact-build temporary
directories left by interrupted workers only after non-blockingly acquiring the corresponding
artifact-key advisory lock. Temporary directories carry their artifact key and creation time.
Active builds retain that lock and cannot be removed by age alone.

A successful quarantine validation performs one replay-safe promotion under the advisory lock.
It writes the managed original, parsed text, parser metadata, document projection, and queued job
through temporary files plus atomic `os.replace()` operations, then atomically writes
`upload_promotions/{upload_id}.json` as the final durable commit marker. Only a job with that marker
is visible to ingestion-job claim. The upload then moves to `accepted`, records the promoted
identities, and records `completed_at`.

If a process exits before the marker write, lease recovery overwrites the same deterministic
promotion paths and cannot create duplicate document, revision, or job identities. If it exits
after the marker write but before the upload state update, recovery reads the marker and repairs
the upload projection without repeating promotion. Successful promotion removes
`original-upload.bin` after the managed original and commit marker are durable, avoiding a
duplicate long-lived byte copy. A rejected upload moves to `rejected`, records one stable
validation error plus `expires_at = rejected_at + 24h`, and creates no revision or ingestion job.

A worker first validates whether `{content_hash}/{ingestion_config_fingerprint}` already contains
a complete compatible reusable artifact sidecar plus the required LlamaIndex persistence files. A
cache hit moves both job and document projection to `ready`, persists the artifact reference, and
skips model-backed rebuilding.

On cache miss, the builder attempts an advisory lock scoped to the artifact key non-blockingly.
Contention returns a defer signal rather than waiting or reporting a build failure. After lock
acquisition, the builder validates the cache again and reuses a compatible artifact without a
model call if another worker published it first. Otherwise the builder writes all LlamaIndex files
into a sibling temporary directory, writes `artifact_meta.json` last, validates the completed
temporary artifact, and atomically renames the complete directory into its final content-addressed
path. Workers never write directly to a final artifact directory and never reuse a partial artifact.

The worker renews its persisted task lease at phase boundaries. The builder receives a renewal
callback and passes it into `ProofAgentLLM(role=INGESTION)`. The bridge invokes it before and after
each synchronous `complete()` or `chat()` provider call and writes the configured timeout into
`ModelRequest.timeout_seconds`. The new bridge arguments remain optional so runtime retrieval
behavior is unchanged. If a task lease genuinely expires, another worker may reclaim it with a new
claim token. If renewal fails, the stale worker immediately stops before starting another provider
call, publishing an artifact, or updating job or document state. If the lease expires during an
already-started bounded provider call or atomic rename, a completed compatible artifact may remain
published under the artifact-key lock; the new owner validates and reuses it.

Artifact-build failure classification is explicit. Model timeout, transient rate limit, and
temporary network failures are recoverable. After the initial failed attempt, a recoverable job
is requeued with persisted `last_error_*`, `last_failure_classification`, `auto_retry_count`, and
`next_attempt_at`. The default retry schedule is 30 seconds and then 120 seconds, giving at most 2
automatic retries and 3 total build attempts. `attempt_count` counts claims, while
`auto_retry_count` alone counts recoverable build failures and enforces the retry limit.
Artifact-key lock contention is expected deduplication behavior, not a build failure: defer the
token-owned job back to `queued` with `next_attempt_at = now + 5s`, do not increment
`auto_retry_count`, and let a later worker recheck cache. Missing or malformed configuration,
missing credentials, parser failures, and unclassified failures are non-recoverable and move
directly to `failed`. Exhausted recoverable jobs also move to `failed`. Terminal failure stores
only a stable error code plus a short operator-facing message. No failure persists a traceback.

Lease recovery handles worker-process interruption. Persisted `next_attempt_at` means restart
does not bypass retry backoff.

## Parser Boundary

Document parsing is isolated behind:

```python
class KnowledgeDocumentParser(Protocol):
    @property
    def parser_metadata(self) -> ParserMetadata: ...
    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument: ...
```

The quarantine validator parser registry supports:

- UTF-8 Markdown with fingerprint identity `markdown:utf-8:v1`
- text-based PDF with fingerprint identity `pypdf:v1@{installed_version}`

Before parser selection, the asynchronous validator verifies filename-extension, declared-MIME,
and content-signature consistency. Unsupported, mismatched, malformed, encrypted, oversized,
scanned, executable, or otherwise rejected files remain quarantine-only records under Rejected
Knowledge Upload Retention. They never become Managed Knowledge Document Originals, revisions, or
ingestion jobs.

The PDF parser uses `pypdf>=6.12.2,<7`. It rejects malformed PDFs, encrypted PDFs, PDFs above
500 pages, and PDFs with no meaningful extracted text. It relies on `pypdf` font-encoding and CMap
handling to extract supported PDF text into normalized Unicode, so PDF text is not restricted to
one source encoding. Scanned PDF and OCR ingestion remain outside V1 intake.

`parser-meta.json` records structured parser provenance:

```json
{
  "adapter": "pypdf",
  "adapter_contract_version": "1",
  "library_version": "6.12.2",
  "fingerprint_identity": "pypdf:v1@6.12.2",
  "parsed_text_sha256": "..."
}
```

The exact fingerprint identity participates in artifact compatibility. A `pypdf` upgrade may
change extraction output, so newly parsed uploads do not silently reuse artifacts produced from
another installed parser version. Persisted Parsed Knowledge Document Text remains bound to the
parser metadata used when that derivative was created.

`pypdf` belongs to a new `ingestion` optional dependency group rather than the runtime `tree`
group. Read-only runtime load should not depend on document parsing packages.

### Why Not Docling Yet

Docling is a strong future parser adapter for layout-aware extraction, tables, formulas, images,
OCR, and additional office formats. It is not the default parser in this foundation slice because
the current V1 intake intentionally rejects scanned PDFs and accepts only Markdown plus text-based
PDF. Docling's standard PDF pipeline can involve layout, table, OCR, and model-weight concerns that
expand installation and runtime requirements beyond the current fail-closed parser contract.

Parser fingerprint identity participates in the ingestion fingerprint. A future Source
configuration may select an identity such as `docling:standard:v1@{installed_version}`; changing
parser identity will invalidate incompatible cached artifacts and trigger incremental reingestion
rather than silently reusing old output.

Quarantine validation persists normalized Parsed Knowledge Document Text with the accepted
revision. Artifact construction consumes that derivative rather than reparsing the original. The
derivative is managed storage for reingestion and audit-safe operations; it is not written to
runtime Trace or treated as an index artifact.

## Artifact Build

The worker validates the job-owned immutable `KnowledgeArtifactBuildSpec.declared_ingestion_model`
through one shared helper using the existing `ModelConfig` contract. It resolves credential
environment-variable values only at execution time and never persists those values. It passes the
validated config plus build spec to a single-revision Local Index artifact builder. The builder
resolves the model provider, wraps it with
`ProofAgentLLM(role=INGESTION)`, and writes LlamaIndex native persistence plus:

```json
{
  "schema_version": "local_index.artifact.v1",
  "provider": "local_index",
  "engine_name": "llama-index-tree",
  "engine_version": "llama-index-tree@0.14.22",
  "parser_identity": "pypdf:v1@6.12.2",
  "content_hash": "...",
  "ingestion_config_fingerprint": "..."
}
```

This reusable artifact sidecar is distinct from the published READY snapshot sidecar validated by
runtime load. It intentionally excludes Source, document, and revision identity. Each ready
document projection and ingestion job persists a Knowledge Revision Artifact Reference through
`artifact_path`, preserving revision provenance without duplicating artifact bytes.

The ingestion configuration fingerprint is a stable SHA-256 digest computed from artifact-affecting
`KnowledgeArtifactBuildSpec` inputs: declared ingestion-model configuration, parser fingerprint
identity, provider name, engine name, and exact runtime engine version. Routing-model settings do
not participate. The engine version is read from the installed `llama-index-core` package at
runtime rather than hard-coded to the broad dependency floor; for example,
`llama-index-tree@0.14.22`.

Accepted quarantine validation freezes the artifact-affecting declaration into one
`KnowledgeArtifactBuildSpec` and computes the fingerprint from that snapshot without treating the
digest operation as model-configuration validation. The immutable revision original's content hash
independently selects the artifact cache path. Parsed Knowledge Document Text records its own
derivative hash for integrity verification, not cache identity. A missing or malformed
`ingestion_model` can still produce a persisted ingestion job identity; the artifact worker then
fails that job with `PA_INGESTION_001`. Later Source Draft edits do not mutate the queued build
spec, fingerprint, or artifact path. This keeps intake handling limited to quarantine staging
while preserving a stable queue record for operator diagnosis.

Worker tests inject a fake builder so the default test suite remains deterministic, fast, and
network-free. Tests for real Markdown and PDF parser behavior run with the `ingestion` extra.

## API And CLI

The existing upload endpoint stages a quarantined upload:

```text
POST /api/config/knowledge-sources/{source_id}/documents
```

Its response is a Quarantined Knowledge Upload payload. The accepted upload later produces a
Knowledge Document payload with `ingestion_job_id`.

New read-only endpoints expose operational job state:

```text
GET /api/config/knowledge-sources/{source_id}/quarantined-uploads
GET /api/config/knowledge-sources/{source_id}/quarantined-uploads/{upload_id}
GET /api/config/knowledge-sources/{source_id}/ingestion-jobs
GET /api/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}
```

The CLI prints one of:

```text
knowledge upload accepted: upload_ab12cd34
knowledge upload rejected: upload_ab12cd34 (PA_INGESTION_002)
knowledge ingestion job ready: job_ab12cd34
knowledge ingestion job retry scheduled: job_ab12cd34 (PA_INGESTION_003)
knowledge ingestion job deferred: job_ab12cd34
knowledge ingestion job failed: job_ab12cd34 (PA_INGESTION_003)
knowledge worker warning: ks_policy (PA_INGESTION_001)
no queued knowledge tasks
```

## Failure Codes

- `PA_INGESTION_001`: Source ingestion configuration is missing or invalid.
- `PA_INGESTION_002`: The quarantined upload is malformed, encrypted, oversized, scanned, or unsupported.
- `PA_INGESTION_003`: Local Index artifact build failed.
- `PA_INGESTION_004`: Job state transition or persistence failed.

Failures preserve the previous published READY snapshot because this slice does not mutate or
publish snapshots.

## Testing

- Uploading Markdown or PDF stores one quarantined upload and creates no revision or ingestion job.
- Invalid base64, empty content, or a request-envelope size violation fails synchronously without
  storing quarantine bytes.
- Pending quarantine reservations count toward the 500-document Source limit; concurrent staging
  cannot exceed capacity, and rejection releases a reservation immediately.
- Single-file staging publishes `upload.json` and quarantined bytes together through an atomic
  temporary-directory rename, leaving no half-staged reservation.
- Unsupported type, MIME-signature mismatch, invalid Markdown UTF-8, and malformed PDF bytes first
  enter quarantine and are rejected asynchronously without revision or ingestion-job creation.
- `--once` claims no more than one quarantine-validation or ingestion task.
- Unified claim compares both task kinds and persists one selected transition atomically, so
  concurrent workers cannot violate oldest-ready-first selection through a peek-then-claim race.
- Oldest-ready-first selection allows an older ingestion job to run while newer quarantine
  uploads continue arriving.
- Per-Source concurrency defaults to 2, accepts bounded values from 1 through 8, counts non-expired
  processing quarantine-validation and artifact-build tasks, skips a capped Source while another
  Source can progress, and does not affect artifact fingerprinting.
- Invalid persisted `worker_concurrency` is rejected during normal Source writes; defensive
  claim-time validation skips a manually altered or legacy malformed Source, reports
  `PA_INGESTION_001`, and still allows valid Sources to progress without silent clamping.
- Worker results return value-safe malformed-Source diagnostics alongside an optional task
  outcome; CLI prints warnings first and suppresses no-task text when diagnostics exist.
- Accepted validation creates one immutable original, revision, and queued ingestion job.
- Accepted validation persists normalized parsed text and parser metadata for artifact build reuse.
- Promotion retries before the commit marker overwrite deterministic paths and create no duplicate
  revision or ingestion job.
- An ingestion job is not claimable until its upload-promotion commit marker exists.
- Recovery after marker persistence repairs an incomplete accepted-upload projection without
  repeating promotion.
- Successful promotion removes duplicate quarantine bytes after the managed original is durable.
- Rejected validation creates no revision or ingestion job.
- Rejected bytes remain available before `expires_at`, then worker housekeeping removes them and
  records `purged_at` without deleting the minimal status record.
- Housekeeping removes stale interrupted artifact-build temporary directories without deleting
  published artifacts, and it never age-only deletes a temporary directory whose artifact-key
  lock is held by an active builder.
- Store and artifact-key synchronization use `filelock.FileLock` paths outside renamed artifact
  directories; store waits time out after 5 seconds with `PA_INGESTION_004`, artifact build and
  housekeeping lock attempts are non-blocking, and artifact temporary directories remain siblings
  on the same local filesystem as their final paths.
- A lease-expired processing task can be reclaimed after worker restart.
- Lease renewal keeps a long-running claimed task owned across phase boundaries and bounded model
  calls; a stale replaced claim token cannot accept, reject, complete, reschedule, or fail state.
- Renewal failure stops the stale worker before any later provider call or artifact publication,
  while an artifact completed during an already-started bounded call or atomic rename remains
  reusable by the new owner.
- Markdown and text-based PDF parsers return normalized text.
- Text-based PDF fixtures with multiple extractable font-encoding or CMap forms normalize to
  Unicode text without manual raw-byte decoding.
- Encrypted, malformed, over-500-page, and no-text PDFs fail closed.
- A successful fake build writes ready state and artifact identity to job and document records.
- A compatible existing artifact completes a job through reference reuse without invoking the
  builder, including after a lease-expired worker task is reclaimed.
- Concurrent jobs with the same artifact key perform at most one model-backed build; the second
  worker rechecks the cache after acquiring the artifact-key lock.
- Half-written artifact directories are never cache hits, and artifact publication becomes visible
  only after validated atomic directory rename.
- A failed fake build records one stable code and short message without a traceback.
- A recoverable build failure is requeued with persisted 30-second then 120-second backoff; worker
  restart does not run it before `next_attempt_at`.
- Artifact-key lock contention defers the token-owned job for 5 seconds without incrementing
  `auto_retry_count`; a later worker rechecks cache before building.
- A third recoverable build failure reaches terminal `failed`, while non-recoverable failures skip
  automatic retry.
- Fingerprints change when artifact-affecting parser or ingestion-model configuration changes.
- Exact installed LlamaIndex engine identity changes artifact compatibility and is read at runtime
  rather than inferred from the broad dependency floor.
- Exact PDF parser-version identity changes artifact compatibility, while persisted parsed text
  remains bound to its original structured parser metadata.
- Artifact cache identity uses immutable original revision content hash plus ingestion fingerprint;
  parsed-text SHA-256 verifies derivative integrity without replacing revision identity.
- Queued build specs remain immutable after later Source Draft edits; fingerprinting and actual
  artifact construction consume the same persisted declaration snapshot.
- Credential values are resolved from environment-variable references only during worker
  execution and never persisted in build specs, jobs, artifacts, or failure metadata.
- Nested raw secret-bearing Source or build-spec params fail with `PA_SECRET_001` before
  persistence, while `*_env` references remain allowed and rejected values never appear in errors.
- The default demo and default CI remain independent of the `ingestion` extra.
