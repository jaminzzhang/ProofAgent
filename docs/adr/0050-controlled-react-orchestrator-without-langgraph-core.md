# Controlled ReAct Orchestrator Without LangGraph Core

Accepted.

The V3 **Controlled ReAct Orchestrator** will execute the core React Enterprise QA product path as a Control Plane state machine, not as a LangGraph `StateGraph`. LangGraph checkpoint, interrupt, resume, and streaming mechanics may be reintroduced later only as Runtime Plane adapters around the Orchestrator; they must not define the Orchestrator interface, stage ordering, approval authority, continuation shape, or terminal outcome semantics.

The rejected alternative is keeping LangGraph as the primary executor while making the Orchestrator a thinner stage handler collection. That would preserve existing mechanics but keep the deepest semantics spread across graph routing, state-delta adapters, checkpoint payloads, and Control Plane stage behavior. The new module must make orchestration behavior testable through one run-scoped interface before runtime scheduling concerns are added back.
