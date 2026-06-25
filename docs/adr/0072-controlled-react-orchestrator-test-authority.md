# Controlled ReAct Orchestrator Test Authority

Accepted.

The V3 **Controlled ReAct Orchestrator** becomes the authority for orchestration correctness tests. The required test layers are:

1. Pure state-machine tests for action constraints, loop convergence, outcome taxonomy, transition commit behavior, and idempotency.
2. Fake-port integration tests for retrieval observation, tool observation, approval pause, approval resume, snapshot restore, and diagnostic stops.
3. Delivery smoke tests proving `RunExecutionService -> ControlledReActOrchestrator -> WorkflowTemplateExecutionResult -> Governance Receipt / RunStore / Dashboard projection`.

Tests currently built around `run_with_langgraph`, `resume_langgraph_approval`, LangGraph checkpoint state, or old React runtime graphs should be migrated only when they assert still-current V3 semantics. Tests that assert retired execution mechanics or old trace parity should be deleted.

The rejected alternative is keeping legacy runner tests as the regression source of truth while adding Orchestrator tests beside them. That would let retired runtime behavior continue to veto the new architecture and would blur the acceptance gate.
