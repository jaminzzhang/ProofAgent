# Controlled ReAct Optimization Implementation Sequence

Accepted.

The `run_c358ce0d` optimization work will land in four implementation slices rather than one broad rewrite.

1. Planner Eligible Action Contract: extend the planner interface so the Control Plane's current Eligible Action Set is passed as structured input, and make `LLMReActPlanner.allowed_actions` equal that set.
2. Observation Record Runtime Contract: add first-class Observation Records to runtime state, with truth references for answer generation and deterministic summaries for planning.
3. Convergence and Deduplication Gates: add Answer-Ready Convergence and Observation Action Deduplication so the loop stops repeating equivalent observations once accepted evidence is available and no unresolved subgoals remain.
4. Final Answer Citation Binding Gate and replay coverage: validate final answers against Observation Record `citation_refs` and `source_refs`, then add a replay-style regression sample based on `run_c358ce0d`.

We choose this order because the planner-input mismatch is the smallest high-leverage fix, Observation Records are the enabling state contract, convergence and deduplication depend on that contract, and final-answer citation binding should be added once the observation provenance path exists end to end.
