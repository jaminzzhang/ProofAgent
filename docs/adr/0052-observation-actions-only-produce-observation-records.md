# Observation Actions Only Produce Observation Records

Accepted.

In the V3 **Controlled ReAct Orchestrator**, every Observation Action produces exactly one Observation Record path back into the loop and must not directly create final output, refusal output, approval-denied terminal output, or answered outcomes. Retrieval and tool execution may emit trace events and may update the typed Controlled ReAct Run State, but the only loop-visible execution result of `PLAN_RETRIEVAL` or `PROPOSE_TOOL_CALL` is an Observation Record followed by another Plan Round.

This sharpens ADR-0032 and ADR-0038 for the Orchestrator refactor. The rejected alternative is preserving special terminal behavior for tools or insufficient retrieval, such as a tool stage returning a customer-status answer directly. That keeps implementation short but breaks the loop invariant, prevents compound request recovery, and forces callers to know which observation actions secretly terminate.
