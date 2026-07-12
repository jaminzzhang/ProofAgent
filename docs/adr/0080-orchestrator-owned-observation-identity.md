# Orchestrator-Owned Observation Identity

Accepted.

The Orchestrator will allocate `observation_id`, `truth_ref`, and the observation commit key deterministically before executing an Observation Action. Observation adapters must echo the allocated identity in their Observation Effect and must not generate observation ids or truth refs.

We choose this over adapter-generated identity because retry, resume, deduplication, and audit replay need stable ids independent of provider or adapter behavior. Deterministic Orchestrator-owned identity keeps the commit boundary idempotent.

Amendment: the pre-action `truth_ref` is a stable base identity (`observation://<run>/<observation>/truth`), not the final artifact reference. Observation Commit binds the complete typed truth payload to canonical, versioned JSON and derives the committed `truth_ref` by appending `/sha256/<digest>`; the committed Observation Record and trace projection use that digest-bearing reference. A retry with the same identity and payload resolves to the same reference, while a different payload for that identity conflicts rather than overwriting truth. Adapters echo the allocated base identity and never choose the committed reference.

The bundled file-backed snapshot and truth adapters require anchored POSIX `dir_fd`, `O_NOFOLLOW`, and hard-link publication capabilities. They fail closed when those primitives are unavailable; another platform must provide a storage adapter with an equivalent race-resistant containment guarantee rather than use a weaker path-based fallback.
