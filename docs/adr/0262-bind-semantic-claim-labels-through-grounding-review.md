# ADR-0262: Bind semantic claim labels through grounding review

Date: 2026-09-14

[KNOWN | HIGH] run_31c4ec49 produced complete JSON twice (4417 and 4974 output tokens).
Both failed the exact claim-in-message substring gate; repair also retained an unused
accepted citation. This prevented semantic review from running.

[FRAME | HIGH] Superseding ADR-0260's substring requirement, quotes.claim may be a faithful
summary identifying a conclusion in the answer. Exact matches still receive inline
numbers; every original quote also displays its associated claim label as literal text.
The separate grounding review must verify that the label identifies a real conclusion
in the answer and that the original evidence supports it. Wrong or detached labels fail
review; a quote-binding pass alone never authorizes delivery or Task completion.

Source text remains an original excerpt bound to an Accepted Evidence citation.
Unused accepted citations do not invalidate an otherwise sound answer; only used quote
records are rendered. Unknown citations remain rejected. No fuzzy source-text matching,
automatic claim rewriting or unconditional semantic pass is introduced.

[KNOWN | HIGH] Both captured attempts from run_31c4ec49 were replayed locally through
schema, safety, citation, adequacy and original quote validators and passed after this
change. The capture was read in place, without copying raw evidence into the repository.
This establishes removal of the observed deterministic failure, not semantic approval
of the captured answer. Its suggestions, age conditions and coverage still need model
review and independent business assessment. No external model replay was performed.

Regression: tests/test_quote_claim_labels.py covers valid paraphrased labels reaching
review, unrelated labels failing review, and unused accepted versus unknown citations.

Final local verification: 3089 backend tests passed, 102 skipped, 2 deselected;
Ruff and mypy (424 source files) passed. Backend restarted with preserved configuration;
Dashboard, Operator Chat and configuration API returned HTTP 200.
