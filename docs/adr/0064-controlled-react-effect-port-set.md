# Controlled ReAct Effect Port Set

Accepted.

The V3 **Controlled ReAct Orchestrator** will depend on a minimum set of effect ports:

- `IntentResolverPort`
- `PlannerPort`
- `ReviewPort`
- `PolicyPort`
- `KnowledgeObservationPort`
- `ToolObservationPort`
- `AnswerSynthesisPort`
- `StageProjectionPort`
- `SnapshotStorePort`
- `TransitionLockPort`

Existing planner, review, policy, retrieval, tool gateway, trace, persistence, and delivery implementations may be adapted behind these ports, but the Orchestrator must not directly depend on LangGraph checkpointers, `RunStore`, `TraceWriter`, provider clients, delivery request objects, or broad runtime service classes.

The rejected alternative is injecting existing concrete services directly into the Orchestrator for speed. That would make the new module a coordination wrapper around old dependencies instead of a deep module with a stable Control Plane interface.
