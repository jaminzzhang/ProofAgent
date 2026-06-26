# Observation Type Placement Boundary

Accepted.

Observation Truth Artifact variants and Answer Evidence Context are persisted, resumable, or audit-replayable DTOs, so they belong in `proof_agent/contracts/controlled_react.py`. Observation Effect, Observation Identity, Observation Commit Result, Observation Summary Builder, and commit implementation types are private Orchestrator mechanics under `proof_agent/control/workflow/controlled_react/`; ObservationTruthStorePort is a Control Plane port protocol.

We choose this split because truth artifacts and answer contexts must remain stable across persistence, resume, audit replay, and tests, while effect and commit mechanics should stay refactorable implementation details.
