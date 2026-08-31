---
status: accepted
---

# Bootstrap production-local runtime Query authority

[FRAME | HIGH] The checked-in production-local deployment already supplies a
dedicated runtime Query credential to ProofAgent, but KSS does not register the
matching service-client identity. KSS API process composition also does not load the
immutable Query Grant policy introduced by ADR-0218. The operator provisioning route
therefore remains absent even though the formal publication path now requires Query
Grant staging before online smoke.

[DECISION | HIGH] The KSS API process reads one strict, secret-free
`KSS_QUERY_GRANT_POLICY_JSON` value and validates it as
`KnowledgeQueryGrantPolicy` during process configuration. The value fixes runtime
client identity, allowed strategies, maximum execution budget and effective
access-scope digest. Unknown fields, malformed JSON or invalid policy facts fail
configuration closed. Omitting the complete value retains the existing deployment
choice to expose no Query Grant provisioning route.

[DECISION | HIGH] production-local adds one hardened, non-restarting runtime-client
bootstrap after KSS migration. It registers the existing runtime credential digest
under the exact client identity used by the immutable policy. It creates no Query
Grant. KSS API startup waits for both runtime-client and dedicated Reference-client
registration, then exposes provisioning only through the existing authenticated
operator management boundary.

[DECISION | HIGH] Checked-in contract tests require the policy client identity and
runtime bootstrap identity to match exactly. The Reference identity remains distinct,
and neither service-client credential can authenticate the operator provisioning
command. Per-Release Grant creation remains a later Control request rooted in the
validated Formal Production Agent Candidate.

[BOUNDARY | HIGH] TDD-05N reuses the existing runtime and operator secrets. It does
not add SQL, a Secret Handle, browser or BFF capability, selective revoke,
reconciliation, operator-command audit storage, a real model call or a deployment.
The production-local policy is a checked-in local harness fixture; isolated local
verification does not establish production access-scope enforcement or Production GO.

[KNOWN | HIGH] TDD-05O adds an explicit exact-Release verifier without changing this
authority boundary. Upgrade verification against retained local volumes showed that
the reused runtime token is already durably bound to the local deployment identity
`proof-agent-production-local`. The checked-in local policy, bootstrap and ProofAgent
runtime therefore preserve that identity; the generic bootstrap default remains
`proof-agent-runtime`. Rebinding the retained token to a new client name is forbidden.

[KNOWN | HIGH] The retained local Releases already have immutable historical smoke
Grants whose identifiers and access-scope digests differ from the current policy. The
verifier correctly receives a bounded conflict before Query. TDD-05O does not adopt,
rewrite, revoke or delete those Grants. A positive full-stack replay requires another
existing queryable Release without a conflicting Grant; isolated PostgreSQL evidence
proves the positive deployment-policy → operator Grant → bounded Query path meanwhile.

[KNOWN | HIGH] ADR-0222 supersedes only the active checked-in production-local client
choice after TDD-05O. TDD-05R moves runtime Query authority to a distinct versioned
client and Secret while preserving this ADR's policy/bootstrap/operator separation.
