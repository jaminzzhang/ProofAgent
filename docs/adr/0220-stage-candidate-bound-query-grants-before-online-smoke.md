---
status: accepted
---

# Stage candidate-bound Query Grants before formal online smoke

[FRAME | HIGH] The formal publication path currently registers an exact KSS
Reference and then runs online smoke. The runtime Query client cannot execute that
smoke unless KSS has already provisioned an exact-Release Query Grant. Letting the
smoke runner or a caller choose Grant policy facts would let an execution identity
expand its own authority.

[DECISION | HIGH] ProofAgent adds one Control-owned Query Grant staging step after
`FormalProductionAgentReferenceStaging` and before formal online smoke. The stager
derives the only request field, `knowledge_base_release_id`, from the validated
Formal Production Agent Candidate. It calls the provider-neutral
`KnowledgeQueryGrantProvisioner`, strictly validates the secret-free active receipt,
and requires its Release and Knowledge Space to match the Candidate.

[DECISION | HIGH] Formal online smoke accepts
`FormalProductionAgentQueryGrantStaging` as its explicit staging input. The nested
Reference staging remains the authority for Candidate, provisional Version and
Reference identities; the Query Grant receipt proves only that KSS provisioned the
runtime client's policy-bounded exact-Release query authority. It does not publish
or activate an Agent and does not replace KSS authorization at Query time.

[DECISION | HIGH] A successfully provisioned Grant remains durable if downstream
smoke or publication fails. TDD-05M does not attempt an unsafe compensating revoke:
the existing KSS contract has no selective Grant-revocation command, and uncertainty
must not be converted into an unproved cleanup result. The residual Grant is limited
to one exact Release and immutable deployment policy, while ProofAgent still controls
whether a user-facing run can start. Selective revocation, reconciliation and
operator-command audit require separate decisions and tests.

[BOUNDARY | HIGH] TDD-05M reuses the existing KSS operator Secret boundary for the
guarded provisioner and does not add a Secret Handle, egress rule, SQL migration,
Dashboard or BFF surface. It does not run a real model, change production-local
configuration, deploy, publish a Release or establish Production GO.

[KNOWN | HIGH] TDD-05N separately supplies the checked-in production-local immutable
policy and runtime client bootstrap under ADR-0221. It verifies the Reference → Grant
transport order against isolated PostgreSQL but does not invoke this complete formal
publication path or change the conservative residual-Grant semantics above.
