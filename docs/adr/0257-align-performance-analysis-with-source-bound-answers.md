# ADR-0257: Align two-sided performance analysis with source-bound answers

Date: 2026-09-12. Status: adopted for the user-authorized local correction of
`run_1fbcbc32`. Extends ADR-0241/0244/0250. No production or external replay approval.

## Trigger and scope

[KNOWN | HIGH] The captured run retrieved useful text and tables, then failed
text-fact consistency and exhausted one repair with 30 selected statements where
the contract permits 1–16. Original-sentence selection excluded material table
declines. Required-query completion prevented further retrieval. See
`docs/research/run-1fbcbc32-diagnosis-2026-09-12.md` for the historical diagnosis.

The new bounded profile applies to explicit Chinese company-performance questions
requesting both strengths and weaknesses. It is not a universal entailment judge,
an investment-ranking engine, or a claim that missing business domains are covered.
Other questions retain the existing answer workflow. Public FinalAnswerOutput and
provider/permission boundaries remain unchanged.

## Decision

- For this profile and text-only evidence with selectable statements, use the
  existing source-ID contract on the first answer call. The existing one-repair
  bound remains. Repairs retain the selection contract regardless of whether the
  failed selection violated schema, adequacy or facts. Context overflow cannot
  downgrade selection to free prose.
- Compact selection input carries the question, bounded validation codes,
  requirements and ID/text candidates. It omits duplicate evidence, prior prose
  and repeated long citation URIs. The server recomputes the candidate-to-citation
  mapping from accepted evidence and never accepts replacement text or citations.
  IDs are scoped to this request/evidence/projection version; historical IDs must
  not be reused against a newer candidate catalogue.
- Add a deterministic Markdown-table projection. A complete header, heading and
  matching cell count are required; headings, period labels, units, row names,
  column names, values and resolvable footnotes travel together. No arithmetic,
  unit conversion, invented missing cells or inferred headers. Unknown HTML,
  ambiguous headers, missing footnotes and unsupported tables have no projection.
  Projected statements are a derived view of the original cited bytes, not new
  accepted evidence or a `structured_json` provider record. The same projection
  feeds selection and validation, so a model cannot grant its own table facts.
- Normalize only CJK presentation spaces next to CJK/number boundaries. Never join
  digits, remove signs/units or normalize arbitrary Latin labels. Continue checking
  exact subjects, periods, comparators, conditions, negations and conflicting values.
- Render one exact conservative scope disclosure, asserting neither latestness nor
  full coverage. Only that fixed string is non-factual control presentation; there
  is no free-form disclaimer exemption. Dynamic prose still undergoes normal gates.
- For a broad performance question with no explicit/relative year, strip invented
  years from proposed query qualifiers and replace year-bearing scope defaults with
  an unresolved actual-report search scope. Required identity/context constraints
  remain blocking. The known current date is not a substitute for report evidence.
- Keep required-query completion and answer coverage distinct. The bounded profile
  requires an actual reporting period, supported growth/strength indicators and
  supported pressure indicators. Common explicit financial metric directions are
  coverage signals, not overall business rankings or causal claims. Matching two
  topic words is insufficient. Insufficient coverage permits finite optional/gap
  retrieval through the same policy, immutable observation binding and budgets;
  exhausted retrieval cannot manufacture an answer.
- Deduplicate answer context only when validated evidence identity and meaningful
  metadata match; ignore retrieval scores/ranks and observation time only. Preserve
  applicability, conflict and authority differences and every query's immutable
  Observation Truth. Count newly observed citations separately.
  Planner summaries show unique evidence and bounded coverage categories.
- Preserve both failed answer-attempt diagnostics in the existing diagnostic list
  (latest first for compatibility), rather than discarding the original failure.

## Audit, safety and limits

New observation/Trace projections contain only the bounded category names `period`,
`strengths`, `pressures` and counts. No source values, text, prompts, credentials,
model reasoning or arbitrary metadata are newly admitted into ordinary Trace.
Failure diagnostics retain existing sanitized fields and bounded lists. Selection
count violations also expose integer `selection_count` and `selection_limit` to
operators and the existing final-message surface; no selected IDs or source text
are included. Over-limit output is rejected, never silently truncated. Sensitive
validation captures retain their existing opt-in/retention policy.

Native relevance and content hashes do not establish publisher authenticity or
latestness. Agentset source metadata remains limited; the answer explicitly says
latestness/full coverage are unverified rather than inventing them. Complex merged
tables, unresolved footnotes and unsupported metric semantics may require more
retrieval or a bounded no-answer outcome. LLM-selected prose can still be inadequate;
passing local deterministic checks is not proof of global semantic correctness.

Verification and remaining limits:
`docs/features/agent-kernel-quality/tdd-run-1fbcbc32.md`.
