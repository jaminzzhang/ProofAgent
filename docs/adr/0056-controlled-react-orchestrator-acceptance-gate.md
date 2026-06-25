# Controlled ReAct Orchestrator Acceptance Gate

Accepted.

The V3 **Controlled ReAct Orchestrator** cutover will be accepted against governance invariants, not byte-for-byte or event-for-event trace compatibility with the old executor. The required gate covers supported, unsupported, clarification, tool approval pause, approval-granted resume, approval-denied resume, Observation Action output discipline, terminal-output receipt basis, absence of LangGraph from the V3 core path, and deletion or rejection of retired executable templates.

The rejected alternative is old-trace parity as the main gate. That would preserve incidental Runtime Plane event ordering and state-delta shapes while blocking intended semantic corrections, especially tool results becoming Observation Records, approval denial returning through the loop, and stage names becoming projections rather than execution methods.
