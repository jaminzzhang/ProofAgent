# hicode Coding Rules

These rules add feature-delivery constraints to `AGENTS-COMMON.md`; the shared
guide remains authoritative for architecture, security, testing, and claim
language.

## Contract-first delivery

- Drive every observable behavior through RED → GREEN → REFACTOR.
- Test public contracts or application ports before private implementation
  details.
- Reject unknown external fields and invalid state transitions explicitly.
- Keep identifiers, timestamps, error codes, and enum values stable and typed.
- Change a public contract only with an ADR or an already-approved design record.

## State and persistence

- Make idempotency decisions from a canonical request fingerprint and persist
  the decision with the created resource.
- Commit state transitions, durable work publication, and required audit records
  atomically when they form one business event.
- Fence leased work; a stale worker must not complete or overwrite a newer
  execution attempt.
- Do not hold database transactions open across model, network, object-store, or
  search-engine calls.
- Parameterize SQL and keep repository interfaces independent of a concrete
  database client.

## Authority boundaries

- External Knowledge providers retrieve Candidate Evidence. ProofAgent owns policy,
  evidence admission, conflict handling and final-answer validation (ADR-0242).
- Dify is the first adapter. Bind exact Dataset, endpoint, versioned credential
  reference and retrieval settings; the model cannot choose another dataset or key.
- KSS-only runtime and release assumptions are historical. Do not add KSS startup,
  readiness or query dependencies to the active Agent kernel.
- Production must fail closed when PostgreSQL, object storage or the guarded
  transport/Secret Provider is unavailable. No development fallback is allowed.

## Security and evidence

- Never log credentials, source payloads, raw model prompts, or unrestricted
  query results. Record bounded identifiers and redacted diagnostics.
- Map internal failures to stable, non-sensitive public error codes.
- Keep test output, commands, unresolved risks, and changed paths in the feature
  TDD report. A local pass is not production proof.
