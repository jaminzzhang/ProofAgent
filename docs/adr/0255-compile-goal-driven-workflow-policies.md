# ADR-0255: Compile goal-driven workflow policies

Date: 2026-09-12. Accepted by the user's instruction to implement the proposed
adaptive workflow design in `docs/features/agent-kernel-quality/workflow-optimization-2026-09-12.md`.

[FRAME | HIGH] Keep the sole V3 Control Plane and separate four contracts: versioned
Goal/Task acceptance, InteractionPolicy, AssurancePolicy and WorkflowExecutionPolicy.
An optional `workflow.execution` compiles a deterministic effective execution plan;
absent new policy fields retain legacy behavior. `interaction` supersedes the legacy
clarification preference only when explicitly configured; conflicting declarations
are rejected. Unknown new fields, numeric uncalibrated confidence thresholds, and
attempts to disable mandatory policy/evidence/validation checks are invalid.

[FRAME | HIGH] The full stage topology remains visible. Lite may replace determined
Planner calls, omit optional retrieval expansion and nonessential memory, and retain
the existing deterministic low-risk review path. Required queries, goal criteria,
tool authority and answer validation cannot be skipped. Effective plan, source
configuration and policy digest are frozen for execution and recovery. Complexity
escalation is confined to the configured ceiling and total budget.

[FRAME | HIGH] Questions are structured information requests, never execution
approval. Required context stays blocking at every stage and in autonomous mode.
Question answers bind actor, task, goal revision, field schema and idempotency key.
Task waiting releases execution resources; a durable resumption intent cannot be
lost between accepting an answer and publishing work. Goal revision and storage CAS
version are distinct. PostgreSQL owns production Task state; local files are development
adapters only. Queue publication uses durable outbox and stable idempotency, or a
shared PostgreSQL transaction. Resume revalidates the current permission context,
frozen Agent Version/configuration, checkpoint integrity, and remaining budget.

[FRAME | HIGH] Complete is an acceptance decision, not a model self-report. Unknown
semantic criteria remain unassessed. Assurance requirements operate on admitted
evidence, source applicability, bound claims and deterministic validators; model
confidence is advisory and no probability of correctness is exposed. Strict profiles
block required unassessed claims. Information supplied by a user is not automatically
Accepted Evidence. Existing result and failure meanings stay intact; task status is a
separate projection.

[FRAME | HIGH] Model effort is provider-aware and opt-in. Unsupported combinations
fail before network requests; default configuration preserves legacy payloads. A shared
per-execution budget accounts for intent/planning/review/retrieval/answer/repair calls,
reserves output tokens before calling, and never interprets missing usage as zero.

[FRAME | HIGH] Raw Task and Question content has the restricted conversation audience
and 90-day retention. Ordinary Trace contains identifiers, counts, safe reason codes,
digests, stage decisions and verification status only. No raw reasoning or prompts,
new external execution authority, automatic production approval or release are added.
Local correctness and rendered UI verification are distinct from external-model quality
and all existing production release Gates.
