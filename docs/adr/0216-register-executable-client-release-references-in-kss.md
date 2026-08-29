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
