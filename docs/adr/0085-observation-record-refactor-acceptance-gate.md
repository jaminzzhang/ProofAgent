# Observation Record Refactor Acceptance Gate

Accepted.

Observation Record deepening is accepted only when seven invariants hold: summaries contain no raw evidence or tool payloads, every committed `truth_ref` resolves, answer synthesis uses Answer Evidence Context, observability uses projections only, retry/resume identity is stable, commit failure leaves no partial observation, and final citation binding validates against truth artifacts plus record refs.

We choose invariant-based acceptance over test-green-only acceptance because this refactor is primarily a boundary correction. The important failure modes are architecture regressions: summary pollution, observability bypass, adapter-owned commits, and answer synthesis quietly becoming a truth-store reader.
