---
status: accepted
---

# Bind formal production Agent publication to an exact Draft revision

[FRAME | HIGH] Formal production Agent publication is rooted in one named Draft
Agent and exact Draft revision. The publisher loads that revision from the Agent
Configuration Store, revalidates its secret-free Draft KSS Release Binding
Candidate against the live KSS catalog, and combines it with the deployment-owned
Production KSS Binding Profile and candidate-bound release evidence before online
smoke, immutable Published Agent Version creation, and PostgreSQL activation.

[DECISION | HIGH] An independently loaded manifest, mutable latest Draft, Dashboard
readiness projection, or deployment-selected KSS Release is not a formal production
candidate. Knowledge management, Draft editing, and Release publication remain
separate permissions and commands; no Knowledge or Draft save command activates an
Agent. We accept the extra identity and freshness checks so the configuration an
operator reviews is the configuration the formal publisher evaluates and freezes.

[RISK | HIGH] If the Draft revision changes, the KSS Release becomes unqueryable,
the deployment profile is incompatible, or Phase F or online smoke fails, publication
fails closed without changing the Active Agent Version. This accepted design does
not claim that the current publisher implementation already consumes Draft state.

[KNOWN | HIGH] TDD-05A implements the first read-only boundary of this decision. A
Control-owned assembler loads one named Draft and exact revision from the Agent
Configuration Store, reuses the server-authoritative publication projector to
revalidate the live versioned KSS catalog, and combines the Draft-owned Release with
a strict deployment-owned binding profile. It returns an immutable candidate with
separate Knowledge Release and formal-candidate digests and performs no write. The
existing formal publisher still accepts an independent manifest and environment-built
Release binding; KSS Reference registration, Phase F, smoke, publication and
activation cutover remain subsequent work.

[KNOWN | HIGH] TDD-05B implements the next application-only boundary. Control
revalidates both candidate digests, resolves Workflow Stage availability, seals four
distinct exact evidence artifacts into an immutable Formal Phase F Record bound to
the formal-candidate and Knowledge Release digests, and requires an independent
authority to approve that record. The result is a `ProvisionalProductionAgentVersion`
with `prepared_at/prepared_by`; it is neither published nor active. The existing
publisher, KSS Reference registration, online smoke, store/audit writes and activation
remain unchanged.

[KNOWN | HIGH] TDD-05C adds a Reference-first staging boundary after Phase F
preparation. Control derives one deterministic idempotency key from the exact
provisional version ID and asks an injected authenticated KSS registrar to register
the Draft-owned Space/Base/Release for `execution_or_rollback`. The Phase F Record now
also binds the provisional version and validation run identities, so the external
resource cannot drift before registration. A mismatched receipt fails closed and may
leave a conservative orphan Reference, as required by ADR-0216. Only the port and
strict local contracts exist; KSS transport, publisher consumption, smoke, persistence
and activation remain subsequent work.

[KNOWN | HIGH] TDD-05D implements the authenticated transport behind that port.
ProofAgent uses a dedicated HTTPS guarded registrar and service-client authorization
factory; it sends the exact TDD-05C request and idempotency key, rejects redirects and
wire or identity drift, and maps the strict KSS resource into the local receipt. KSS
exposes a Bearer-client `POST /v1/knowledge-base-release-references` backed by its
existing PostgreSQL ledger. This closes transport and durable registration only; the
formal publisher still does not consume staging, run online smoke, write an immutable
Published Version, or update the Active pointer.

[KNOWN | HIGH] TDD-05E adds the next application-only Control boundary. It accepts
only a validated staging with an active registered Reference, derives a strict smoke
request from the exact candidate, provisional version, validation run, Release and
Reference identities, and requires a validator result that answers with at least one
governed citation plus distinct exact trace and receipt artifacts. The successful
qualification is explicitly unpublished and inactive. Failure or uncertainty cannot
write an Agent Store or Active pointer because those ports are absent, and cannot
remove the already registered Reference because no deregistration authority is
injected. A real online runner, formal publisher consumption and atomic publication/
activation remain subsequent work.

[KNOWN | HIGH] TDD-05F implements the application-only formal publisher core for
this decision. After exact candidate assembly and Phase F, it captures the current
Active pointer expectation in a short read-only Configuration UoW and closes that
transaction before Reference registration and online smoke. A successful smoke is
sealed with the exact Draft revision, Phase F Record and active Reference receipt in
one strict formal evidence envelope. A final UoW atomically enforces Draft revision
and Active pointer CAS, persists the immutable Published Version and activation, and
appends publication audit. Concurrency or audit/storage failure rolls back all final
writes while retaining the registered KSS Reference. The old manifest publisher and
runtime composition remain unchanged; real online execution and a persisted-idempotency
public command are still subsequent work, so this is not yet the system-level unique
formal publication entry.

[KNOWN | HIGH] TDD-05G implements the concrete online smoke runner behind the
TDD-05E boundary. Control passes the strict request together with the same validated
Reference staging; the runner revalidates their exact candidate, version/run, digest,
Space/Base/Release and Reference identities, safely materializes the provisional
Contract Bundle as a private read-only temporary package, and reuses governed
execution with validation purpose and frozen runtime facts. Only accepted chunks with
nonblank citations count, while bounded Trace and Receipt artifacts require immutable
write and exact read-back. TDD-05E remains the qualification authority. The old
publisher/runtime composition, public durable-idempotency command and environment-
backed live KSS/model validation remain subsequent work, so this adapter is not
Production GO.

[KNOWN | HIGH] TDD-05M inserts the ADR-0220 Query Grant staging boundary between
Reference registration and online smoke. Control derives the sole provisioning field
from the exact Formal Candidate Release, validates the active receipt's Release and
KSS-derived Space, and passes the resulting strict staging to both smoke Control and
the concrete runner. The formal publisher and production composition use this single
path; the old Reference-only smoke input is removed. A Grant remains durable when a
later smoke or publication step fails because no selective revoke authority exists.
This is an explicit residual authorization risk, not an activation result or
Production GO.
