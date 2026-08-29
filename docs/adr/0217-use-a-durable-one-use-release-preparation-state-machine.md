---
status: accepted
---

# Use a durable one-use Release Preparation state machine

[FRAME | HIGH] Starting Knowledge Base Release Preparation creates one durable
public resource bound to an exact Base Draft revision and immutable request
fingerprint. Its minimal lifecycle is `queued`, `running`, `ready`, `failed`,
`cancelled`, `expired`, or `consumed`. `ready` is a non-queryable immutable candidate
with `expires_at`; `consumed` identifies the exact Knowledge Base Release created by
the successful one-use publication transaction.

[DECISION | HIGH] The create command is operator-scoped and idempotent. Replaying
the same Idempotency-Key and fingerprint returns the same Preparation, while reusing
the key with different input is a conflict. Failed, cancelled, expired, and consumed
Preparations cannot be retried or republished; a retry creates a new Preparation
identity and audit history. Publication accepts only one unexpired `ready` candidate,
revalidates all frozen identities in a short compare-and-swap, and atomically records
its transition to `consumed` plus the exact Release identity.

[BOUNDARY | HIGH] Workers claim queued or recoverable running work with leases and
monotonic fencing tokens. A stale or expired claim cannot publish artifacts or
overwrite a newer attempt. Cancellation is cooperative for queued/running work and
never turns partial artifacts into runtime authority. Dashboard polls the public
resource and renders its stable blockers; it does not infer transitions or
orchestrate hidden retries.

[LIMIT | HIGH] This refines ADR-0205 and reuses the existing KSS lease/fencing
approach. TDD-02A through 02G implement the local durable state machine and trusted
application-only execution/publication/cancellation/expiry core; TDD-04C exposes only
Draft save/exact read and Preparation start/status through the ProofAgent same-origin
BFF. TDD-04D composes the existing execution core behind an optional one-shot
`run_once()` runtime handle, without enabling it in the API runtime by default.
TDD-04E exposes the existing publication CAS through a KSS management command and a
ProofAgent same-origin BFF. Both reject request bodies and return the consumed current
state; ProofAgent requires the existing edit permission, while KSS requires trusted
operator authentication. Uncertainty is recovered through the exact Preparation GET
rather than a new idempotency receipt. TDD-04F exposes the existing cooperative
cancellation transaction through no-body KSS and ProofAgent `:cancel` commands. Both
require an `Idempotency-Key`; ProofAgent requires the existing edit permission, and
KSS binds replay to the trusted operator, exact Preparation identity and action.
There is still no continuous Preparation process role, scheduler, expiry BFF,
Dashboard operation
or system-wide removal of the direct synchronous Release bypass.
Local design and tests are not production readiness or a formal Release GO.
