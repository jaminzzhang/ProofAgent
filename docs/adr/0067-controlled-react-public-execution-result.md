# Controlled ReAct Public Execution Result

Accepted.

The V3 **Controlled ReAct Orchestrator** public `start` and `resume` operations will return `WorkflowTemplateExecutionResult` as the only external execution fact contract.

`ControlledReActRunState`, `ControlledReActRunStateSnapshot`, `TransitionCommand`, `EffectResult`, and other internal transition types are not returned to Delivery, Dashboard, RunStore, or validation capture surfaces. Run state and snapshots exist to advance or resume orchestration; Delivery remains responsible for deriving Governance Receipt, RunStore artifacts, Dashboard projections, customer-safe response snapshots, and validation artifacts from the returned execution facts and trace-safe projections.

The rejected alternative is returning a richer Orchestrator-specific result containing internal state or snapshots. That would create a second public execution API beside `WorkflowTemplateExecutionResult` and make downstream surfaces depend on state-machine internals.
