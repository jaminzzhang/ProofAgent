# Controlled ReAct Delivery Entry Point

Accepted.

The V3 product path will enter execution through `ControlledReActOrchestrator.start` and `ControlledReActOrchestrator.resume` from Delivery. `RunExecutionService` resolves the Published Agent, creates the `run_id`, prepares run-start request facts, and owns artifact finalization, Governance Receipt rendering, RunStore persistence, Dashboard projection, customer response snapshots, and validation artifact construction.

Delivery must not call `runtime.langgraph_runner`, `runtime.react_graph`, or `LangGraphApprovalResumeRegistry` for V3 orchestration semantics. Approval resume APIs call the Orchestrator with an approval decision and protected snapshot reference; the Orchestrator loads and validates the run-state snapshot through its snapshot store port.

The rejected alternative is keeping Delivery wired to runtime runners while introducing the Orchestrator as an optional branch. That would leave V3 execution authority split across Delivery, Runtime, and Control modules and would preserve the current approval-resume coupling to LangGraph checkpoint internals.
