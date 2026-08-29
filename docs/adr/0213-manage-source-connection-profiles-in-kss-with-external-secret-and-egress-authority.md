---
status: accepted
---

# Manage Source Connection Profiles in KSS with external secret and egress authority

[FRAME | HIGH] KSS owns the versioned logical lifecycle of every non-secret
Knowledge Source Connection Profile: connector kind, bounded source parameters,
Source association, revision state, validation result, and audit identity. A
synchronization resolves one exact Published Knowledge Source Connection Profile
Revision and records that identity in the resulting Source Version lineage.

[BOUNDARY | HIGH] The secret authority owns credential values; KSS stores only
opaque, versioned Secret Handle references. Deployment policy owns permitted
connector families, Egress Policy, trust roots, and hard resource limits. The
ProofAgent Dashboard may edit trace-safe profile fields and request validation only
through the ProofAgent BFF; neither browser nor ProofAgent becomes profile or
credential authority. A Worker may resolve secrets only for the exact Published
profile revision admitted by deployment policy.

[DECISION | HIGH] Static environment JSON is not the target production authority
for the logical profile lifecycle. Editing or publishing a profile revision never
mutates an existing Source Version, KSS Release, Draft Agent, or Published Agent
Version. Moving new connection facts into production therefore requires a new
synchronization, Source Version, KSS Release, Draft revision, and formal Agent
publication.

[KNOWN | HIGH] TDD-01B implements the KSS PostgreSQL lifecycle, protected
management HTTP and exact-profile synchronization core. TDD-04B adds a guarded
ProofAgent management client and same-origin BFF for create/read/revise/validate/
publish plus synchronization submit/status. Browser responses omit endpoint,
Secret Handle, egress/trust references, KSS credentials and raw upstream problem;
read and mutation paths require `knowledge_source.view` and
`knowledge_source.edit`, respectively.

[LIMIT | HIGH] The current `KSS_SNAPSHOT_CONNECTIONS_JSON` production process
registry remains an implementation fact until a separately verified cutover.
There is no Dashboard page, production Vault/egress/TLS reader, or verified
end-user delegation from ProofAgent identity into KSS audit; KSS currently sees
the configured ProofAgent service operator. These local slices implement the
management boundary but are not production-readiness evidence.
