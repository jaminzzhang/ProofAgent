# Run 2b40a67b: answer fact validation repair

## Diagnosis — 2026-09-09

[KNOWN | HIGH] Original local validation Run `run_2b40a67b` completed both
required retrieval queries. First answer and one repair failed `answer_facts`,
returning `REFUSED_NO_EVIDENCE`. Its summary-only capture cannot prove the exact
wording of each original rejected statement. Evidence:
`runs/dify-verification/history/run_2b40a67b/trace.jsonl`, events 41 and 45.

[KNOWN | HIGH] User-authorized same-question replay `run_33bbbf14` reproduced
the failure with an opt-in redacted capture. Its source reading-guide bullet and
section leader caused an exact statement to fail after presentation was removed.
Later replay also exposed false conflicts between conditional payment branches.
Increasing prose prompt specificity alone did not make repair reliable.

## Change and RED/GREEN

- Normalize list presentation and narrow Chinese reading-guide section leaders;
  retain signs, values, units, negations and conditions.
- Scope explicit conditional assertions to their antecedents.
- Use bounded source-bound statement ID selection for text-only fact repair.
  Control Plane renders selected text/citations and reruns every existing gate.
  Keep typed/mixed evidence on the prior repair contract and retain one repair.
- Preserve raw model selections in the existing opt-in capture. Do not add raw
  prompts, statements or evidence to normal Trace. Unknown/duplicate IDs and
  arbitrary prose fail closed.

[KNOWN | HIGH] Before implementation, the presentation regression command gave
4 failures; conditional-branch tests gave 2 failures. The source-selection
integration test failed before its normalization/rendering implementation.
The final fact suite passes 90 tests, including wrong amounts, lost conditions,
negation/sign changes, conflicts, safety, policy budget denial, invalid IDs,
bounded options, typed exclusion, and adequacy of selected prose.

```text
.venv/bin/python -m pytest tests/test_answer_fact_validation.py -q
90 passed
```

[KNOWN | HIGH] Related answer, structured-evidence, model, orchestrator,
conversation and configuration-API suites passed 317 tests with 3 existing skips
on the final code, including all 90 fact-validation tests. Ruff and Mypy pass for the four affected
implementation modules. `git diff --check` passes. This is local verification,
not a production release gate result.

## Live evidence and limits

[KNOWN | HIGH] Same-question real-model replay `run_655d4447` returned
`ANSWERED_WITH_CITATIONS`. Its initial answer failed fact validation; the existing
one repair then selected source statements and passed all answer validators.
It produced an extractive coverage/rights overview, not a detailed reconstruction
of the benefit table. See its local Trace and Governance Receipt under
`runs/dify-verification/history/run_655d4447/`.

[KNOWN | HIGH] After loading the final code on the original local API port 8000,
`run_4cb2e2b5` also returned `ANSWERED_WITH_CITATIONS`. Its answer included the
coverage overview and the source's non-guaranteed-dividend limitation. The original
history/configuration directories and existing outbound policy were retained.

[KNOWN | HIGH] Replays `run_ffaadab4` and `run_f5aeb326` failed earlier with
unknown Business Flow Skill Pack IDs. That separate model-routing failure remains
unresolved; this change does not bypass route admission or claim general model
reliability. Extractive answers still require completeness/business-quality
evaluation beyond the bounded gates.

Design and boundaries: [ADR-0250](../../adr/0250-bind-text-fact-repair-to-source-statement-selection.md).
Runtime captures remain local and expire under their existing retention policy;
no captured source payloads or credentials are committed to this report.
