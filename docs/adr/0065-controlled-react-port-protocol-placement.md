# Controlled ReAct Port Protocol Placement

Accepted.

The V3 **Controlled ReAct Orchestrator** effect port protocols will live in `proof_agent/control/workflow/controlled_react/ports.py`. These protocols are internal Control Plane dependency-inversion seams for the Orchestrator, not global product contracts.

Only persisted, serialized, or cross-surface DTOs belong in `proof_agent/contracts/`, such as typed run state, run-state snapshots, approval pause facts, observation records, stage projections, and execution results. Concrete adapters may live in delivery, runtime, observability, capability, or storage modules, but they depend inward on the port protocols rather than the Orchestrator depending outward on concrete services.

The rejected alternative is putting every protocol into `proof_agent/contracts/` or beside runtime entrypoints. That would blur private orchestration seams with public data contracts and make runtime or delivery placement look like ownership of Control Plane semantics.
