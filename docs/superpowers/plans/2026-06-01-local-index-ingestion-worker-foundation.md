# Local Index Ingestion Worker Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recoverable file-backed worker that validates quarantined Dashboard uploads, stages accepted Local Index document revisions, and builds or reuses one immutable compatible artifact per `proof-agent knowledge-worker --once` invocation.

**Architecture:** Keep quarantined-upload and ingestion-job state in `LocalAgentConfigurationStore`, serialize claims with a local advisory lock, and isolate parsing plus LlamaIndex artifact construction behind focused ingestion modules. The upload API stores quarantined bytes only; one-shot workers validate quarantine tasks before creating revisions and later reuse or build content-addressed accepted-revision artifacts.

**Tech Stack:** Python 3.12, Pydantic frozen contracts, Typer, FastAPI, `filelock>=3.29.0,<4`, `pypdf>=6.12.2,<7`, LlamaIndex TreeIndex, pytest, Ruff, mypy

---

## File Map

**Create:**
- `proof_agent/capabilities/knowledge/ingestion/__init__.py` - public ingestion exports.
- `proof_agent/capabilities/knowledge/ingestion/contracts.py` - parser and builder DTOs/protocols.
- `proof_agent/capabilities/knowledge/ingestion/configuration.py` - Source ingestion-model validation.
- `proof_agent/capabilities/knowledge/ingestion/fingerprint.py` - stable artifact fingerprint calculation.
- `proof_agent/capabilities/knowledge/ingestion/parsers.py` - Markdown and lazy-imported `pypdf` parsers.
- `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py` - single-revision LlamaIndex artifact builder.
- `proof_agent/capabilities/knowledge/ingestion/worker.py` - one-job worker orchestration.
- `proof_agent/configuration/file_locking.py` - bounded local-filesystem store and artifact-key lock helpers.
- `tests/test_knowledge_ingestion_fingerprint.py`
- `tests/test_knowledge_document_parsers.py`
- `tests/test_knowledge_ingestion_store.py`
- `tests/test_knowledge_ingestion_worker.py`
- `tests/test_local_index_revision_builder.py`

**Modify:**
- `pyproject.toml` - add base `filelock` plus the `ingestion` optional dependency group.
- `uv.lock` - lock `filelock` and `pypdf`.
- `proof_agent/errors.py` - register stable `PA_INGESTION_001` through `PA_INGESTION_004`.
- `proof_agent/bootstrap/validation.py` - share recursive secret-safe parameter validation.
- `proof_agent/capabilities/models/llama_index_bridge.py` - add optional bounded-call timeout and progress callback support.
- `proof_agent/contracts/agent_configuration.py` - add `QuarantinedKnowledgeUpload` and `KnowledgeIngestionJob`; extend the current document projection.
- `proof_agent/contracts/__init__.py` - export the new contracts.
- `proof_agent/configuration/local_store.py` - persist, claim, complete, and fail quarantine and ingestion tasks.
- `proof_agent/delivery/configuration_api.py` - stage quarantined uploads and expose read-only task endpoints.
- `proof_agent/delivery/cli.py` - add `knowledge-worker --once`.
- `tests/test_agent_configuration_contracts.py`
- `tests/test_agent_configuration_store.py`
- `tests/test_agent_configuration_api.py`
- `tests/test_cli.py`
- `tests/test_proof_agent_llm.py`
- `docs/developer-guide.md`
- `docs/development-progress.md`
- `docs/technical-design.md`

## Task 1: Dependency And Frozen Contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `proof_agent/errors.py`
- Modify: `proof_agent/bootstrap/validation.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `tests/test_agent_configuration_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests that construct and serialize:

```python
upload = QuarantinedKnowledgeUpload(
    upload_id="upload_001",
    source_id="ks_policy",
    filename="policy.pdf",
    content_type="application/pdf",
    size_bytes=1024,
    storage_path="knowledge_sources/ks_policy/quarantined_uploads/upload_001/original-upload.bin",
    state="queued",
    attempt_count=0,
    created_at="2026-06-01T00:00:00Z",
    updated_at="2026-06-01T00:00:00Z",
)
job = KnowledgeIngestionJob(
    job_id="job_001",
    source_id="ks_policy",
    document_id="doc_001",
    revision_id="rev_001",
    state="queued",
    attempt_count=0,
    ingestion_config_fingerprint="fingerprint",
    artifact_build_spec=KnowledgeArtifactBuildSpec(
        provider="local_index",
        engine_name="llama-index-tree",
        engine_version="llama-index-tree@0.14.22",
        parser_fingerprint_identity="pypdf:v1@6.12.2",
        content_hash="original-sha256",
        parsed_text_sha256="parsed-text-sha256",
        declared_ingestion_model={
            "provider": "openai",
            "name": "gpt-4.1-mini",
            "params": {"api_key_env": "OPENAI_API_KEY"},
        },
    ),
    created_at="2026-06-01T00:00:00Z",
    updated_at="2026-06-01T00:00:00Z",
)
assert job.artifact_path is None
assert job.claimed_at is None
assert job.completed_at is None
```

