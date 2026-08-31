---
status: accepted
---

# Register executable client Release references in KSS

[FRAME | HIGH] KSS owns a durable Knowledge Base Release Reference Ledger. Every
Agent runtime or other registered client creates an idempotent reference containing
its authenticated client identity, immutable external resource identity, exact
Knowledge Base Release identity, lifecycle purpose, and audit timestamps. A
Published Agent Version remains referenced while it may execute or be selected as a
rollback target, not only while it is the client's active version.

[DECISION | HIGH] A client registers the exact reference before making its external
resource executable. Reference registration and ordinary retirement are serialized
inside KSS: registration is allowed only for an admissible Release state, while
retirement checks zero executable references and retention eligibility in the same
KSS authority boundary. KSS never accepts a retirement caller's unverified claim
that another client's reference count is zero and does not synchronously query one
particular Agent product as its reference authority.

[BOUNDARY | HIGH] Cross-service publication uses conservative ordering rather than
a distributed transaction. If reference registration fails, ProofAgent must not
activate the Agent Version. If subsequent ProofAgent publication or activation
fails, the registered reference may remain and delay ordinary retirement; this is a
safe orphan, not permission to compensate by deleting the reference immediately.
An idempotent reconciler may remove it only after the owning authenticated client
proves that the immutable external resource is neither executable nor retained for
rollback. Deregistration failure also leaves the reference in place.

[RISK | HIGH] Emergency Release revocation defined by ADR-0215 may bypass ordinary
reference protection and makes affected clients fail closed. Reference rows contain
trace-safe identities and lifecycle facts, not Agent configuration, user content, or
credentials.

[KNOWN | HIGH] TDD-03A through 03D implement the application-only Reference Ledger,
registration, trusted deregistration admission and ordinary-retirement gate. The
deregistration request carries only exact Reference identity; a server-injected
verifier must return matching trace-safe proof identity before KSS atomically records
`deregistered`. ProofAgent's verifier adapter, proof issuance, background reconciler,
network commands, production configuration and emergency revocation remain
unimplemented, so no production reconciliation flow is claimed.

[KNOWN | HIGH] TDD-05C implements the ProofAgent-side application port and strict
Reference-first staging contract. Control derives a stable idempotency key from the
exact provisional version ID, submits the Draft-owned Space/Base/Release for the
future `published_agent_version`, and requires an exact active receipt. Receipt drift
or uncertainty fails closed without compensating deregistration, preserving the safe
orphan rule above. This is port-level local evidence only: the authenticated KSS HTTP
transport, production adapter, publisher consumption and reconciler remain
unimplemented.

[KNOWN | HIGH] TDD-05D exposes registration through KSS's public client API and adds
the concrete ProofAgent guarded registrar. KSS derives client identity only from its
Bearer authenticator, requires an HTTP idempotency key, accepts no caller-reported
client identity, and maps conflict, inadmissible Release, Scope, validation, storage
and integrity failures to stable non-echoing problems. The production-shaped runtime
composes the existing PostgreSQL Reference repository, and an isolated
ProofAgent-to-ledger vertical proves exact replay produces one durable active
Reference and one audit. Deregistration, reconciliation, publisher consumption,
production credential/egress composition and deployment remain unimplemented.

[KNOWN | HIGH] TDD-05J adds the checked-in production-local contract for the dedicated
Reference client: a separate versioned Secret Handle and Vault fixture, an idempotent
KSS service-client identity bootstrap before KSS API startup, and production composition
rejection when the Reference Handle aliases the operator or runtime Query Handle. The
isolated PostgreSQL vertical records the dedicated authenticated client on the exact
Reference and proves the same credential cannot issue a Query without an exact-Release
Query Grant. The existing `knowledge_client_grants` authority remains Query-specific;
this slice does not invent a Reference Grant, add a migration, run the production-local
stack or prove production deployment readiness.

[KNOWN | HIGH] TDD-05K and ADR-0218 add the separate application-only runtime Query
Grant core. Deployment-owned policy and a Draft-supplied exact Release produce the
Query-specific receipt; the Reference client remains outside that policy and remains
unable to Query. No Reference lifecycle behavior or authorization is changed.
