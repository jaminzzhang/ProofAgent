---
status: accepted
---

# Provision Query grants through the KSS operator transport

[FRAME | HIGH] A runtime Query client must not authenticate a command that grants
itself access. Reference registration credentials are also intentionally separate
from runtime Query credentials. Reusing either service-client boundary for Grant
provisioning would let a lower-authority identity request a new executable
authorization.

[DECISION | HIGH] KSS exposes `POST /v1/knowledge-query-grants` only through its
existing authenticated operator management boundary. The command requires the
server-configured `knowledge_source.edit` permission. Its strict request contains
only `knowledge_base_release_id`; KSS supplies client identity, strategies,
execution budget and effective scope from the immutable TDD-05K policy, then
derives Knowledge Space from exact Release authority.

[DECISION | HIGH] Exact policy and Release facts replay the same
`knowledge-query-grant.v1` receipt. Durable authority conflicts return a bounded
`409 knowledge_query_grant_conflict`; receipt-integrity failure returns a bounded
`503 knowledge_query_grant_unavailable`. Validation and error responses do not
echo bearer credentials or rejected caller fields.

[DECISION | HIGH] ProofAgent uses a dedicated provider-neutral provisioner port and
a guarded HTTPS adapter. The adapter sends only the exact Release request, rejects
redirects and non-success responses, validates a strict secret-free receipt and
requires the returned Release to match the request. It does not duplicate or
override the KSS deployment policy.

[BOUNDARY | HIGH] TDD-05L does not compose the adapter into the formal publisher,
add a Secret Handle, change production deployment, add SQL or create a separate
operator-command audit store. The durable Grant row and receipt remain Query
authority facts, not complete operator audit evidence. A later composition or audit
slice must preserve the exact Candidate Release and obtain separate approval.

[KNOWN | HIGH] TDD-05M performs the separately approved composition under ADR-0220.
The formal Control path derives the provisioner request from the exact Candidate after
Reference registration and requires the strict Grant staging before online smoke. It
reuses the existing operator Secret boundary and does not add production-local policy,
operator-command audit storage, selective revoke or Production GO.
