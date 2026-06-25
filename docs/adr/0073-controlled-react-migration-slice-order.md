# Controlled ReAct Migration Slice Order

Accepted.

The V3 **Controlled ReAct Orchestrator** cutover will be implemented in vertical slices:

1. Add Controlled ReAct contracts, port protocols, and pure state-machine tests.
2. Add fake-port Orchestrator `start` and `resume` behavior.
3. Adapt existing planner, review, policy, retrieval, tool, answer synthesis, projection, lock, and snapshot implementations behind the ports.
4. Route Delivery through the Orchestrator while preserving the external `WorkflowTemplateExecutionResult` handoff.
5. Run shadow verification against representative historical V3 inputs.
6. Delete legacy LangGraph/runtime paths, manifest runtime selector semantics, old runtime tests, and active documentation that still describes the retired path.

The rejected alternative is a horizontal rewrite that adds all tests first or rewires every layer before one end-to-end slice works. That would create imagined tests, increase merge risk, and make it harder to prove which behavior is already governed by the new Orchestrator.
