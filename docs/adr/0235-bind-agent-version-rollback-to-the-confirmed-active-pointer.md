---
status: accepted
---

# Bind Agent Version rollback to the confirmed active pointer

[KNOWN | HIGH] ADR-0234 revalidates a rollback target's exact KSS Release and the
immutable target before the local activation transaction. The existing public
rollback command still derives its pointer expectation only after the request arrives.
A user can therefore confirm rollback while version A is active, then unknowingly
apply the same target after another command has changed the active pointer to version B.

[DECISION | HIGH] `AgentConfigurationWorkspace.rollback_version()` requires an
`expected_active_version_id` supplied by the calling command. `None` explicitly means
that the caller expects no active version. The Workspace reads the current pointer with
the immutable target and rejects a mismatch before any KSS catalog call. After the KSS
Release preflight, the write Unit of Work rereads both target and pointer; either drift
returns `active_agent_version_conflict` without activation or audit. The activation
record's pointer expectation and `rollback_from_version_id` both use the caller-confirmed
value rather than a newly adopted pointer.

[DECISION | HIGH] The existing development rollback HTTP contract carries the required
expected pointer, and the existing Dashboard confirmation submits the active version
snapshotted when that dialog opens. A later page rerender cannot replace the displayed
or submitted expectation. An omitted field is invalid; a JSON `null` is the explicit
no-active expectation. The Production configuration router remains unchanged and keeps
`can_rollback=false` in this slice.

[CONSEQUENCE | HIGH] A stale confirmation fails closed before KSS or persistence writes.
Concurrent pointer movement after the initial check is still fenced by the write-time
comparison and repository compare-and-swap. This does not make rollback idempotent: a
response-loss retry with the old expectation conflicts and requires the caller to reload
the current version state.

[BOUNDARY | HIGH] TDD-06E changes the existing Workspace contract, development HTTP
request and Dashboard call only. It does not expose a Production rollback endpoint,
alter permissions, call a real KSS Query or model, create a Grant or Reference, enter
Phase F, publish a Version, deploy, execute a rollback, or grant Production GO.
