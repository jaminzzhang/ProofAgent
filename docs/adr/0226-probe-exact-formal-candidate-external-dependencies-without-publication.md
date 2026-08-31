---
status: accepted
---

# Probe exact Formal Candidate external dependencies without publication

[KNOWN | HIGH] Production composition already contains the exact Draft Candidate
assembler and governed KSS/model execution path. The checked-in production-local Phase F
compatibility endpoint deliberately returns `authorized=false`; using it as approval or
bypassing it to call the formal publication endpoint would weaken the release boundary.
The older production-local QA verifier also loads a deployment manifest instead of the
operator-reviewed exact Draft revision.

[DECISION | HIGH] TDD-05V adds one explicitly invoked production-local probe. The host
entry accepts only exact `agent_id`, `draft_id` and positive `draft_revision`. The same
production composition assembles the Candidate, so the Draft selects the exact KSS
Release and model-role configuration while the deployment supplies the Binding Profile,
Secret Handles, egress policy and Admission Scorer. The probe question is a checked-in,
non-sensitive deployment fixture; the caller cannot select a Release, model connection,
credential, Profile or execution budget.

[DECISION | HIGH] The probe materializes the exact Candidate Contract Bundle in a private
temporary directory and executes one `RunPurpose.VALIDATION` run through the governed
KSS-only runtime, Evidence Admission and configured external model. It requires
`ANSWERED_WITH_CITATIONS` and at least one accepted nonblank citation. Trace and receipt
are retained through the existing immutable artifact store with exact read-back.

[DECISION | HIGH] Success output is secret-free and excludes the question, answer,
Candidate content, Evidence content, credentials, raw prompts and upstream error detail.
It records exact Candidate and Release identities, a SHA-256 of the fixed probe question,
the model connection identifiers, validation run identity, cited outcome and exact
trace/receipt artifact references. Known failures produce one stable bounded JSON result
and exit nonzero.

[CONSEQUENCE | HIGH] The run may create one durable KSS Knowledge Query and two immutable
ProofAgent validation artifacts. It must reuse an already active exact-Release Query Grant.
It does not create or replay a Formal Publication Command, Phase F authorization,
KSS Reference, Query Grant, Published Agent Version or Active pointer. Missing Grant,
unavailable KSS, Admission, model, credential, egress or artifact dependency fails closed.

[BOUNDARY | HIGH] This probe is external-dependency evidence only. It is not the formal
online-smoke qualification because it has no Phase F authorization or active KSS Reference.
It is not publication approval, a release Gate, deployment approval or Production GO. No
HTTP/Dashboard surface, caller-supplied question, grant mutation, recovery process,
rollback, lifecycle reconciliation or production deployment is added.
