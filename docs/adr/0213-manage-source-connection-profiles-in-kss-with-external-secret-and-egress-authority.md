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

[LIMIT | HIGH] The current `KSS_SNAPSHOT_CONNECTIONS_JSON` registry remains an
implementation fact until a separately verified cutover. This ADR defines the
target authority boundary; it is not evidence that dynamic profile management is
already implemented or production-ready.
