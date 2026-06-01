# Local Index Ingestion Worker Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a recoverable file-backed worker that stages Dashboard-managed Local Index documents, parses Markdown and text-based PDF originals, and builds one immutable revision artifact per `proof-agent knowledge-worker --once` invocation.

**Architecture:** Keep queue state in `LocalAgentConfigurationStore`, serialize claims with a local advisory lock, and isolate parsing plus LlamaIndex artifact construction behind focused ingestion modules. The upload API stages immutable originals and queues work; it never parses or builds indexes synchronously.

**Tech Stack:** Python 3.12, Pydantic frozen contracts, Typer, FastAPI, `pypdf>=6.12.2,<7`, LlamaIndex TreeIndex, pytest, Ruff, mypy

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
- `tests/test_knowledge_ingestion_fingerprint.py`
- `tests/test_knowledge_document_parsers.py`
- `tests/test_knowledge_ingestion_store.py`
- `tests/test_knowledge_ingestion_worker.py`
- `tests/test_local_index_revision_builder.py`

**Modify:**
- `pyproject.toml` - add the `ingestion` optional dependency group.
- `uv.lock` - lock `pypdf`.
- `proof_agent/errors.py` - register stable `PA_INGESTION_001` through `PA_INGESTION_004`.
- `proof_agent/contracts/agent_configuration.py` - add `KnowledgeIngestionJob`; extend the current document projection.
- `proof_agent/contracts/__init__.py` - export the new contract.
- `proof_agent/configuration/local_store.py` - persist, claim, complete, and fail jobs.
- `proof_agent/delivery/configuration_api.py` - enqueue uploads and expose read-only job endpoints.
- `proof_agent/delivery/cli.py` - add `knowledge-worker --once`.
- `tests/test_agent_configuration_contracts.py`
- `tests/test_agent_configuration_store.py`
- `tests/test_agent_configuration_api.py`
- `tests/test_cli.py`
- `docs/developer-guide.md`
- `docs/development-progress.md`
- `docs/technical-design.md`

## Task 1: Dependency And Frozen Contracts

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `proof_agent/errors.py`
- Modify: `proof_agent/contracts/agent_configuration.py`
- Modify: `proof_agent/contracts/__init__.py`
- Modify: `tests/test_agent_configuration_contracts.py`

- [ ] **Step 1: Write failing contract tests**

Add tests that construct and serialize:

```python
job = KnowledgeIngestionJob(
    job_id="job_001",
    source_id="ks_policy",
    document_id="doc_001",
    revision_id="rev_001",
    state="queued",
    attempt_count=0,
    ingestion_config_fingerprint="fingerprint",
    created_at="2026-06-01T00:00:00Z",
    updated_at="2026-06-01T00:00:00Z",
)
assert job.artifact_path is None
assert job.claimed_at is None
assert job.completed_at is None
```

Also assert `KnowledgeDocument` defaults `ingestion_job_id` and `artifact_path` to `None`, and
assert mutating `job.state` raises `ValidationError`.

- [ ] **Step 2: Verify the contract tests fail**

Run:

```bash
uv run --extra dev --extra tree python -m pytest \
  tests/test_agent_configuration_contracts.py -q
```

Expected: FAIL because `KnowledgeIngestionJob` is not exported.

- [ ] **Step 3: Implement the contracts and error codes**

Add `PA_INGESTION_001` through `PA_INGESTION_004` to `ErrorCode`.

Add the frozen contract:

```python
class KnowledgeIngestionJob(FrozenModel):
    job_id: str
    source_id: str
    document_id: str
    revision_id: str
    state: str
    attempt_count: int = 0
    ingestion_config_fingerprint: str
    artifact_path: str | None = None
    claimed_at: str | None = None
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
```

Extend `KnowledgeDocument` with optional `ingestion_job_id` and `artifact_path`, then export the
new type from `proof_agent.contracts`.

- [ ] **Step 4: Add and lock the parser dependency**

Add:

```toml
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
git add pyproject.toml uv.lock proof_agent/errors.py \
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
first = ingestion_config_fingerprint(source_params, parser_identity="markdown:utf-8")
second = ingestion_config_fingerprint(source_params, parser_identity="markdown:utf-8")
assert first == second
assert first != ingestion_config_fingerprint(
    changed_ingestion_model_params,
    parser_identity="markdown:utf-8",
)
assert first != ingestion_config_fingerprint(source_params, parser_identity="docling:standard")
```

Assert routing-model-only changes do not change the digest.

- [ ] **Step 2: Write failing parser tests**

Cover:
- UTF-8 Markdown normalization.
- Text PDF extraction.
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
class ParsedKnowledgeDocument:
    text: str
    page_count: int | None
    parser_identity: str

class KnowledgeDocumentParser(Protocol):
    @property
    def parser_identity(self) -> str: ...
    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument: ...
```

Canonicalize only `ingestion_model`, parser identity, provider name, engine name, and engine
version into sorted JSON before SHA-256 hashing.

Add:

```python
def ingestion_model_config_from_source(source: KnowledgeSource) -> ModelConfig:
    ...
