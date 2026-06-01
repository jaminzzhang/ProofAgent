# Local Index Ingestion Worker Foundation Design

## Scope

This slice adds the recoverable local worker foundation for Dashboard-managed `local_index`
Knowledge Sources. It persists ingestion jobs, claims one job per `proof-agent knowledge-worker
--once` invocation, parses Markdown and text-based PDF originals, builds one immutable
revision artifact, and records stable success or failure state.

This slice does not add candidate Knowledge Source snapshots, Source publication APIs, runtime
multi-document routing, automatic retry with backoff, replacement uploads, document archive, or
Dashboard UI.

## Storage Boundary

`LocalAgentConfigurationStore` remains the file-backed persistence boundary. Upload validation
stores one immutable managed original and enqueues one `KnowledgeIngestionJob` in the same API
request. The API never parses a PDF or builds an index synchronously.

```text
knowledge_sources/{source_id}/
  source.json
  documents/{document_id}/
    document.json
    revisions/{revision_id}/original.md
  ingestion_jobs/{job_id}.json
  artifacts/{content_hash}/{ingestion_config_fingerprint}/
```

`KnowledgeIngestionJob` is a frozen contract with:

```text
job_id
source_id
document_id
revision_id
state: queued | processing | ready | failed
attempt_count
ingestion_config_fingerprint
artifact_path
claimed_at
completed_at
error_code
error_message
created_at
updated_at
```

The current `KnowledgeDocument` projection keeps the active revision fields used by the MVP API
and gains `ingestion_job_id` plus `artifact_path`. Full stable-document identity with immutable
revision history remains a later slice.

## Worker Claim And Recovery

The CLI entry point is:

```bash
uv run --extra ingestion --extra tree proof-agent knowledge-worker \
  --config-dir runs/config \
  --once
```

Each `--once` invocation claims at most one job. The store selects the earliest `queued` job, or
the earliest `processing` job whose `claimed_at` is older than the worker lease. Claiming increments
`attempt_count`, records a fresh `claimed_at`, and moves both job and document projection to
`processing`.

The local file-backed store serializes claim selection and state writes with an OS-level advisory
lock under the Knowledge Source store root. This prevents two concurrently started `--once`
processes from claiming the same job. A future distributed queue adapter replaces this local lock
boundary without changing the ingestion-job state machine.

A successful build moves both records to `ready`, persists the artifact path, and records
`completed_at`. A failed build moves both records to `failed` and stores only a stable error code
plus a short operator-facing message. It does not persist a traceback.

Lease recovery handles worker-process interruption. Automatic retry, transient failure
classification, retry limits, and backoff remain future work.

## Parser Boundary

Document parsing is isolated behind:

```python
class KnowledgeDocumentParser(Protocol):
    @property
    def parser_identity(self) -> str: ...
    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument: ...
```

The parser registry supports:

- UTF-8 Markdown with parser identity `markdown:utf-8`
- text-based PDF with parser identity `pypdf:6`

The PDF parser uses `pypdf>=6.12.2,<7`. It rejects malformed PDFs, encrypted PDFs, PDFs above
500 pages, and PDFs with no meaningful extracted text. Scanned PDF and OCR ingestion remain
outside V1 intake.

`pypdf` belongs to a new `ingestion` optional dependency group rather than the runtime `tree`
group. Read-only runtime load should not depend on document parsing packages.

### Why Not Docling Yet

Docling is a strong future parser adapter for layout-aware extraction, tables, formulas, images,
OCR, and additional office formats. It is not the default parser in this foundation slice because
the current V1 intake intentionally rejects scanned PDFs and accepts only Markdown plus text-based
PDF. Docling's standard PDF pipeline can involve layout, table, OCR, and model-weight concerns that
expand installation and runtime requirements beyond the current fail-closed parser contract.

Parser identity participates in the ingestion fingerprint. A future Source configuration may
select a `docling` adapter; changing parser identity will invalidate incompatible cached artifacts
and trigger incremental reingestion rather than silently reusing old output.

## Artifact Build

The worker resolves the Source-owned `params.ingestion_model` using the existing `ModelConfig` and
model registry, wraps it with `ProofAgentLLM(role=INGESTION)`, and invokes a single-revision Local
Index artifact builder. The builder writes LlamaIndex native persistence plus:

```json
{
  "schema_version": "local_index.revision-artifact.v1",
  "provider": "local_index",
  "engine_name": "llama-index-tree",
  "engine_version": "0.12",
  "parser_identity": "pypdf:6",
  "source_id": "ks_policy",
  "document_id": "doc_123",
  "revision_id": "rev_123",
  "content_hash": "...",
  "ingestion_config_fingerprint": "..."
}
```

The ingestion configuration fingerprint is a stable SHA-256 digest of artifact-affecting inputs:
ingestion model configuration, parser identity, provider name, engine name, and engine version.
Routing-model settings do not participate.

Enqueue computes the fingerprint from the declared Source parameters without treating that digest
operation as model-configuration validation. A missing or malformed `ingestion_model` can still
produce a persisted job identity; the worker then fails that job with `PA_INGESTION_001`. This
keeps upload request handling limited to intake and staging while preserving a stable queue record
for operator diagnosis.

Worker tests inject a fake builder so the default test suite remains deterministic, fast, and
network-free. Tests for real Markdown and PDF parser behavior run with the `ingestion` extra.

## API And CLI

The existing upload endpoint stages the original and queues a job:

```text
POST /api/config/knowledge-sources/{source_id}/documents
```

Its document payload gains `ingestion_job_id`.

New read-only endpoints expose operational job state:

```text
GET /api/config/knowledge-sources/{source_id}/ingestion-jobs
GET /api/config/knowledge-sources/{source_id}/ingestion-jobs/{job_id}
```

The CLI prints one of:

```text
knowledge ingestion job ready: job_ab12cd34
knowledge ingestion job failed: job_ab12cd34 (PA_INGESTION_002)
no queued knowledge ingestion jobs
```

## Failure Codes

- `PA_INGESTION_001`: Source ingestion configuration is missing or invalid.
- `PA_INGESTION_002`: The managed original is malformed, encrypted, oversized, scanned, or unsupported.
- `PA_INGESTION_003`: Local Index artifact build failed.
- `PA_INGESTION_004`: Job state transition or persistence failed.

Failures preserve the previous published READY snapshot because this slice does not mutate or
publish snapshots.

## Testing

- Uploading Markdown or PDF stores the immutable original and persists one queued ingestion job.
- `--once` claims no more than one job.
- A lease-expired processing job can be reclaimed after worker restart.
- Markdown and text-based PDF parsers return normalized text.
- Encrypted, malformed, over-500-page, and no-text PDFs fail closed.
- A successful fake build writes ready state and artifact identity to job and document records.
- A failed fake build records one stable code and short message without a traceback.
- Fingerprints change when artifact-affecting parser or ingestion-model configuration changes.
- The default demo and default CI remain independent of the `ingestion` extra.
