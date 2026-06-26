# Observation Truth Projection and Audit Replay

Accepted.

Trace, Governance Receipt, RunStore, and Dashboard will consume Observation Truth Projections generated during Observation Commit, not direct Observation Truth Artifact reads. Full truth payload resolution is reserved for a permissioned Observation Audit Replay path.

We choose this over letting observability surfaces read the Observation Truth Store because observability is a side channel. Direct truth reads from Dashboard or receipt rendering would create a second payload access path with separate authorization, redaction, retention, and replay semantics.
