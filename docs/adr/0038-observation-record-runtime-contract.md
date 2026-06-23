# Observation Record Runtime Contract

Accepted.

The Controlled ReAct Loop will make Observation Records a first-class runtime state contract rather than reconstructing observations from `evidence`, `evidence_trajectory`, `action_history`, and `review_results`. Each Observation Record carries both a truth reference for answer generation and a deterministic planning summary for the next Plan Round.

The minimum runtime fields are `observation_id`, `action_id`, `action_type`, `round`, `truth_ref`, `summary`, `accepted_evidence_count`, `new_evidence_count`, `unresolved_subgoals`, `source_refs`, and `citation_refs`. `plan` reads summaries and unresolved subgoals; `model_answer` resolves truth references and citation references. This makes the Answer-Ready Convergence Signal auditable instead of dependent on prompt interpretation.

We choose this over reconstructing observation facts from scattered state because the scattered form cannot reliably distinguish "enough evidence, answer now" from "some evidence exists, but a compound request still has unresolved subgoals." The extra state object is justified by the loop-control role it serves.