Also assert `KnowledgeDocument` defaults `ingestion_job_id` and `artifact_path` to `None`, and
assert mutating `upload.state` or `job.state` raises `ValidationError`. Add recursive secret-safe
validation tests proving nested raw credential fields fail with `PA_SECRET_001`, nested `*_env`
references remain allowed, and rejection messages contain field paths but not values.

- [ ] **Step 2: Verify the contract tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py -q
```

Expected: FAIL because the new task contracts are not exported.

- [ ] **Step 3: Implement the contracts and error codes**

Add `PA_INGESTION_001` through `PA_INGESTION_004` to `ErrorCode`.

Add the frozen contracts:

```python
class KnowledgeArtifactBuildSpec(FrozenModel):
    provider: str
    engine_name: str
    engine_version: str
    parser_fingerprint_identity: str
    content_hash: str
    parsed_text_sha256: str
    declared_ingestion_model: Mapping[str, Any] | None = None

class QuarantinedKnowledgeUpload(FrozenModel):
    upload_id: str
    source_id: str
    filename: str
    content_type: str
    size_bytes: int
    storage_path: str
    state: str
    attempt_count: int = 0
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    promoted_document_id: str | None = None
    promoted_revision_id: str | None = None
    ingestion_job_id: str | None = None
    expires_at: str | None = None
    purged_at: str | None = None
    created_at: str
    updated_at: str

class KnowledgeIngestionJob(FrozenModel):
    job_id: str
    source_id: str
    document_id: str
    revision_id: str
    state: str
    attempt_count: int = 0
    auto_retry_count: int = 0
    max_auto_retries: int = 2
    ingestion_config_fingerprint: str
    artifact_build_spec: KnowledgeArtifactBuildSpec
    artifact_path: str | None = None
    claimed_at: str | None = None
    claim_token: str | None = None
    lease_expires_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    last_failure_classification: str | None = None
    next_attempt_at: str | None = None
    created_at: str
    updated_at: str
```

Extend `KnowledgeDocument` with optional `ingestion_job_id` and `artifact_path`, then export both
task types plus `KnowledgeArtifactBuildSpec` from `proof_agent.contracts`. Add typed
`KnowledgeWorkerDiagnostic`, `KnowledgeWorkerClaimSelection`, `KnowledgeWorkerTaskOutcome`, and
`KnowledgeWorkerResult` contracts. `KnowledgeWorkerClaimSelection` is the store-to-worker envelope
containing an optional claimed task plus value-safe diagnostics. `KnowledgeWorkerResult` is the
one-shot worker-to-CLI envelope containing an optional task outcome plus those diagnostics, so one
invocation can report accepted or rejected quarantine, ready or failed artifact build, scheduled
retry, and malformed-Source warnings without echoing parameter values.

- [ ] **Step 4: Add and lock the parser dependency**

Add:

```toml
dependencies = [
  # existing dependencies
  "filelock>=3.29.0,<4",
]
ingestion = ["pypdf>=6.12.2,<7"]
all = ["proof-agent[ingestion,openai,tree]"]
```

Run:

```bash
uv lock
```

- [ ] **Step 5: Verify the contract tests pass**

Run the Task 1 pytest command again.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock proof_agent/errors.py proof_agent/bootstrap/validation.py \
  proof_agent/contracts/agent_configuration.py proof_agent/contracts/__init__.py \
  tests/test_agent_configuration_contracts.py
git commit -m "Add knowledge ingestion job contracts"
```

## Task 2: Fingerprint And Parser Adapters

**Files:**
- Create: `proof_agent/capabilities/knowledge/ingestion/__init__.py`
- Create: `proof_agent/capabilities/knowledge/ingestion/contracts.py`
- Create: `proof_agent/capabilities/knowledge/ingestion/configuration.py`
- Create: `proof_agent/capabilities/knowledge/ingestion/fingerprint.py`
- Create: `proof_agent/capabilities/knowledge/ingestion/parsers.py`
- Create: `tests/test_knowledge_ingestion_fingerprint.py`
- Create: `tests/test_knowledge_document_parsers.py`

- [ ] **Step 1: Write failing fingerprint tests**

Cover stable output and artifact-affecting changes:

```python
first = ingestion_config_fingerprint(build_spec)
second = ingestion_config_fingerprint(build_spec)
assert first == second
assert first != ingestion_config_fingerprint(changed_ingestion_model_build_spec)
assert first != ingestion_config_fingerprint(changed_parser_build_spec)
assert first != ingestion_config_fingerprint(changed_engine_version_build_spec)
```

Assert routing-model-only changes do not change the digest.

- [ ] **Step 2: Write failing parser tests**

