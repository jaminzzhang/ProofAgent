# Controlled ReAct State and DTO Placement

Accepted.

Persisted, resumable, or audit-replayable Controlled ReAct DTOs will live in `proof_agent/contracts/controlled_react.py`. This includes `ControlledReActRunState`, `ControlledReActRunStateSnapshot`, and `ObservationRecord`.

Internal state-machine implementation types will live under `proof_agent/control/workflow/controlled_react/`. This includes `TransitionCommand`, `EffectResult`, transition step types, and other private orchestration mechanics. These types are not public contracts and should not be persisted, exposed through Delivery, or used as observability payloads.

The rejected alternative is putting all Orchestrator types into `contracts/` for convenience. That would freeze private implementation mechanics as product contracts and make later state-machine refactors unnecessarily expensive.
