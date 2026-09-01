---
status: accepted
---

# Verify a fixed synthetic Candidate through a governed Run

[KNOWN | HIGH] ADR-0232 verifies deterministic Policy, the deployment-owned Admission
Scorer and Evidence Evaluation through the public Knowledge Retrieval Service. It stops
before the governed Agent Run entry, so it does not prove that the current execution
path carries accepted Evidence into a cited answer and governance receipt.

[FRAME | HIGH] The production-local deployment provides a zero-argument governed-Run
verifier. It loads a checked-in deterministic Agent fixture and calls the public
`execute_agent_package_run()` entry. The normal production runtime supplies the exact
query factory and Admission Scorer. Only the KSS service port returns one fixed
in-memory Candidate Result.

[FRAME | HIGH] The question, Candidate Result, Release identity, retrieval strategy,
budget, Scorer identity and deterministic planner/reviewer/answer providers are fixed.
Callers cannot supply a Draft, Release, question, Candidate, Model Connection,
credential, threshold or output path. Success requires `ANSWERED_WITH_CITATIONS`,
exactly one Accepted Evidence item and exactly one citation. A below-threshold score,
identity drift, fixture drift, missing ephemeral audit file or unexpected Run outcome
fails closed.

[FRAME | HIGH] The verifier overrides the fixture's unused static audit paths with a
temporary directory. It requires both trace and receipt to exist while the Run is
active, then lets the temporary directory remove them. Success output contains only
fixed-input digests, Scorer identity/revision, bounded counts, outcome and explicit
false authority flags. Failures expose only a stable envelope and an allowlisted stage;
exception text and Candidate content remain private.

[CONSEQUENCE | HIGH] A successful run proves that one fixed synthetic Candidate can
pass through the current production-local runtime binding, Control Plane Admission and
governed Run entry to a cited deterministic answer. It does not test a real KSS Query,
real Candidate quality, Draft@14, DeepSeek, durable ArtifactStore retention or an exact
formal Candidate.

[BOUNDARY | HIGH] The verifier creates no KSS resource, calls no external answer model,
writes no ArtifactStore object and grants no Phase F, formal publication, activation,
release Gate or Production GO authority. A full production Dockerfile rebuild remains
required deployment evidence when external base-image metadata is unavailable; a local
immutable overlay can verify the checked-in entry but cannot replace that full build.