Cover:
- UTF-8 Markdown normalization.
- Text PDF extraction.
- PDF extraction fixtures with multiple supported font-encoding or CMap forms normalizing to
  Unicode text.
- Extension, declared-MIME, and content-signature mismatch rejection.
- Unsupported or executable-content rejection.
- Malformed PDF rejection.
- Encrypted PDF rejection.
- Blank/no-text PDF rejection.
- 501-page PDF rejection.

Generate small PDFs inside the tests with `pypdf.PdfWriter`; add a helper that writes one text
content stream for the successful extraction fixture. Assert parser failures use
`PA_INGESTION_002`. Mark PDF-specific tests to skip when the optional `pypdf` package is not
installed; the dedicated ingestion-extra verification must execute them.

- [ ] **Step 3: Verify the focused tests fail**

Run:

```bash
uv run --extra dev --extra ingestion --extra tree python -m pytest \
  tests/test_knowledge_ingestion_fingerprint.py \
  tests/test_knowledge_document_parsers.py -q
```

Expected: FAIL because ingestion modules do not exist.

- [ ] **Step 4: Implement typed parser contracts and fingerprint**

Add:

```python
@dataclass(frozen=True)
class ParserMetadata:
    adapter: str
    adapter_contract_version: str
    library_version: str | None
    fingerprint_identity: str
    parsed_text_sha256: str | None = None

@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    text: str
    page_count: int | None
    parser_metadata: ParserMetadata

class KnowledgeDocumentParser(Protocol):
    @property
    def parser_metadata(self) -> ParserMetadata: ...
    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument: ...
```

Canonicalize only the persisted `KnowledgeArtifactBuildSpec` declaration's ingestion model,
parser fingerprint identity, provider name, engine name, and engine version into sorted JSON
before SHA-256 hashing. The original content hash remains the independent artifact-path key.
Read the exact installed LlamaIndex engine identity at runtime, for example
`llama-index-tree@0.14.22` from `importlib.metadata.version("llama-index-core")`; do not fingerprint
the broad dependency floor.

Add:

```python
def local_index_engine_version() -> str:
    ...

def ingestion_model_config_from_build_spec(spec: KnowledgeArtifactBuildSpec) -> ModelConfig:
    ...
```

Normalize missing or malformed `declared_ingestion_model` to `PA_INGESTION_001`. Resolve
environment-variable credential values only through provider resolution during worker execution;
never persist resolved values.

- [ ] **Step 5: Implement Markdown and PDF parsers**

Keep `pypdf` import inside the PDF parser path so importing Proof Agent without the `ingestion`
extra still works. Persist structured parser metadata with adapter name, adapter contract version,
installed library version, and exact fingerprint identity such as `pypdf:v1@6.12.2`. Use
`pypdf` font-encoding and CMap extraction rather than manually decoding PDF content streams. Add an
asynchronous quarantine-validator registry that checks filename extension, declared MIME type,
and content signature consistently before parser promotion. Normalize validator and parser
failures into:

```python
ProofAgentError(
    "PA_INGESTION_002",
    "...",
    "Upload a supported UTF-8 Markdown file or a text-based, unencrypted PDF up to 500 pages.",
)
```

- [ ] **Step 6: Verify parser tests pass**

Run the Task 2 pytest command again.

- [ ] **Step 7: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion tests/test_knowledge_ingestion_fingerprint.py \
  tests/test_knowledge_document_parsers.py
