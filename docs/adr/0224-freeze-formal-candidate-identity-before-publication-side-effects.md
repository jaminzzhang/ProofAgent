---
status: accepted
---

# Freeze formal candidate identity before publication side effects

[KNOWN | HIGH] ADR-0223 allows one expired durable formal publication command to be
taken over. Before this decision, the new execution reassembled the exact Draft and
current authorities but did not retain the first execution's Formal Candidate digest.
A changed catalog or deployment binding could therefore turn one durable command into a
different publication candidate while preserving its command and external identities.

[DECISION | HIGH] After read-only candidate assembly and before Phase F, the current
fenced execution writes one immutable internal checkpoint containing
`formal_candidate_sha256`, `knowledge_release_candidate_sha256` and PostgreSQL time.
The checkpoint is part of the durable command record but not its public receipt.

[DECISION | HIGH] A takeover reassembles the Candidate from the exact Draft revision,
live KSS catalog and deployment-owned Profile. Both digests must match the existing
checkpoint before Phase F. Exact digest replay returns the original checkpoint without
changing its time. Digest drift leaves the checkpoint unchanged and fails the command
before Phase F, Reference registration, Query Grant staging, online smoke or final
publication.

[DECISION | HIGH] Only the current exact execution claim may create or replay a
checkpoint. The repository checks command state, command identity, lease owner and
fencing token under one row lock. A stale execution, terminal command or partial
checkpoint fails closed. Migration `0024_formal_candidate_checkpoint` is expand-only.

[CONSEQUENCE | HIGH] After checkpoint drift, an operator must review the new Candidate
and submit a new command with a new `Idempotency-Key`. The old command cannot adopt a
different digest. This preserves actor-scoped request idempotency and candidate identity
as separate immutable facts.

[BOUNDARY | HIGH] TDD-05T stores digests rather than the complete Candidate payload. It
does not add a background recovery process, heartbeat, cancellation, Reference or Grant
cleanup, a Dashboard control, publication approval, real external-model proof or
Production GO.

[KNOWN | HIGH] ADR-0225 exposes only the existing public command receipt to its exact
creating actor. It does not expose this checkpoint or change takeover behavior.
