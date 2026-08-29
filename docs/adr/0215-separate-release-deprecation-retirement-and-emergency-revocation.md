---
status: accepted
---

# Separate Release deprecation, retirement, and emergency revocation

[FRAME | HIGH] KSS distinguishes ordinary lifecycle cleanup from emergency safety
containment. Deprecating a Knowledge Base Release blocks new Agent Draft bindings
and new formal Agent publications while keeping the Release queryable for already
Published Agent Versions and eligible rollback targets. Deprecation never rewrites
an existing binding or silently selects a replacement Release.

[DECISION | HIGH] Ordinary retirement is allowed only after authoritative reference
checks report no executable Agent or other client reference and the configured
retention requirement is satisfied. A retired Release is non-queryable and only
then becomes eligible for separately authorized physical deletion. Retirement and
deletion are explicit audited commands, not side effects of publishing a newer
Release or moving the Recommended Release pointer.

[BOUNDARY | HIGH] Emergency revocation is a distinct security or severe-data-integrity
command. It may make a referenced Release immediately non-queryable and therefore
causes every pinned query and affected Agent run to fail closed. It requires a
bounded reason, authorized actor identity, audit record, affected-reference summary,
and explicit operator confirmation; availability or routine cleanup is not a valid
reason to bypass reference protection.

[KNOWN | HIGH] TDD-03B through 03F now implement the lifecycle application core,
KSS Reference protection and read-only deletion-eligibility assessment described
here. TDD-04A exposes only that assessment through an authenticated KSS management
GET and a same-origin, secret-free ProofAgent BFF GET; both require
`knowledge_source.view`. Emergency revocation records one
bounded reason, exact confirmation, authorized-operator identity, database time and
KSS-computed affected-active-reference count in the same PostgreSQL transaction as
the `revoked` state and permanent receipt. Only an ordinary `retired` Release with
complete retirement history, zero active References and an explicit clear result from
the server-injected artifact-retention authority is deletion-eligible; deregistered
References remain historical facts, while revoked Releases remain retained for incident
response. The assessment is read-only and is never deletion authority. This still does
not provide lifecycle or Reference command HTTP/BFF authorization,
affected-reference detail projection or notification, ProofAgent runtime/rollback
integration, a production artifact-retention adapter, physical deletion, production
migration or Production GO.