git commit -m "Add local index ingestion parser adapters"
```

## Task 3: File-Backed Queue Store

**Files:**
- Create: `proof_agent/configuration/file_locking.py`
- Modify: `proof_agent/configuration/local_store.py`
- Create: `tests/test_knowledge_ingestion_store.py`
- Modify: `tests/test_agent_configuration_store.py`

- [ ] **Step 1: Write failing store tests**

Cover:
- staging stores quarantined bytes and one queued upload-validation record;
- store locks use `{store_root}/.locks/store.lock` with a finite blocking timeout;
- artifact-key locks use `{store_root}/.locks/artifacts/{sha256(artifact_key)}.lock`, outside
  atomically renamed artifact directories;
- staging reserves Source document capacity under the queue lock and atomically publishes one
  temporary upload directory containing bytes and record;
- managed documents plus queued or processing quarantine reservations cannot exceed 500, including
  under concurrent staging;
- Source `params.worker_concurrency` defaults to 2, requires an integer from 1 through 8, rejects
  invalid values with `PA_INGESTION_001` before Source persistence, and affects scheduling without
  changing artifact fingerprinting;
- rejection releases its reservation immediately even while quarantine bytes remain retained;
- accepted promotion hands its reservation to the managed document without changing occupied
  capacity;
- staging creates neither a document revision nor an ingestion job;
- quarantine listing returns creation order;
- quarantine claim moves one upload to `processing`, increments `attempt_count`, and creates one
  opaque claim token with a persisted lease expiry;
- quarantine claim renewal extends only the matching token's lease;
- a stale quarantine claimant cannot accept or reject after lease recovery replaces its token;
- accepted quarantine validation creates one immutable original, normalized parsed-text derivative,
  parser metadata, queued document revision, and queued ingestion job with an immutable
  secret-safe `KnowledgeArtifactBuildSpec`;
- promotion applies recursive secret-safe validation before build-spec persistence and never
  stores or echoes rejected raw credential values;
- accepted promotion derives stable document, revision, and job identities from `upload_id`;
- interrupted promotion before its atomic commit marker is replayable without duplicate revision
  or job creation;
- interrupted promotion after its marker repairs the accepted-upload projection without repeating
  promotion;
- a queued ingestion job without its upload-promotion marker is not claimable;
- later Source Draft edits do not change a queued job's build spec, fingerprint, or artifact path;
- accepted promotion removes the duplicate quarantined-byte copy after the managed original is
  durable;
- rejected quarantine validation creates no revision or ingestion job;
- rejected quarantine bytes remain available before `expires_at`, then housekeeping deletes bytes
  and records `purged_at` while retaining the minimal status record;
- listing jobs returns creation order;
- claim moves job and document to `processing`, increments `attempt_count`, and creates one opaque
  claim token with a persisted lease expiry;
- a second claim skips a non-expired processing job;
- an expired processing lease is reclaimable;
- job claim renewal extends only the matching token's lease;
- a stale job claimant cannot complete, reschedule, or fail after lease recovery replaces its
  token;
- claims count non-expired `processing` quarantine-validation and artifact-build tasks together
  against the Source concurrency limit;
- oldest-ready-first selection skips a capped Source and continues with an eligible task from
  another Source;
- defensive claim-time validation skips a manually altered or legacy Source with invalid
  `worker_concurrency`, reports stable `PA_INGESTION_001`, and still allows another Source to
  progress without silently clamping;
- unified claim returns one value-safe diagnostic per malformed Source alongside any selected
  task, or diagnostics alone when no valid task is claimable;
- one unified claim compares quarantine-validation and artifact-build tasks and persists the
  selected transition atomically, avoiding a peek-then-claim race between queues;
- a queued retry is not claimable before persisted `next_attempt_at`;
- a ready document and job store an artifact reference without copying reusable artifact bytes;
- completion writes ready state and artifact path;
- rescheduling a recoverable failure preserves stable last-error metadata and clears the active
  claim;
- artifact-key lock contention defers the token-owned job for 5 seconds without incrementing
  `auto_retry_count`;
- `attempt_count` counts claims, while only `auto_retry_count` counts recoverable build failures
  against `max_auto_retries`;
- store-lock timeout fails with `PA_INGESTION_004` without attempting another state write;
- failure writes stable code and short message without traceback text;
- completion from a non-processing state raises `PA_INGESTION_004`.

- [ ] **Step 2: Verify the store tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_agent_configuration_store.py \
  tests/test_knowledge_ingestion_store.py -q
```

Expected: FAIL because queue store methods do not exist.

- [ ] **Step 3: Implement staging and job persistence**

Add:

```python
def stage_quarantined_knowledge_upload(...) -> QuarantinedKnowledgeUpload
def count_reserved_knowledge_document_slots(...)
def get_quarantined_knowledge_upload(...)
def list_quarantined_knowledge_uploads(...)
def claim_next_quarantined_knowledge_upload(..., lease_seconds: int = 300) -> QuarantinedKnowledgeUpload | None
def renew_quarantined_knowledge_upload_claim(..., claim_token: str, lease_seconds: int = 300) -> QuarantinedKnowledgeUpload
def accept_quarantined_knowledge_upload(...) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]
def reject_quarantined_knowledge_upload(...)
def purge_expired_quarantined_upload_bytes(...)
def get_knowledge_ingestion_job(...)
def list_knowledge_ingestion_jobs(...)
def claim_next_knowledge_worker_task(..., lease_seconds: int = 300) -> KnowledgeWorkerClaimSelection
```

Staging checks and reserves Knowledge Source Document Capacity under the same store-root advisory
lock used by worker transitions. Count managed documents plus queued or processing quarantine
reservations; never exceed 500. Write quarantine bytes plus `upload.json` to a temporary sibling
directory and publish the staged upload with one atomic rename, leaving no half-written
reservation. Acceptance derives document, revision, and job ids
deterministically from `upload_id`, promotes
the original under its immutable revision storage path, persists normalized `parsed-text.txt` and
`parser-meta.json`, computes parser identity from the parser result, and calls
`ingestion_config_fingerprint()` from a persisted secret-safe `KnowledgeArtifactBuildSpec` without
treating fingerprint calculation as model-config validation. Freeze declared ingestion-model
configuration and environment-variable references only; do not resolve or persist credential
values. Apply shared recursive Secret-Safe Knowledge Configuration Validation before build-spec
persistence and report rejected field paths without values. Write promotion files through
temporary files plus atomic `os.replace()`, then write
`upload_promotions/{upload_id}.json` as the final durable commit marker. Recovery before that
marker overwrites the same deterministic paths; recovery after it repairs the accepted-upload
projection from the marker. After the managed original and marker are durable, remove the
duplicate quarantine bytes. Rejection sets `expires_at` to 24 hours after rejection;
`purge_expired_quarantined_upload_bytes()` removes expired quarantined bytes and writes `purged_at`
while retaining the minimal rejected-upload record. Accepted promotion hands its reservation to
the managed document; rejection releases its reservation immediately.

