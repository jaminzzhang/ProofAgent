# Typed Controlled ReAct Run State

Accepted.

The V3 **Controlled ReAct Orchestrator** will use a typed **Controlled ReAct Run State** internally instead of `dict[str, Any]` continuation deltas as the core execution state. Stage-like orchestration steps may project trace-safe summaries and runtime adapter deltas, but the Control Plane state that drives eligibility, observations, approval pause and resume, evidence basis, blockers, and terminal outcome must be a typed value owned by the Orchestrator.

The rejected alternative is to copy the current `ReActGraphState` / stage-delta style into the new module. That would preserve familiar test fixtures but keep the module shallow: every internal step and test would still need to know loosely typed keys, merge semantics, and partial continuation shapes. Typed run state makes the Orchestrator interface small while allowing its implementation to absorb state complexity.
