# Production Runs Use an Internal PostgreSQL Queue and Run Executor

Accepted.

Partially superseded by ADR-0129 for fine-grained progress replay and S3-first artifact finalization.

[FRAME | HIGH] Proof Agent owns a PostgreSQL-backed Production Run Queue inside the existing product boundary. The API persists an accepted governed run request and returns its identity; a Run Executor launched from the same Proof Agent image claims work with leases, enforces the global five-run concurrency limit, and records progress and terminal state. The Run Executor is a process role without a public business API, not an independently deployed microservice or the future Sandbox Execution Service.

[FRAME | HIGH] The initial release does not add Redis, RabbitMQ, Celery, or another queue platform. PostgreSQL provides durable admission, bounded ordering, cancellation state, lease expiry, and restart recovery. During Blue/Green deployment, only the active application slot may hold the executor activation lease and claim new work; the previous slot drains or relinquishes claims before the candidate becomes active.

[FRAME | HIGH] Run submission requires CSRF protection and an idempotency key. The API transactionally admits capacity and returns the same run identity for a repeated key. When a Run Executor claims the request, it freezes the Published Agent Version, Knowledge Snapshot, model connection version, Production Egress Policy version, and Production Secret Handle identifiers into a Production Run Execution Snapshot; later configuration changes do not alter that run.

[FRAME | HIGH] Queue and execution progress is persisted as trace-safe ordered state and exposed through a reconnectable Run Progress Stream. A disconnected browser does not cancel execution and may resume after its last event. Raw model output is not streamed to the audience before Control Envelope validation; only trace-safe progress and the validated final projection are revealed. Lease recovery, cancellation, timeout, and terminal commit are idempotent state transitions.
