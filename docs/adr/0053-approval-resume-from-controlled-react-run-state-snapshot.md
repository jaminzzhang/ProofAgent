# Approval Resume From Controlled ReAct Run State Snapshot

Accepted.

The V3 **Controlled ReAct Orchestrator** will resume approval-paused runs from an Orchestrator-owned typed **Controlled ReAct Run State Snapshot**, not from LangGraph checkpoints, trace replay, or mutable latest Agent configuration. The Approval Pause points to the protected snapshot and the run-start Workflow Template Execution Input integrity reference; resume loads both, validates they still match, applies the approval decision as Control Plane loop state, and continues planning.

The rejected alternative is treating checkpoint or trace artifacts as the semantic source of resume. That would keep implementation close to the current LangGraph path, but it would make Runtime Plane mechanics or audit projections define Control Plane state. Checkpoints may exist later as storage mechanics; trace remains the audit source of truth, not the executable state source.
