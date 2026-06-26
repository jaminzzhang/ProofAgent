# Observation Truth Artifact Boundary

Accepted.

Observation Records are loop-visible control-state envelopes, not raw payload containers. Full admitted retrieval evidence and authorized tool results live in typed Observation Truth Artifacts referenced by `truth_ref`, while `summary` remains deterministic, bounded, and planner-visible.

We choose this over embedding full evidence or tool payloads in `summary` because planner context must stay bounded and sanitized, while final-answer synthesis and audit replay still need the full truth layer. The rejected alternative keeps the implementation short but leaks raw payloads into stage projections and makes the planner/answer boundary unenforceable.
