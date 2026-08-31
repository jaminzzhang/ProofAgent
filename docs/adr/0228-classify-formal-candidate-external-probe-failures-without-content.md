---
status: accepted
---

# Classify Formal Candidate external probe failures without content

[KNOWN | HIGH] The TDD-05V external-dependency probe currently returns one generic
`formal_candidate_external_smoke_failed` code for failures after exact Candidate
materialization. Draft@14 proved that an exact KSS Query can succeed while a later stage
fails without retained validation artifacts. The generic code cannot tell an operator
whether to inspect KSS, Evidence Admission, the configured model, citation validation or
artifact retention.

[DECISION | HIGH] TDD-05X adds five stable, secret-free failure codes to the existing
probe CLI contract:

- `formal_candidate_external_smoke_kss_failed` means the governed run failed through the
  exact KSS query boundary.
- `formal_candidate_external_smoke_evidence_admission_failed` means Candidate Evidence
  could not be scored or no evidence was accepted.
- `formal_candidate_external_smoke_model_failed` means configured model transport,
  output normalization or non-citation final-answer validation failed.
- `formal_candidate_external_smoke_citation_validation_failed` means accepted evidence
  lacked a formal citation or final-answer citation binding failed.
- `formal_candidate_external_smoke_artifact_retention_failed` means local trace/receipt
  validation, immutable artifact write or exact read-back failed.

[DECISION | HIGH] Classification uses existing structured error codes and trace-safe
workflow facts. It does not parse exception messages, provider responses, answers or
Evidence content. `PA_KNOWLEDGE_002` identifies the KSS boundary,
`PA_KNOWLEDGE_001` identifies Evidence Admission on this exact KSS execution path, and
`PA_MODEL_*` identifies configured-model failures. A returned run is classified from
accepted citation facts and the stable `final_answer_validation_failed` error code.
Unknown exceptions remain `formal_candidate_external_smoke_failed`.

[DECISION | HIGH] The CLI emits only its existing failure schema, `status` and one stable
`error_code`. It never emits the question, answer, Candidate or Evidence content,
credential, Secret Handle, raw prompt, provider identity, provider detail, exception
message, stack trace, artifact bytes or local path. The diagnostic exception may carry
only the stable code and must remain a subtype of the existing validation error.

[CONSEQUENCE | HIGH] The governed execution path, exact Candidate and Release identity,
fixed probe question, call budget, artifact format and success result do not change.
TDD-05X does not add an alternate executor, retry, HTTP or Dashboard surface, dependency
call, Grant mutation, publication side effect or migration. Existing generic failure
handling remains the fail-closed result when structured facts are absent or ambiguous.

[BOUNDARY | HIGH] These codes identify the last safely attributable probe stage; they do
not prove a provider root cause or disclose its response. Local tests of the classifier
do not constitute external-dependency evidence, formal online-smoke qualification,
publication approval, a release Gate, deployment approval or Production GO. Any later
real external probe requires a new explicit authorization for that exact run.