```

Normalize missing or malformed `params.ingestion_model` to `PA_INGESTION_001`.

- [ ] **Step 5: Implement Markdown and PDF parsers**

Keep `pypdf` import inside the PDF parser path so importing Proof Agent without the `ingestion`
extra still works. Normalize parser failures into:

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
- Modify: `proof_agent/configuration/local_store.py`
- Create: `tests/test_knowledge_ingestion_store.py`
- Modify: `tests/test_agent_configuration_store.py`

- [ ] **Step 1: Write failing store tests**

Cover:
- staging stores an immutable original and one queued job;
- listing jobs returns creation order;
- claim moves job and document to `processing` and increments `attempt_count`;
- a second claim skips a non-expired processing job;
- an expired processing lease is reclaimable;
- completion writes ready state and artifact path;
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
def stage_knowledge_document_for_ingestion(...) -> tuple[KnowledgeDocument, KnowledgeIngestionJob]
def get_knowledge_ingestion_job(...)
def list_knowledge_ingestion_jobs(...)
```

Compute parser identity from intake type and call `ingestion_config_fingerprint()` without treating
fingerprint calculation as model-config validation.

- [ ] **Step 4: Implement locked transitions**

Add:

```python
def claim_next_knowledge_ingestion_job(..., lease_seconds: int = 300) -> KnowledgeIngestionJob | None
def complete_knowledge_ingestion_job(...)
def fail_knowledge_ingestion_job(...)
```

Use a store-root advisory lock around selection plus writes. Require state-compatible transitions
and raise `PA_INGESTION_004` for conflicts.

- [ ] **Step 5: Verify store tests pass**

Run the Task 3 pytest command again.

- [ ] **Step 6: Commit**

```bash
git add proof_agent/configuration/local_store.py \
  tests/test_agent_configuration_store.py tests/test_knowledge_ingestion_store.py
git commit -m "Persist local index ingestion queue state"
```

## Task 4: Worker Orchestration

**Files:**
- Create: `proof_agent/capabilities/knowledge/ingestion/worker.py`
- Create: `tests/test_knowledge_ingestion_worker.py`

- [ ] **Step 1: Write failing worker tests**

Use a fake builder and cover:
- no queued job returns `None`;
- one run claims and completes exactly one job;
- two queued jobs require two calls;
- parser or builder failure records the stable code and a short message;
- failure persistence excludes traceback content;
- missing Source `ingestion_model` fails with `PA_INGESTION_001`.

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
    def run_once(self) -> KnowledgeIngestionJob | None:
        ...
```

The worker must claim through the store, resolve one parser, validate source ingestion config,
pass the validated `ModelConfig` into the injected builder, and complete or fail the persisted job.
Persist only stable error metadata.

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

- [ ] **Step 1: Write failing builder tests**

Use a deterministic mock model provider and monkeypatch provider resolution. Cover:
- builder uses `ModelCallRole.INGESTION`;
- one parsed revision produces LlamaIndex persistence files;
- `artifact_meta.json` contains schema, provider, engine, parser identity, source, document,
  revision, content hash, and ingestion fingerprint;
- unsupported model-provider resolution is normalized to `PA_INGESTION_001`;
- unexpected TreeIndex build failure raises `PA_INGESTION_003`.

- [ ] **Step 2: Verify the builder tests fail**

Run:

```bash
uv run --extra dev --extra ingestion --extra tree python -m pytest \
  tests/test_local_index_revision_builder.py -q
```

Expected: FAIL because the builder module does not exist.

- [ ] **Step 3: Implement the builder**

Accept the worker-validated `ModelConfig`, resolve its model provider, wrap it with
`ProofAgentLLM(role=INGESTION)`, build exactly one revision, persist LlamaIndex storage, and write
the revision artifact sidecar. Normalize provider-resolution failures to `PA_INGESTION_001` and
build failures to `PA_INGESTION_003`.

- [ ] **Step 4: Verify builder tests pass**

Run the Task 5 pytest command again.

- [ ] **Step 5: Commit**

```bash
git add proof_agent/capabilities/knowledge/ingestion/local_index_builder.py \
  tests/test_local_index_revision_builder.py
git commit -m "Build immutable local index revision artifacts"
```

## Task 6: Configuration API Job Projection

**Files:**
- Modify: `proof_agent/delivery/configuration_api.py`
- Modify: `tests/test_agent_configuration_api.py`

- [ ] **Step 1: Write failing API tests**

Update upload assertions and add:
- upload returns `ingestion_job_id`;
- uploaded document is queued without synchronous parsing or build;
- job list endpoint returns queued jobs;
- job detail endpoint returns one job;
- job detail returns 404 for unknown source or job.

- [ ] **Step 2: Verify the API tests fail**

Run:

```bash
uv run --extra dev --extra dashboard --extra tree python -m pytest \
  tests/test_agent_configuration_api.py -q
```

- [ ] **Step 3: Implement API staging and read endpoints**

Replace direct `add_knowledge_document()` usage in upload with
`stage_knowledge_document_for_ingestion()`. Add:

```text
GET /config/knowledge-sources/{source_id}/ingestion-jobs
GET /config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}
```

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
- `knowledge-worker --once` prints no-job text when empty;
- ready job prints `knowledge ingestion job ready: {job_id}`;
- failed job prints `knowledge ingestion job failed: {job_id} ({error_code})`;
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
- Markdown and text-based PDF support;
- fail-closed PDF limits;
- `pypdf` default and future Docling adapter path;
- the current absence of publication, candidate snapshot promotion, retry backoff, and runtime
  multi-document routing.

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
