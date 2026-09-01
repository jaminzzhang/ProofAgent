---
status: accepted
---

# Revalidate the exact KSS Release before Agent Version rollback

[KNOWN | HIGH] `AgentConfigurationWorkspace.rollback_version()` already selects one
immutable Published Agent Version and atomically changes the Active Agent Version
pointer with an exact pointer expectation and configuration audit. It currently does
not revalidate the target version's KSS Release lifecycle state before that write.

[DECISION | HIGH] A rollback target without a KSS binding keeps the existing local
pointer behavior. A rollback target with a KSS binding must pass a live KSS catalog
preflight before any activation or audit write. The catalog must be ready, the exact
Release identity must resolve to one catalog entry, and that entry must be either
`queryable` or `deprecated`. A formal production version uses the retained Release
Reference's Space, Base and Release tuple. A non-formal version is accepted only when
its immutable Release ID has exactly one catalog match. Missing, ambiguous,
`retired`, `revoked`, unavailable or malformed catalog facts fail closed through a
stable configuration conflict; there is no `latest`, local or legacy fallback.

[DECISION | HIGH] The immutable target is read before the remote preflight, without
holding a PostgreSQL write transaction across the KSS call. The write Unit of Work
then reads the same target again and rejects disappearance or mutation before changing
the active pointer. Successful activation and audit remain one local transaction.

[CONSEQUENCE | HIGH] A `deprecated` Release remains a valid rollback target because
deprecation blocks new adoption but deliberately preserves existing execution and
rollback. Ordinary `retired` and emergency `revoked` Releases cannot be selected by a
new rollback command. Failed preflight creates no activation, audit, KSS Query, Grant,
Reference, Version or other publication state.

[RISK | HIGH] The catalog read and local pointer commit are not a distributed
transaction. An emergency revocation may race after preflight. Existing KSS
Reference rules prevent ordinary retirement while an executable or rollback-eligible
reference remains active, and every later KSS Query must independently reject a
retired or revoked exact Release. This slice does not claim uninterrupted availability
or add a cross-service rollback lease.

[BOUNDARY | HIGH] TDD-06D changes only the existing application rollback service and
its local tests. It does not expose rollback through the production HTTP router, call
KSS Query or an external model, create or deregister References, enter Phase F,
publish or activate a new Agent Version, add a reconciler, change persistence schema,
deploy, or grant Production GO.
