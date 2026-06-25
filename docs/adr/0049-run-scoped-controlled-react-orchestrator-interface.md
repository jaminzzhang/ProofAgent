# Run-Scoped Controlled ReAct Orchestrator Interface

Accepted.

The V3 **Controlled ReAct Orchestrator** will expose a run-scoped execution interface rather than public per-stage methods. Its external operations are starting a governed run and resuming a paused approval run; Intent Resolution, planning, review, retrieval, tool execution, model answer generation, response projection, convergence, and terminal outcome selection remain internal state-machine steps.

This replaces the current stage-method surface where Runtime Plane code can call `intent_resolution`, `plan`, `retrieval`, `tool`, and `model` separately. Keeping public per-stage calls would preserve Dashboard-friendly labels but keep the module shallow: callers would still need to understand stage ordering, continuation state, approval pause shape, route rules, and terminal semantics. Stage labels remain trace and receipt projections, not the Orchestrator interface.
