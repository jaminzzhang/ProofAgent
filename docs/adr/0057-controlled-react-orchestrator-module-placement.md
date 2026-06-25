# Controlled ReAct Orchestrator Module Placement

Accepted.

The V3 **Controlled ReAct Orchestrator** implementation will live under `proof_agent/control/workflow/`, while its typed run state and snapshot contracts will live under `proof_agent/contracts/`. It must not be implemented under `runtime/`, `capabilities/`, or `delivery/`: Runtime Plane adapters may schedule execution mechanics, Capability modules may execute bounded abilities, and Delivery may start or resume runs, but none of those modules own React Enterprise QA V3 orchestration semantics.

The rejected alternative is placing the Orchestrator near LangGraph or delivery entrypoints to minimize call-site churn. That would keep the old coupling: runtime scheduling or API entry code would again become the seam where planning, approval pause, observation records, convergence, and terminal outcomes are understood. The Control Plane module placement makes those semantics testable through the Orchestrator interface.
