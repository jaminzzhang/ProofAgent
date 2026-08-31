---
status: accepted
---

# Expose bounded Evidence Admission failure reasons

[KNOWN | HIGH] TDD-05Y proved that the exact Formal Candidate external probe can stop
at Evidence Admission after reusing a succeeded KSS Query. The existing
`formal_candidate_external_smoke_evidence_admission_failed` stage code intentionally
hides content, but it cannot distinguish an unavailable scorer from an empty Candidate
set, missing scores, scores below the configured threshold, or a policy denial.

[DECISION | HIGH] ProofAgent defines six content-free Evidence Admission reason codes:

- `evidence_admission_scorer_unavailable`;
- `evidence_admission_score_invalid`;
- `evidence_admission_candidate_set_empty`;
- `evidence_admission_score_missing`;
- `evidence_admission_threshold_not_met`;
- `evidence_admission_policy_denied`.

[DECISION | HIGH] The scorer port raises one typed Admission error with the existing
`PA_KNOWLEDGE_001` subsystem code and one allowlisted reason. The HTTP scorer adapter
maps authorization, transport and response-contract failure to `scorer_unavailable`;
the Control Plane maps a non-finite or out-of-range result to `score_invalid`. Exception
messages remain operational text and are never parsed to choose a reason.

[DECISION | HIGH] A completed governed Run may derive a reason only from the existing
trace-safe `evidence_evaluation.metadata.no_evidence_reason_code`. Evidence returned by
KSS but rejected against `min_score` is recorded as
`knowledge_candidate_threshold_not_met`; it is no longer mislabeled as
`zero_knowledge_candidates`. Unknown, missing or malformed facts remain unclassified.

[DECISION | HIGH] The external probe retains the Admission stage `error_code` and adds
an optional `reason_code` only after allowlist validation. Because this is a strict JSON
contract change, every failure envelope uses
`production-local-formal-candidate-external-smoke-failure.v2`. The success envelope
remains unchanged. Non-Admission stages cannot carry an Admission reason.

[CONSEQUENCE | HIGH] Operators can choose the next local check without seeing a
question, Candidate or Evidence content, score, threshold, identifier, answer, provider
response, credential, raw prompt, artifact bytes, path or stack trace. This slice adds
no retry, network call, persistence, HTTP or Dashboard surface, scorer fallback,
publication side effect or authority transition.

[BOUNDARY | HIGH] The reason identifies a bounded failure category, not root cause or
provider behavior. It cannot retroactively classify the TDD-05Y live result. A later
external probe still requires new exact authorization and remains separate from Phase F,
formal online-smoke qualification, publication approval, release Gates and Production
GO.