Implement `proof_agent/configuration/file_locking.py` around `filelock.FileLock`:

```python
@contextmanager
def locked(path: Path, *, timeout_seconds: float) -> Iterator[None]: ...

@contextmanager
def try_locked(path: Path) -> Iterator[bool]: ...
```

Use `{store_root}/.locks/store.lock` for store transitions and
`{store_root}/.locks/artifacts/{sha256(artifact_key)}.lock` for artifact builds and cleanup.
Store lock waits use a 5-second timeout and normalize timeout to `PA_INGESTION_004`; callers do not
attempt another state write when the store lock is unavailable. `try_locked()` uses `timeout=0`
for non-blocking housekeeping. Keep artifact lock files outside renamed directories and keep
temporary artifact directories as sibling paths on the same local filesystem as their final
directories. Shared NFS and distributed locking remain outside this foundation.

- [ ] **Step 4: Implement locked transitions**

Add:

```python
def claim_next_knowledge_ingestion_job(..., lease_seconds: int = 300) -> KnowledgeIngestionJob | None
def renew_knowledge_ingestion_job_claim(..., claim_token: str, lease_seconds: int = 300) -> KnowledgeIngestionJob
def complete_knowledge_ingestion_job(...)
def defer_knowledge_ingestion_job(...)
def reschedule_knowledge_ingestion_job(...)
def fail_knowledge_ingestion_job(...)
```

Use a store-root advisory lock around selection plus writes. Require state-compatible transitions
for both quarantine and ingestion transitions, require the current opaque claim token for every
renew, accept, reject, complete, defer, reschedule, or fail operation, and raise
`PA_INGESTION_004` for conflicts. `defer_knowledge_ingestion_job()` moves a token-owned contended
artifact-build job back to `queued`, sets `next_attempt_at = now + 5s`, and does not increment
`auto_retry_count`. Claim only ingestion jobs whose upload-promotion marker exists and whose
`next_attempt_at` is absent or no later than the current time. A genuinely expired lease may be
reclaimed with a new token, after which the prior worker cannot commit state. Apply one claim-time
per-Source concurrency gate under the same lock: read `params.worker_concurrency`, default it to 2,
require an integer from 1 through 8, count non-expired `processing` quarantine-validation and
artifact-build tasks together, skip a capped Source, and continue oldest-ready-first selection
among eligible tasks from other Sources. This scheduling parameter does not participate in
artifact fingerprinting. The worker-facing `claim_next_knowledge_worker_task()` compares both task
kinds and persists the selected transition under that same lock; it must not peek one queue and
claim from another in separate lock scopes. Task-specific claim helpers may remain internal or
test-facing wrappers around the same locked selector. Validate `params.worker_concurrency` before
Source persistence with `PA_INGESTION_001`, then repeat validation during claim for manually
altered or legacy records. A malformed Source is skipped without silent clamping or blocking
eligible tasks from other Sources; collect one value-safe `KnowledgeWorkerDiagnostic` containing
only `source_id`, stable `PA_INGESTION_001`, and a short message. Return diagnostics alongside the
selected task claim, or diagnostics alone when no valid task is claimable.

- [ ] **Step 5: Verify store tests pass**

Run the Task 3 pytest command again.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/configuration/local_store.py \
  proof_agent/configuration/file_locking.py \
  tests/test_agent_configuration_store.py tests/test_knowledge_ingestion_store.py
