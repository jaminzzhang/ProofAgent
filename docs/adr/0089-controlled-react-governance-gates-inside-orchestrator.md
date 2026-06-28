# Controlled ReAct Governance Gates Inside Orchestrator

Controlled ReAct V3 governance gates belong inside the Orchestrator and its effect ports, not in Delivery-layer trace projection. Retrieval planning and retrieval steps, final-answer model calls, final answer admission, and memory writes must evaluate policy before the guarded action is executed.

Delivery may persist trace, receipt, and RunStore projections, but it must not be the component that creates core policy decisions after the Orchestrator has already produced a terminal result. This keeps `PolicyEngine` as an execution authority instead of an after-the-fact audit embellishment.
