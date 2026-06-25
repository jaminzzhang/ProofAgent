# Controlled ReAct Run State Snapshot Store

Accepted.

The V3 **Controlled ReAct Orchestrator** will use a dedicated **Controlled ReAct Run State Snapshot Store** to persist and load resumable execution state. The Orchestrator is the semantic owner of snapshot writes and reads; Delivery may invoke resume, and observability surfaces may show trace-safe references, but `RunStore`, trace files, Governance Receipt, and Dashboard projections must not deserialize snapshots or determine continuation semantics.

The local implementation may store snapshot artifacts beside run artifacts for operational convenience, but that physical placement does not make them RunStore detail, trace payload, or dashboard state. Approval pause records should expose only a protected reference plus trace-safe summary needed for audit and operator UX.

The rejected alternative is reusing `RunStore` or LangGraph checkpoint storage as the new snapshot authority. That would preserve the current coupling where observability artifacts and runtime mechanics control resume behavior, making approval resume dependent on trace shape, dashboard projection, or framework-specific checkpoint internals.
