# Workflow Stages As Controlled ReAct Projections

Accepted.

React Enterprise QA V3 keeps Workflow Template Stage language for trace, Governance Receipt, Dashboard, and validation capture, but stage names are projections emitted by the **Controlled ReAct Orchestrator**, not public execution methods and not internal module seams. The Orchestrator may emit stage result projections for Intent Resolution, plan, review, retrieval, tool, model answer, memory, and response explanation, while the only executable interface remains starting or resuming the run-scoped Orchestrator.

The rejected alternative is preserving stage handlers as the core execution shape because Dashboard and receipts already understand stages. That keeps the UI vocabulary stable but makes the module shallow: route rules, continuation state, approval pause semantics, and terminal outcomes remain spread across callers of individual stages. Stage vocabulary stays; stage-owned execution goes away.