git commit -m "Persist local index ingestion queue state"
```

## Task 4: Worker Orchestration

**Files:**
- Create: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Create: `tests/test_knowledge_ingestion_worker.py`

- [ ] **Step 1: Write failing worker tests**

Use a fake builder and cover:
- no queued task returns `None`;
- housekeeping purges expired rejected-upload bytes without consuming the one-task allowance;
- housekeeping removes stale artifact-build temporary directories without deleting published
  artifacts or consuming the one-task allowance, and skips any directory whose artifact-key lock
  cannot be acquired non-blockingly;
- one run claims and validates exactly one quarantined upload;
- accepted quarantine validation enqueues but does not build the ingestion artifact in the same run;
- artifact build consumes persisted parsed text and does not reparse the managed original;
- a compatible existing artifact completes the job without invoking the builder;
- a lease-expired reclaimed job reuses an artifact persisted before interruption without rebuilding;
- phase-boundary lease renewal keeps a long-running task owned, and stale replaced tokens cannot
  commit task state;
- builder progress callbacks renew the current job lease before and after bounded model calls;
- renewal failure stops the stale worker before any later provider call, artifact publication, or
  task-state commit, while an artifact completed during an already-started bounded call or atomic
  rename remains reusable by the new owner;
- rejected quarantine validation persists no revision or ingestion job;
- two queued tasks require two calls;
- an older queued ingestion job runs before newer quarantined uploads, preventing build starvation;
- a capped Source is skipped while the worker claims an eligible oldest-ready task from another
  Source;
- a malformed persisted Source concurrency value reports stable `PA_INGESTION_001` while another
  valid Source remains claimable;
- malformed-Source diagnostics accompany a successful valid task outcome, and diagnostics-only
  runs do not pretend the queue is empty;
- concurrent worker claims preserve atomic oldest-ready-first selection across both task kinds;
- parser or builder failure records the stable code and a short message;
- failure persistence excludes traceback content;
- recoverable timeout, rate-limit, and temporary-network failures schedule persisted 30-second
  then 120-second retries;
- artifact-key lock contention defers a job for 5 seconds without consuming an automatic retry;
- store-lock timeout surfaces `PA_INGESTION_004` without a second state-write attempt;
- worker restart cannot bypass persisted retry backoff;
- a third recoverable build failure reaches terminal `failed`;
- non-recoverable and unclassified failures skip retry;
- missing job-snapshot `declared_ingestion_model` fails with `PA_INGESTION_001`;
- later Source Draft model edits do not mutate or redirect an already queued artifact build.

- [ ] **Step 2: Verify the worker tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_knowledge_ingestion_worker.py -q
```

Expected: FAIL because `KnowledgeIngestionWorker` does not exist.

- [ ] **Step 3: Implement the worker service**

Add a `KnowledgeRevisionArtifactBuilder` protocol and:

```python
class KnowledgeIngestionWorker:
    def run_once(self) -> KnowledgeWorkerResult | None:
        ...
```

The worker must use the store's unified cross-queue claim operation, resolve one parser for quarantine validation, validate
the claimed job's immutable `KnowledgeArtifactBuildSpec.declared_ingestion_model`, pass the build
spec plus validated `ModelConfig` and a lease-renewal progress callback into the injected builder,
and complete or fail the persisted task with the matching claim token. Renew the claim at phase
boundaries. It must not reread live Source Draft artifact configuration for a queued build. Run
rejected-upload and stale-artifact-temporary housekeeping before claim without consuming the
one-task allowance.
Select the oldest ready task by `created_at` across quarantine validations and ingestion jobs, and
process exactly one task per run. For artifact builds, classify known timeout, rate-limit, and
temporary-network failures as recoverable and requeue them with persisted `next_attempt_at`;
default to non-recoverable for unclassified failures. Bound individual provider calls with the
configured timeout and persist only stable error metadata. Treat artifact-key lock contention as
expected deduplication: defer the token-owned job for 5 seconds without incrementing
`auto_retry_count`, then let a later worker recheck cache. Keep `attempt_count` as claim count and
increment `auto_retry_count` only for recoverable build failure.
Treat renewal failure as lost ownership: stop without starting another provider call, publishing
an artifact, or attempting another task-state transition.

- [ ] **Step 4: Verify worker tests pass**

Run the Task 4 pytest command again.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion/worker.py \
  tests/test_knowledge_ingestion_worker.py
git commit -m "Add recoverable knowledge ingestion worker"
```

## Task 5: Single-Revision LlamaIndex Artifact Builder

**Files:**
- Create: `proof_agent/capabilities/knowledge/ingestion/local_index_builder.py`
- Create: `tests/test_local_index_revision_builder.py`
- Modify: `proof_agent/capabilities/models/llama_index_bridge.py`
- Modify: `tests/test_proof_agent_llm.py`

- [ ] **Step 1: Write failing builder tests**

Use a deterministic mock model provider and monkeypatch provider resolution. Cover:
- builder uses `ModelCallRole.INGESTION`;
- one parsed revision produces LlamaIndex persistence files;
- builder consumes the persisted Parsed Knowledge Document Text derivative rather than reparsing
  the original;
- builder consumes the job-owned immutable `KnowledgeArtifactBuildSpec` and validated model config
  rather than live Source Draft artifact configuration;
- cache hit requires validated sidecar plus required LlamaIndex persistence files;
- cache miss acquires an artifact-key advisory lock and rechecks cache before any model call;
- artifact-key lock contention returns a defer signal rather than blocking or consuming a
  recoverable-failure retry;
- builder writes only to a sibling temporary directory, writes sidecar last, validates the
  temporary artifact, and atomically renames it into the final content-addressed path;
- temporary directories carry artifact-key and creation metadata for lock-aware housekeeping;
- builder invokes a progress callback before and after every bounded model call so the worker can
  renew its task lease;
- a progress-callback renewal failure aborts before any later provider call or artifact
  publication;
- `ProofAgentLLM` propagates its optional timeout into `ModelRequest.timeout_seconds`, invokes an
  optional progress callback before and after both `complete()` and `chat()` provider calls, and
  preserves existing behavior when neither option is supplied;
- concurrent same-key builds invoke the model-backed builder at most once;
- half-written or malformed artifact directories are never reused;
- `artifact_meta.json` contains schema, provider, engine, parser identity, content hash, and
  ingestion fingerprint, but no source, document, or revision identity;
- reusable artifact metadata and fingerprint use the exact runtime-installed LlamaIndex engine
  identity rather than the broad dependency floor;
- unsupported model-provider resolution is normalized to `PA_INGESTION_001`;
- unexpected TreeIndex build failure raises `PA_INGESTION_003`.

- [ ] **Step 2: Verify the builder tests fail**

Run:

```bash
uv run --extra dev --extra ingestion --extra tree python -m pytest \
  tests/test_local_index_revision_builder.py tests/test_proof_agent_llm.py -q
