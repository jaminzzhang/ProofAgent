# ADR-0261: Answer independent parts before personal clarification

Date: 2026-09-13

[FRAME | HIGH] A mixed question may have answerable public facts and a remaining
personal-information gap. Deliver the grounded partial answer first, then actively
ask a focused question in the same response, including autonomous mode.

Add answer_context to the Intent clarification classification. It denotes information
needed to finish a remaining subquestion, never identity, permission, unresolved
object identity, tool inputs or conflicting constraints. Control defers such fields
only when required retrieval queries exist and the intent does not propose tools.
Unclassified and required_context fields remain blocking. No broad keyword rule
reclassifies missing fields silently.

Control stores these fields as deferred_answer_fields, separate from missing_fields.
They travel through planning, answer generation, repair and grounding review.
The Planner cannot re-block on the same deferred fields, except for explicit Task
required context or tool input. The answer review requires a supported partial answer,
an explicit limitation and an active focused question; a gap list alone is insufficient.

For a Task, an admitted answer with deferred fields creates an answer-stage question
within the configured question/round limits and keeps waiting_for_input. Exhausted
rounds keep the task paused, never complete. Supplied typed fields are removed from
the deferred list on continuation. Ordinary Run answers may be ANSWERED_WITH_CITATIONS
while semantic coverage stays unassessed; they do not imply whole-task completion.

Policy, evidence, review, assurance, cumulative budgets and explicit frozen Task
requirements retain their gates. A model's classification remains fallible; independent
business evaluation is still needed. Historical run_d1a30e89 is not rewritten.

Verification: tests/test_partial_answer_clarification.py and
tests/test_partial_answer_orchestrator.py; quoted-answer review and Task regressions.
