---
status: accepted
---

# Verify Admission Scorer composition with a fixed synthetic Candidate

[KNOWN | HIGH] TDD-05Y stopped at the Evidence Admission boundary. TDD-05Z added
content-free reason categories for future runs, but repeating the exact Draft probe would
send Candidate Evidence to an external model and requires new exact authorization. A
generic Admission failure also does not independently prove whether the deployment-owned
Scorer identity, versioned credential, egress path and strict response contract are
working.

[DECISION | HIGH] The production-local deployment provides one explicit, zero-argument
Admission Scorer verifier. It constructs one checked-in synthetic question and one
synthetic relevance Candidate, binds the normal production `KnowledgeCandidateRuntime`,
and invokes only the bound `KnowledgeCandidateAdmissionScorer` port. Callers cannot
provide a Draft, Release, question, Candidate, model connection, credential or budget.

[DECISION | HIGH] The verifier uses the deployment-owned Scorer ID, revision, versioned
Secret Handle, Vault Secret Provider and guarded egress client. The scorer must return a
finite value from 0 through 1 for the exact synthetic Candidate set. Scorer identity,
Candidate-set or score-contract drift fails closed. The verifier does not call the
constructed KSS service or query factory.

[DECISION | HIGH] Success output contains only the Scorer identity/revision, hashes of
the fixed synthetic question and Candidate set, counts and explicit false authority
flags. It does not return the question, Candidate identifier or content, score, bearer
material, authorization header, endpoint or raw response. Every failure uses one stable,
content-free envelope and does not project exception text.

[CONSEQUENCE | HIGH] A successful run proves the current production-local compatibility
Scorer composition can resolve its managed credential, pass guarded egress and satisfy
the strict response contract. It does not prove the quality of real Candidate Evidence,
the configured threshold or policy decision, the Draft@14 failure reason, or an external
answer-model path.

[BOUNDARY | HIGH] The verifier uses a synthetic Release identity only to satisfy the
immutable runtime binding contract. It creates no KSS Query, Grant, Reference, validation
artifact, Formal Publication Command, Published Agent Version or Active pointer. It does
not call DeepSeek, enter Phase F, authorize publication, satisfy a release Gate or
establish Production GO.