```

Expected: FAIL because the builder module does not exist.

- [ ] **Step 3: Implement the builder**

Accept the immutable `KnowledgeArtifactBuildSpec`, worker-validated `ModelConfig`, and a progress
callback used for lease renewal. Extend `ProofAgentLLM` with optional `timeout_seconds` and
`progress_callback` constructor arguments. Populate `ModelRequest.timeout_seconds` and invoke the
callback immediately before and after each synchronous `complete()` or `chat()` provider call;
keep both arguments optional so runtime retrieval behavior remains unchanged. Validate sidecar
plus required persistence files on cache lookup.
On miss, attempt the artifact-key advisory lock non-blockingly and check cache again after
acquisition before resolving its model provider. Return a defer signal on contention rather than
blocking or reporting a build failure. Build only inside a sibling temporary directory carrying artifact-key and creation
metadata, persist LlamaIndex storage, write the reusable artifact sidecar last, validate the
completed temporary artifact, and atomically rename it into the final content-addressed path.
Invoke the progress callback before and after every bounded model call. Source, document, and
revision identity remain in the job and document artifact reference rather than the reusable
sidecar. Worker housekeeping removes stale temporary artifact directories left by interrupted
builds only while holding the matching artifact-key lock non-blockingly.
If renewal fails, propagate lost ownership immediately and do not start another provider call or
publish the artifact. A compatible artifact already completed during an in-flight bounded call or
atomic rename may remain available for the new owner to validate and reuse.
Normalize provider-resolution failures to `PA_INGESTION_001` and build failures to
`PA_INGESTION_003`.

- [ ] **Step 4: Verify builder tests pass**

Run the Task 5 pytest command again.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion/local_index_builder.py \
  proof_agent/capabilities/models/llama_index_bridge.py \
  tests/test_local_index_revision_builder.py tests/test_proof_agent_llm.py
git commit -m "Build immutable local index revision artifacts"
```

## Task 6: Configuration API Job Projection

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [ ] **Step 1: Write failing API tests**

Update upload assertions and add:
- upload returns `upload_id`;
- uploaded bytes remain quarantined without synchronous parsing, revision creation, or build;
- invalid base64, empty content, and request-envelope size violations fail synchronously without a
  quarantine record;
- pending quarantine reservations count toward the 500-document Source limit;
- single-file staging publishes bytes plus record atomically through a temporary-directory rename;
- nested raw secret-bearing Source params fail with `PA_SECRET_001` before `source.json`
  persistence, while nested `*_env` references remain allowed;
- rejection releases its reservation even while rejected bytes remain retained;
- unsupported extensions, declared-MIME mismatches, invalid Markdown UTF-8, and malformed PDFs are
  staged successfully for asynchronous rejection rather than rejected by the API;
- quarantine list endpoint returns queued uploads;
- quarantine detail endpoint returns one upload;
- job list endpoint returns queued jobs;
- job detail endpoint returns one job;
- job detail returns 404 for unknown source or job.
- store-lock timeout maps `PA_INGESTION_004` to HTTP 503 without attempting a second write.

- [ ] **Step 2: Verify the API tests fail**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest \
  tests/test_agent_configuration_api.py -q
```

- [ ] **Step 3: Implement API staging and read endpoints**

Replace direct `add_knowledge_document()` usage in upload with
`stage_quarantined_knowledge_upload()`. Keep synchronous handling limited to target `local_index`
Source validation, base64 decoding, an encoded-size precheck before decode, non-empty content, and
the 50 MB decoded-byte limit. Move extension, declared-MIME, signature, UTF-8, and PDF-structure
validation into the quarantine worker. Add:

```text
GET /config/knowledge-sources/{source_id}/quarantined-uploads
GET /config/knowledge-sources/{source_id}/quarantined-uploads/{upload_id}
GET /config/knowledge-sources/{source_id}/ingestion-jobs
GET /config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}
```

Map store-lock `PA_INGESTION_004` timeout failures to HTTP 503.

- [ ] **Step 4: Verify API tests pass**

Run the Task 6 pytest command again.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/delivery/configuration_api.py tests/test_agent_configuration_api.py
git commit -m "Expose knowledge ingestion job status API"
```

