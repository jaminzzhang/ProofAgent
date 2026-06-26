# Orchestrator-Owned Observation Identity

Accepted.

The Orchestrator will allocate `observation_id`, `truth_ref`, and the observation commit key deterministically before executing an Observation Action. Observation adapters must echo the allocated identity in their Observation Effect and must not generate observation ids or truth refs.

We choose this over adapter-generated identity because retry, resume, deduplication, and audit replay need stable ids independent of provider or adapter behavior. Deterministic Orchestrator-owned identity keeps the commit boundary idempotent.
