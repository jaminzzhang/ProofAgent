---
status: accepted
---

# Make KSS the only executable knowledge authority

[FRAME | HIGH] A Published Agent Version that uses knowledge binds exactly one
Knowledge Source Service (KSS) release through
`ResolvedKnowledgeSourceServiceBinding`. The binding fixes the Knowledge Space,
Knowledge Base Release, client identity, versioned client-secret reference,
ProofAgent-owned Admission Scorer identity and revision, and required failure
mode. Package-embedded, shared-source and Hybrid bindings are invalid execution
inputs; manifests cannot contribute knowledge bindings.

[FRAME | HIGH] KSS owns Source ingestion, immutable versions, Base Releases,
retrieval and Candidate Evidence. ProofAgent owns Candidate Evidence admission,
conflict handling, context assembly and the final answer. KSS ranking and
lane-native scores are diagnostics only and can never be interpreted as an
Evidence Admission Score. Missing or invalid KSS credentials, exact Release,
client grant or Admission Scorer fail closed; production has no local knowledge
fallback.

[DECISION | HIGH] Remove the old executable Hybrid implementation from
ProofAgent, including its provider registry, ingestion and publication workers,
source-management API, repositories, CLI and deployment roles, and Dashboard
configuration surface. Historical ADRs, database migrations and audit records
may remain as migration history, but they do not authorize an executable legacy
path. KSS's own Knowledge Worker remains part of the independent service.

[RISK | HIGH] Published Agent Versions that contain the former Hybrid or shared
knowledge binding shapes can no longer be deserialized, replayed or used as a
rollback target. This breaking consequence was explicitly accepted for the
cutover. Operational rollback must select another Published Agent Version with
an exact, available KSS binding; restoring the deleted ProofAgent Hybrid runtime
is not a supported recovery procedure.

[LIMIT | HIGH] Acceptance of this architecture and local implementation does not
approve a production release. Production cutover still requires an approved and
calibrated Admission Scorer revision, exact Client Grant, versioned secret
provisioning, dependency readiness, shadow and pilot evidence, recovery drills,
and the normal Product Release Authority decision.
