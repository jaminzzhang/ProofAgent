# ADR-0250: Bind text fact repair to source statement selection

## Status and trigger

[FRAME | HIGH] Adopted for the user-authorized local repair of `run_2b40a67b`
on 2026-09-09. This does not grant production publication or release approval.

[KNOWN | HIGH] The original run completed required retrieval and exhausted one
answer repair with `answer_facts_failed`. Local captured reproductions demonstrated
presentation-sensitive false negatives, conditional-branch false conflicts, and
continued model paraphrasing despite source-near repair instructions.

## Decision

Keep ADR-0244's public FinalAnswerOutput and deterministic admission gates. For a
text-only `answer_facts_failed` attempt with available source extracts, use the
existing single repair call to request `statement_ids` through the internal
`select_answer_statements` function schema. Other repairs and typed/mixed evidence
retain the existing FinalAnswerOutput repair contract.

Control Plane derives at most 128 options and 16,000 rendered statement characters
from Accepted Evidence, with exact source citation bindings. Model-selected IDs
must be unique, known, strings, and number between 1 and 16. Extra fields, free
prose and invalid IDs fail closed. Control Plane joins selected text with newlines
and derives citations; the model cannot supply replacement text or citation refs.
The rendered candidate must still pass schema, safety, citation binding, adequacy
and fact checks. Selection is not evidence admission or proof of answer completeness.

List markers and narrowly recognized Chinese reading-guide dotted section leaders
are presentation. Signed quantities, numeric values, polarity, units and conditions
remain significant. Explicit `若/如果/If ..., ...` antecedents remain part of the
fact subject, preventing false cross-branch conflicts and cross-branch value reuse.
Source extracts restore sentence-ending punctuation and omit obvious markup,
table rows, colon-ended headings and parenthesized numbered fragments.

The repair remains behind the same model-call policy/token budget, with the same
one-repair bound. Safety failures never initiate repair. A context-overflow error
on selection cannot silently replace its schema with free-prose generation.
Raw provider selection responses remain in the existing opt-in sensitive capture;
normal Trace retains bounded diagnostics, never new source/answer/prompt text.

## Limits

Broad paraphrase, table-to-prose inference and completeness remain outside this
bounded check. Extractive repair can provide less detail than a free-form answer.
Unsupported or inadequate selections are still refused. Model-proposed unknown
Business Flow Skill Pack IDs are a separate pre-answer failure, not repaired here.
No new storage, public API, configuration authority, retry loop or production
capability is added.

Implementation: `proof_agent/control/validators/answer_facts.py`,
`proof_agent/control/workflow/controlled_react/answer_source_selection.py`,
`proof_agent/control/workflow/controlled_react/final_answer_attempt.py`.
Regression coverage: `tests/test_answer_fact_validation.py`.
