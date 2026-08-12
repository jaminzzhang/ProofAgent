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

- Knowledge Source Service may analyze, store, plan, and retrieve Candidate
  Evidence. It must not admit evidence, decide truth, resolve conflicts, or
  generate ProofAgent's final answer.
- ProofAgent authorizes its user-facing operation and performs Evidence
  Admission. Knowledge Source Service independently enforces service grants and
  Knowledge Space scope.
- Production composition must fail closed when PostgreSQL, object storage, or
  required search dependencies are unavailable; do not add a local fallback.

## Security and evidence

- Never log credentials, source payloads, raw model prompts, or unrestricted
  query results. Record bounded identifiers and redacted diagnostics.
- Map internal failures to stable, non-sensitive public error codes.
- Keep test output, commands, unresolved risks, and changed paths in the feature
  TDD report. A local pass is not production proof.
