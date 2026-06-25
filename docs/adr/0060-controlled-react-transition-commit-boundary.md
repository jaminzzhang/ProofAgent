# Controlled ReAct Transition Commit Boundary

Accepted.

Each V3 **Controlled ReAct Orchestrator** start or resume operation must execute under a single-run transition lock. A `run_id` may have only one active Orchestrator transition at a time, including observation action execution, approval resume, approval denial handling, and terminal finalization.

The **Controlled ReAct Transition Commit** is the atomic semantic boundary for updating run state or resumable snapshot, emitting trace-safe Workflow Stage projections, writing approval projections, and recording idempotency keys such as `action_id` and `observation_id`. Tool and retrieval adapters may retry inside the transition, but repeated delivery retries must resolve to the same governed action or observation record rather than duplicating execution facts.

The rejected alternative is letting Delivery, Runtime, RunStore, or individual tool adapters coordinate their own partial writes. That would make duplicate approval resumes, repeated tool calls, or mismatched state/trace artifacts possible under concurrent requests.
