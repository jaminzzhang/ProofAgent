# Observation Effect and Orchestrator Commit

Accepted.

Knowledge Observation Ports and Tool Observation Ports will return an Observation Effect rather than a committed Observation Record. The Orchestrator owns Observation Commit: it validates the effect, writes the typed Observation Truth Artifact through the Observation Truth StorePort, appends the Observation Record envelope to Control Plane state, and emits trace-safe projections atomically.

We choose this over letting adapters append records or write truth payloads because observation state is loop-control authority. Adapters may execute retrieval or tools and propose facts, but they must not mutate Controlled ReAct Run State or create observability-backed execution paths.
