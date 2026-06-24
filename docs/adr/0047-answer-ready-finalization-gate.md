# Answer-Ready Finalization Gate

Accepted.

The Controlled ReAct Loop will treat answer-ready state as a final-answer obligation rather than a peer choice between `GENERATE_FINAL_ANSWER` and `REFUSE`. When Accepted Evidence exists and the latest Observation Record has no unresolved subgoals, the Control Plane should proceed to `GENERATE_FINAL_ANSWER` unless a specific blocker is present.

When no explicit blocker exists, the answer-ready Eligible Action Set is `GENERATE_FINAL_ANSWER` only. If a planner or provider still emits `REFUSE`, Action Constraint rewrites it to `GENERATE_FINAL_ANSWER` and emits an `action_constrained` trace event. This keeps Layer 2 as the provider-neutral backstop and avoids relying on function-calling or prompt compliance.

When `answer_ready_blockers` is empty, the `plan` stage emits a synthetic `GENERATE_FINAL_ANSWER` action without invoking the planner model. This preserves the loop topology because the terminal action still originates in `plan`, while avoiding one unnecessary model call and removing the opportunity for historical refusal context to override current Accepted Evidence.

Valid blockers include no Accepted Evidence, explicit unresolved subgoals, a policy denial, evidence relevance failure, citation-binding impossibility, or another traced control fact that makes a governed answer impossible. A planner-selected `REFUSE` in answer-ready state is not sufficient by itself.

Blockers are first-class Control Plane state, not ad hoc inferences from scattered fields. The runtime state should carry `answer_ready_blockers`, a list of objects with stable `code`, bounded `reason`, and optional `source_ref`. Core codes are `no_accepted_evidence`, `unresolved_subgoal`, `policy_denied`, `evidence_relevance_failed`, `citation_binding_impossible`, and `variant_conflict`. An empty blocker list means the Answer-Ready Finalization Gate admits only `GENERATE_FINAL_ANSWER`.

Product variant ambiguity is not a blocker by itself. If Accepted Evidence clearly identifies one product variant, the final answer must state that cited variant scope. Variant ambiguity becomes a blocker only when Accepted Evidence contains conflicting variants or cannot establish the variant scope of the answer.

After answer-ready fires, planner model-bearing context must prioritize the current Observation Record state. Free-text recent-conversation summaries that say prior attempts refused or failed must not be supplied as terminal-decision context. If prior attempts matter for audit, they may be projected only as bounded non-blocking metadata, such as `prior_failed_attempts_count`, with no authority to justify current refusal.

When the gate admits `GENERATE_FINAL_ANSWER`, the final-answer model must receive the full Accepted Evidence truth layer and the Observation Record citation/source references needed for binding. Planner summaries are sufficient for terminal action selection, but they are not sufficient for answer synthesis. Starving `model_answer` of evidence would simply move the refusal failure from the planner stage to the final-answer stage.

We choose this over the ADR-0037 terminal two-choice behavior because real planner runs can over-weight conservative context, historical refusal summaries, or missing evidence snippets in the planner prompt even after retrieval produced Accepted Evidence. The final-answer model and citation-binding gate are the correct places to synthesize and validate evidence-backed output; the planner should not discard accepted evidence through an ungrounded refusal.

This keeps ADR-0037's useful convergence behavior, but tightens its terminal semantics: answer-ready still stops further observation by default, yet refusal now requires an explicit blocker instead of model caution.