## Task 7: CLI Worker Entry Point

**Files:**
- Modify: `proof_agent/delivery/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Monkeypatch the lazily imported worker dependency and assert:
- malformed-Source diagnostics print as `knowledge worker warning: {source_id} ({error_code})`
  before any task outcome;
- diagnostics-only runs do not print `no queued knowledge tasks`;
- `knowledge-worker --once` prints no-task text when empty;
- accepted upload prints `knowledge upload accepted: {upload_id}`;
- rejected upload prints `knowledge upload rejected: {upload_id} ({error_code})`;
- ready job prints `knowledge ingestion job ready: {job_id}`;
- scheduled retry prints `knowledge ingestion job retry scheduled: {job_id} ({error_code})`;
- deferred artifact-key contention prints `knowledge ingestion job deferred: {job_id}`;
- failed job prints `knowledge ingestion job failed: {job_id} ({error_code})`;
- store-lock timeout prints `PA_INGESTION_004` and exits non-zero;
- omitting `--once` fails clearly because continuous polling is outside this slice.

- [ ] **Step 2: Verify CLI tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest tests/test_cli.py -q
```

- [ ] **Step 3: Implement lazy CLI wiring**

Add:

```python
@app.command("knowledge-worker")
def knowledge_worker(
    config_dir: str = typer.Option("runs/config", "--config-dir"),
    once: bool = typer.Option(False, "--once"),
) -> None:
    ...
```

Import ingestion builder and worker inside the command so ordinary CLI paths do not require the
`ingestion` extra.

- [ ] **Step 4: Verify CLI tests pass**

Run the Task 7 pytest command again.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/delivery/cli.py tests/test_cli.py
git commit -m "Add one-shot knowledge ingestion worker CLI"
```

## Task 8: Documentation And Full Verification

**Files:**
- Modify: `docs/developer-guide.md`
- Modify: `docs/development-progress.md`
- Modify: `docs/technical-design.md`

- [ ] **Step 1: Document the worker foundation**

Document:
- `uv run --extra ingestion --extra tree proof-agent knowledge-worker --once`;
- asynchronous Quarantined Knowledge Upload validation before revision or ingestion-job creation;
- Markdown and text-based PDF support;
- fail-closed PDF limits;
- `pypdf` default and future Docling adapter path;
- persisted bounded artifact-build retry with 30-second then 120-second backoff;
- the current absence of publication, candidate snapshot promotion, continuous worker polling,
  batch-upload APIs, and runtime multi-document routing;
- claim-time Source concurrency through `params.worker_concurrency`, defaulting to 2 and bounded
  from 1 through 8;
- the later batch-upload contract: maximum 50 files, atomic full-batch capacity reservation and
  staging, then independent per-file asynchronous validation.

- [ ] **Step 2: Run focused ingestion verification**

```bash
uv run --extra dev --extra dashboard --extra ingestion --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py \
  tests/test_agent_configuration_store.py \
  tests/test_knowledge_ingestion_fingerprint.py \
  tests/test_knowledge_document_parsers.py \
  tests/test_knowledge_ingestion_store.py \
  tests/test_knowledge_ingestion_worker.py \
  tests/test_local_index_revision_builder.py \
  tests/test_proof_agent_llm.py \
  tests/test_agent_configuration_api.py \
  tests/test_cli.py -q
```

- [ ] **Step 3: Run the full suite without the ingestion extra**

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest tests/ -q
```

This proves the default suite and deterministic paths remain independent of `pypdf`.
PDF-specific parser tests skip when the optional ingestion dependency is absent.

- [ ] **Step 4: Run parser coverage with the ingestion extra**

```bash
uv run --extra dev --extra ingestion --extra tree python -m pytest \
  tests/test_knowledge_document_parsers.py \
  tests/test_local_index_revision_builder.py -q
```

- [ ] **Step 5: Run static checks**

```bash
uv run --extra dev --extra ingestion --extra tree ruff check proof_agent tests
uv run --extra dev --extra dashboard --extra ingestion --extra openai --extra tree mypy proof_agent
git diff --check
```

- [ ] **Step 6: Run deterministic CLI regression**

```bash
uv run --extra dev --extra tree proof-agent demo
```

Expected:

```text
supported: ANSWERED_WITH_CITATIONS
unsupported: REFUSED_NO_EVIDENCE
tool_required: WAITING_FOR_APPROVAL
```

- [ ] **Step 7: Commit**

```bash
git add docs/developer-guide.md docs/development-progress.md docs/technical-design.md
git commit -m "Document local index ingestion worker foundation"
```
