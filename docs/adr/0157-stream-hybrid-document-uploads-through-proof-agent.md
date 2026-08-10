---
status: accepted
---

# Stream Hybrid document uploads through Proof Agent

[FRAME | HIGH] Hybrid Knowledge intake accepts one multipart PDF per Proof Agent API request and lets Dashboard orchestrate batches with bounded concurrency and per-file outcomes. This replaces Base64 JSON batches, avoiding their size and memory amplification, while rejecting direct browser-to-S3 writes so API authorization, request limits, content admission, system-generated storage identity, and audit remain authoritative.

[FRAME | HIGH] Each accepted asynchronous command returns `202 Accepted` with `operation_id`, `source_revision`, and `poll_after_ms`. Dashboard polls a durable Knowledge Source Operation Projection only while the operation is active, honors `Retry-After` when supplied, uses bounded backoff, pauses background polling while the page is hidden, and reloads authoritative Source and action projections after a terminal result.

[FRAME | HIGH] Durable quarantine, ingestion, review, and publication records remain workflow authority. The operation projection survives browser reload and process restart and exposes only bounded stage, timing, progress, and sanitized outcome fields. A future SSE transport may notify Dashboard to refresh that projection, but an event stream is neither required in V1 nor authoritative state.

[FRAME | HIGH] Every API-admitted Hybrid ingestion job stores the exact unified `operation_id`. Worker claim, retry, review-required, success, failure, and cancellation transitions update the job, Source revision, and operation projection in the same PostgreSQL transaction. The expand-only link migration recovers released upload-operation links from their append-only admission audit events and reconciles already-terminal jobs, so an upgraded Dashboard cannot poll a stale `queued` operation forever.

[FRAME | HIGH] Each upload carries a stable `Idempotency-Key` retained by Dashboard through terminal state and by the API for at least 24 hours. An exact replay returns the original operation before Source revision comparison, while reuse with a different filename, parameters, or observed content digest returns `409 idempotency_key_mismatch`. A fresh key deliberately creates a fresh document command even if immutable content-addressed storage reuses the same bytes.

[FRAME | HIGH] Replacement is an explicit multipart command against the revisions collection of one stable `document_id`; filename equality never overwrites. The previous READY revision remains selected by the candidate and every published snapshot while its replacement is pending or failed. When the replacement becomes READY, the candidate atomically selects it and advances `source_draft_version_id`; explicit Source publication is still required before any published binding can use it.

[FRAME | HIGH] Revision projection distinguishes `unselected` from `superseded`. A failed or cancelled revision that never became a candidate is `unselected` and Dashboard renders only its ingestion state; `superseded` is reserved for an older completed revision displaced by another selected candidate.

[FRAME | HIGH] Metadata workbook import uses the same API-mediated binary transport rather than retaining a Base64 JSON exception. One multipart `.xlsx` command binds to an exact document revision, Source revision, and Idempotency Key, returns a durable operation, and lets a Knowledge Worker atomically materialize the complete review set after validation.
