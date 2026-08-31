---
status: accepted
---

# Recover formal publication commands with fenced leases

[KNOWN | HIGH] A formal publication command reserves an `in_progress` receipt before
Phase F, KSS Reference registration, Query Grant staging and online smoke. Before this
decision, a process exit left that receipt durable but permanently non-executable:
every exact retry returned `202 in_progress`.

[DECISION | HIGH] Each new `in_progress` command owns one internal execution claim with
a database-time lease, opaque process owner and monotonic fencing token. An exact
`POST` replay before lease expiry returns the existing receipt and performs no external
work. An exact replay after expiry may atomically take over the command and increment
the fence. Only the current fenced claim may commit success or failure.

[DECISION | HIGH] The deployment owns the lease duration. The accepted range is 1–3600
seconds and the checked-in production-local value is 900 seconds. Request bodies and
browser state cannot select the lease, owner or fence. PostgreSQL `clock_timestamp()`
is the lease-time authority; the application clock is not used to decide takeover.

[DECISION | HIGH] Phase F Record, provisional Version and validation Run identities are
derived from the durable command ID. Their Phase F timestamp is the original command
`started_at`. A takeover therefore repeats the same Reference request and idempotency
key rather than creating a second provisional external resource identity.

[BOUNDARY | HIGH] TDD-05S adds no background scanner, heartbeat, cancel command,
Dashboard control, publication approval or automatic formal publication. It does not
renew a lease while an execution is running. Expiry alone does not invalidate the
current attempt; a later successful takeover increments the fence and prevents the old
attempt from committing Version, Active pointer, command receipt or audit.

[CONSEQUENCE | HIGH] Migration `0023_formal_publish_claim` is expand-only. Existing
terminal commands remain replayable with null claim columns. A legacy `in_progress`
row without claim data is eligible for a first fenced takeover. Upstream side effects
that completed before a process exit remain governed by their own idempotency and
retention rules; this slice does not add Reference deregistration or Grant revocation.

[BOUNDARY | HIGH] A takeover still reassembles and revalidates the exact candidate from
the durable Draft revision and current authorities. Persisting an intermediate
candidate checkpoint, running a background recovery process and proving a real
external model smoke are separate slices. This decision is local recovery authority,
not Product Release Authority approval or Production GO.

[KNOWN | HIGH] ADR-0224 and TDD-05T complete the candidate-checkpoint follow-up by
freezing both digests before Phase F. Background recovery and real external-model proof
remain outside this decision.

[KNOWN | HIGH] ADR-0225 and TDD-05U add an actor-owned, exact-resource receipt read.
The read does not replace this ADR's exact `POST` replay authority and cannot acquire or
renew an execution claim.
