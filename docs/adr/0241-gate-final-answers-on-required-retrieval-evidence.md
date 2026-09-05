# ADR-0241: Gate final answers on required retrieval evidence

## Status

[FRAME | HIGH] Accepted for the user-authorized P0-2 local implementation on 2026-09-05; not production approval.

## Context

[KNOWN | HIGH] The current answer-ready heuristic treats one accepted observation with no declared unresolved subgoals as enough to finish. It can suppress a second required query, and planner/tool shortcuts can propose a final answer before the intent's required retrieval set is covered.

## Decision

- Derive a fixed set of required queries from the first validated Intent Resolution. Explicitly freeze the stored intent. Trim only outer whitespace and deduplicate identical queries; optional queries do not block this gate. Stable requirement IDs are SHA-256 identities of those normalized queries.
- Reuse the original intent in the signed/digest-bound snapshot. Do not add persisted completion defaults that would change old snapshot hashes. Recompute completion from verified Observation Truth instead of trusting cached counts or model-provided flags.
- A requirement needs the exact executed query from adapter-owned admission metadata, a bound retrieval truth belonging to this run and record, and Accepted Evidence whose source/citation is available in the answer context. Counts, tools, memory, candidate evidence, query proposals and semantic similarity do not prove completion.
- While unattempted requirements remain, prevent early finalization and redirect premature final or duplicate/unrelated retrieval proposals to a pending required query. The new proposal retains risk level and passes the existing Review, Policy and exact KSS binding path.
- Keep failed attempts unresolved while allowing other unattempted requirements to run. Stop with a stable incomplete reason when no pending query can add progress. The observation budget still bounds execution; a fully covered task can enter answer generation immediately after its last allowed observation, while incomplete tasks at the limit refuse.
- Recheck bound truth and completion immediately before synthesis. Expose an audit projection with version, requirement identities, counts, bound references and stable reasons; do not add raw query or answer payloads to the projection.
- Require non-whitespace source and citation references. Preserve explicit refusal/clarification decisions and unresolved business/retrieval subgoals even when all queries have evidence. Approval denial remains an immutable observation; the existing governed alternative-retrieval path may still answer without executing the denied tool.
- Before any resumed observation, validate original required-query proofs from the loaded snapshot. Add `task_completion_evaluated` to the closed Trace event enum with explicit `stage_id=plan`; only applicable runs emit it. Final, refusal, clarification and direct policy/scope-denial plan projections carry the same versioned coverage facts. Existing snapshot payload fields and approval-wait result semantics stay unchanged.
- Calls without required queries remain outside this gate, never implicitly completed. This gate is necessary retrieval coverage, not answer-semantic correctness or overall business task completion; Evaluation Quality remains conservative.

## Consequences and validation

Exact query coverage is intentionally stricter than semantic equivalence. New required variants may require extra governed queries. Business/retrieval unresolved subgoals remain blockers until clarification or a new run; this slice adds no authority to clear them. No new runtime authority, production tool scope, storage or task recovery service is introduced. Tests cover real composition, premature final, duplicates, equal evidence counts, optional/empty evidence, budget boundaries, truth tampering, policy refusal, snapshot recovery and old callers. Scope and acceptance are tracked in `docs/features/agent-kernel-quality/scope-p0-2.md` and `tdd-p0-2.md` (locally verified on 2026-09-06).
