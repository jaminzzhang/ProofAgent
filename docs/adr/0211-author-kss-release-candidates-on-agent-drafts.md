---
status: accepted
---

# Author exact KSS Release candidates on Agent Drafts

[FRAME | HIGH] Agent authoring needs an interactive Knowledge configuration without
restoring the deleted ProofAgent Knowledge Source, Hybrid binding, ingestion, or
retrieval authorities. A Draft Agent therefore may store one secret-free **Draft KSS
Release Binding Candidate** containing the exact Knowledge Space, Knowledge Base,
Knowledge Base Version, and queryable Knowledge Base Release identities selected from
the live KSS catalog. It is first-class Draft state, not Agent Contract YAML, a
package manifest binding, or an untyped advanced field.

[DECISION | HIGH] The Agent Configuration Workspace validates the complete identity
tuple against a ready KSS catalog before saving it with Draft revision CAS, Draft
operation audit, and global audit in one Configuration Unit of Work. KSS remains the
only owner of catalog and Release lifecycle state. ProofAgent stores no KSS source
configuration, credential, scorer configuration, content, or mutable `latest`
pointer, and it never falls back to a local Knowledge implementation.

[BOUNDARY | HIGH] The Draft candidate is authoring intent and is not executable. A
formal production publication must revalidate that exact Release and combine it with
the deployment-owned **Production KSS Binding Profile** containing binding identity,
versioned client credential reference, Admission Scorer identity and revision, and
required failure mode. Only Phase F publication may freeze the resulting
`ResolvedKnowledgeSourceServiceBinding` into a Published Agent Version. Saving a
candidate does not change the active version or the current question-answer runtime.

[RISK | HIGH] A KSS Release may retire after Draft save, and a deployment profile may
not be compatible with the chosen Release. Dashboard projections therefore show
current catalog state without claiming runtime activation, while publication remains
fail-closed and must repeat live validation. Production validation, publication,
activation, and rollback endpoints remain outside this authoring slice.
