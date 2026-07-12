# Orchestrator-Owned Observation Identity

Accepted.

The Orchestrator will allocate `observation_id`, `truth_ref`, and the observation commit key deterministically before executing an Observation Action. Observation adapters must echo the allocated identity in their Observation Effect and must not generate observation ids or truth refs.

We choose this over adapter-generated identity because retry, resume, deduplication, and audit replay need stable ids independent of provider or adapter behavior. Deterministic Orchestrator-owned identity keeps the commit boundary idempotent.

Amendment: the pre-action `truth_ref` is a stable base identity (`observation://<run>/<observation>/truth`), not the final artifact reference. Observation Commit binds the complete typed truth payload to canonical, versioned JSON and derives the committed `truth_ref` by appending `/sha256/<digest>`; the committed Observation Record and trace projection use that digest-bearing reference. A retry with the same identity and payload resolves to the same reference, while a different payload for that identity conflicts rather than overwriting truth. Adapters echo the allocated base identity and never choose the committed reference.

The bundled file-backed snapshot and truth adapters require an application-owned private root beneath a trusted, non-renamable ancestor chain plus POSIX `dir_fd`, `O_NOFOLLOW`, hard-link publication, and `flock` capabilities. A persistent private root lock serializes publication and read-back across threads and processes so no caller can accept an artifact that another in-flight publisher later rolls back. The adapters fail closed when these prerequisites are unavailable and remain development/test implementations only. Descriptor anchoring and publication serialization detect path substitution and known commit races but are not a sandbox boundary against an arbitrary process running under the same effective user. Production and any environment with same-UID untrusted execution must use the isolated S3-compatible artifact adapter defined by ADR-0109, not a weaker local path fallback.
