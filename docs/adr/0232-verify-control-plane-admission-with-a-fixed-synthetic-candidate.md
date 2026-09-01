---
status: accepted
---

# Verify Control Plane Admission with a fixed synthetic Candidate

[KNOWN | HIGH] ADR-0231 independently verifies the deployment-owned Admission Scorer,
but it stops at the scorer port. It does not prove that the production Control Plane
applies retrieval policy, projects the scored Candidate, or evaluates the fixed Evidence
Threshold through the current `KnowledgeRetrievalService`.

[FRAME | HIGH] The production-local deployment provides a second zero-argument verifier.
It binds the normal production `KnowledgeCandidateRuntime`, places one fixed in-memory
Candidate Result only at the KSS service boundary, and sends that result through the
public `KnowledgeRetrievalService.retrieve()` entry. The deterministic `PolicyEngine`,
deployment-owned Admission Scorer and Evidence Evaluation remain real production code.

[FRAME | HIGH] The verifier fixes the question, Candidate Result, retrieval strategy,
single-Candidate budget and `min_score`. Callers cannot provide a Draft, Release,
question, Candidate, policy, Model Connection, credential or threshold. The scorer must
return the exact Candidate set, the retrieval policy must allow the request, and Evidence
Evaluation must accept exactly one Candidate. Policy denial, scorer drift or a score
below the fixed threshold fails closed.

[FRAME | HIGH] Success output contains only the Scorer identity/revision, fixed-input
digests, Candidate and accepted counts, the bounded policy decision/rule, Evidence
Evaluation status and explicit false authority flags. It excludes the question,
Candidate identity/content, score, threshold, citation, credential, endpoint and raw
response. Failure uses one stable content-free envelope.

[CONSEQUENCE | HIGH] A successful run proves that the current production-local
compatibility Scorer can participate in the current Control Plane retrieval-policy and
Evidence Admission path for one fixed synthetic Candidate. It does not test a real KSS
Query, real Candidate quality, Draft@14, the answer model, citation generation or final
answer behavior.

[BOUNDARY | HIGH] The in-memory Candidate service creates no KSS resource. The verifier
does not call DeepSeek, persist validation artifacts, enter Phase F, invoke formal
publication, create a Published Agent Version, change the Active pointer, satisfy a
release Gate or establish Production GO.
