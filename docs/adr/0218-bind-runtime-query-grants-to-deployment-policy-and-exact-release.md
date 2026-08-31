---
status: accepted
---

# Bind runtime Query grants to deployment policy and exact Release

[FRAME | HIGH] Provisioning a runtime Knowledge Query Grant could let a caller
submit a client, Space, strategies, or budgets together with a Release. That would
allow a Draft-to-publication caller to choose deployment authority or widen an
existing client grant. The alternative is to bind those facts before accepting the
Draft-owned exact Release selection.

[DECISION | HIGH] KSS composes one immutable, secret-free Query Grant policy from a
registered runtime client identity, allowed strategies, maximum execution budget,
and effective access-scope digest. A provisioning call accepts only one exact
`knowledge_base_release_id`. KSS derives `knowledge_space_id` from its Release
authority and returns it in a secret-free receipt; callers cannot submit Space,
client, credential, strategy, budget, or scope facts.

[DECISION | HIGH] The Grant identity is content-addressed from the complete policy
and exact Release request. Exact facts replay the same receipt. The existing unique
`(client_id, knowledge_base_release_id)` authority rejects a second policy for the
same binding, so changing strategy, budget, or scope cannot widen a Grant in place.
Queries for another Release, a budget above the Grant, or a client without that
exact Grant fail closed.

[BOUNDARY | HIGH] The runtime Query client and the formal-publication Reference
client remain separate identities and credentials. This decision does not create a
Reference Grant or give the Reference client Query authority. It also does not let
KSS select an Agent Draft Release; a future ProofAgent transport must pass only the
exact Release retained by the validated Formal Production Agent Candidate.

[KNOWN | HIGH] TDD-05K implements the application-only policy/request/receipt seam
over the existing PostgreSQL access-control adapter. An isolated PostgreSQL and KSS
HTTP vertical proves exact replay, KSS-derived Space, no in-place budget widening,
one exact Release, bounded Query admission, and denial for the dedicated Reference
client. No KSS HTTP provisioning endpoint, ProofAgent transport or formal publisher
composition, migration, deployment, real model call, or Production GO is included.

[KNOWN | HIGH] TDD-05L exposes that seam through the authenticated KSS operator
management transport and a provider-neutral ProofAgent guarded adapter. The wire
request still contains only the exact Release, and the adapter strictly revalidates
the secret-free active receipt and returned Release. This does not compose Grant
provisioning into formal publication, add operator-command audit storage, change
production configuration or establish Production GO.

[KNOWN | HIGH] TDD-05N implements ADR-0221 for the checked-in production-local
harness. KSS process configuration strictly loads the secret-free policy, and a
separate hardened bootstrap registers only the matching runtime credential digest.
The isolated PostgreSQL vertical proves Reference → operator Grant → bounded Query
with those checked-in facts. It does not run the production-local full stack, a real
model, formal publication or production access-scope enforcement.
