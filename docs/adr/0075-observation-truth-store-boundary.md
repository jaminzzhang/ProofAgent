# Observation Truth Store Boundary

Accepted.

Observation Truth Artifacts will be stored behind an independent Control Plane Observation Truth StorePort. The Orchestrator commit boundary writes the truth artifact and appends the Observation Record envelope atomically; Controlled ReAct Run State and snapshots retain only `truth_ref`.

We choose this over embedding truth payloads in snapshots or trace/run projections because snapshots should remain resumable control state, and observability must stay a side channel rather than an execution dependency. The trade-off is one more store port, but it preserves bounded planner context, small snapshots, and a clean final-answer truth resolution boundary.
