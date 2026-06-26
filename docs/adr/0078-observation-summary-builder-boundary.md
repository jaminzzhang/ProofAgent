# Observation Summary Builder Boundary

Accepted.

Observation Record `summary` will be produced by a deterministic Control Plane Observation Summary Builder, not authored freely by knowledge or tool adapters. Retrieval summaries derive from admission metadata, accepted/rejected counts, source refs, and citation refs; tool summaries derive from Tool Contract `summary_fields` after redaction policy.

We choose this because `summary` is planner-visible control input. Letting adapters write it directly would let capability implementations decide what the planner sees, reintroducing context pollution and weakening the Observation Truth Artifact boundary.
