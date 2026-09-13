# ADR-0258: Bind task requirements to answer verification and recovery

Date: 2026-09-13. Status: adopted for plan v1 T1–T6, explicitly confirmed by user “同意”.
Plan: docs/features/agent-kernel-quality/task-answer-workflow-plan-2026-09-13.md.

Keep V3 and its policy, evidence admission, immutable observations and cumulative budgets.
User-bound clause IDs travel through planner and answer prompts. Unknown semantic criteria
remain unassessed. Domain profiles supply bounded judgments; the kernel owns verification
and recovery. The first analysis profile is insurance performance, with no company-specific
names, no cross-business rankings and no invented causes. This is not universal entailment.

Add the backwards-compatible Task verifier `grounded_analysis`. It requires a supported
objective profile and exact reproduction of a source-bound complete analysis, plus normal
fact, citation and assurance checks. Existing literal `answer_coverage` remains literal.
Existing records remain readable. New or revised supported analysis Tasks compile a
required control-owned `proofagent-answer-contract` criterion bound to the current
objective. Its ID is reserved, it is refreshed on revision, and unsupported arbitrary
constraints remain unassessed. At most 31 custom criteria fit alongside this check. No storage
migration is required for JSON verifier values; frontend types must accept the new value.

The source-selection model may return known `evidence_gap_requirement_ids` instead of
statement IDs. Mixed, unknown or duplicate fields/IDs are rejected. It cannot select an
endpoint, source authority or arbitrary query. The answer port carries a typed recovery
request; the orchestrator validates IDs, generates bounded queries from user clauses,
and dispatches through existing retrieval review, policy, immutable observation and budget.
Already attempted gaps do not recur indefinitely. No repair can convert a policy denial
or an unverified source into permission or an accepted fact.

The performance renderer groups selected bound facts and states improvement/pressure/mixed
at metric level, with scope and comparison limits. Every represented business's available
directions must be preserved. Derived prose is admissible only when the whole rendering
can be reproduced exactly from the evidence catalogue; labels alone grant no exemption.
Original numeric facts still pass the existing fact validator, including conflicting data.

Trace/read/UI: expose stable requirement IDs, profile ID, status/counts and recovery codes
only. No additional raw prompts, source text, model reasoning or credentials. The response
can disclose missing user clauses through its existing authorized user-facing channel.
Stage descriptors and Dashboard must show answer → planning for evidence gaps and the
bounded answer repair loop. Task completion and response delivery remain distinct.

Verification is local and synthetic until a separately authorized real-model replay.
