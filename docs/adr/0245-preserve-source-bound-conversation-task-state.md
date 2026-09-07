# ADR-0245: Preserve source-bound conversation task state

## Status

[FRAME | HIGH] Accepted for the user-authorized P1-1 local implementation on 2026-09-06.

## Decision

Preserve task goals and constraints as bounded, versioned conversation working state with source user-turn identities and explicit revision/revocation semantics. Only user questions can propose state changes; assistant responses, retrieved content and model-written summaries cannot grant authority or mutate constraints.

Reuse the existing conversation turn persistence, retention and expected-turn-count/transaction boundaries. No production filesystem fallback, independent memory database or longer retention is added. Historical turns without snapshots may be replayed from their retained ordered user questions. Current-request corrections apply to the current working context; persistent state changes become visible only with the existing successful turn commit.

Admit meaningful task state before recent conversational detail. Compression must change the actual model input and account for its budget. An active constraint cannot disappear through silent truncation; unresolved revisions or insufficient context budget must remain explicit. Trace receives only safe state identifiers, digests and counts, not a new copy of task-state text.

The initial extractor supports explicit goal/constraint keys and bounded, identifiable Chinese/English budget/prohibition statements. Unsupported or ambiguous language is not a claim of general semantic understanding. Revoking a remembered constraint is never permission to execute a business write; evidence admission and tool authorization remain independent gates.
