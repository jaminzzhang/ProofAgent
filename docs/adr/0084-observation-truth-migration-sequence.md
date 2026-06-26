# Observation Truth Migration Sequence

Accepted.

Observation Record deepening will migrate in four phases: contracts first, truth store and commit internals second, knowledge/tool adapter effects third, and answer/projection consumers last. The Orchestrator main flow should not be rewritten before contracts, store, commit validation, and adapter effects are testable.

We choose this over a single Orchestrator rewrite because each phase creates a stable test boundary: frozen DTO contracts, commit invariants, adapter payload separation, and final answer/observability projection behavior. This sequence is a sub-sequence of ADR-0073, not a replacement for the overall Controlled ReAct cutover order.
