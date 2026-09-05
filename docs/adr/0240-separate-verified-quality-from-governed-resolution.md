# ADR-0240: Separate verified quality from governed resolution

## Status

[FRAME | HIGH] Accepted for the user-authorized P0-1B local implementation on
2026-09-05. This records the implementation decision; it is not release approval.

## Context

[KNOWN | HIGH] Analyzer V1 excludes diagnostic semantic Gates from case pass.
Absence of declared semantic claims produces a diagnostic PASSED result. Consequently,
Governed Resolution Rate is not proof of answer correctness or task completion.
The existing artifact reader, case results and writer already provide the appropriate
post-run seam; no additional Agent executor or external judge input is required.

## Decision

1. Add optional `EvaluationCase.quality_target`: `answer_correctness`,
   `refusal_appropriateness`, or `task_completion`. Task classification is explicit.
   Legacy cases infer answer/refusal only from consistent expected resolution/outcome
   pairs. Unclassified required cases remain visible. Explicit contradictory labels
   and unknown case or expected-assertion fields are rejected, including misspelled
   quality and semantic configuration.
2. Add versioned strict, immutable quality contracts for per-case status/reason and
   cohort metrics. A missing quality projection on historical results remains null.
   Only required standalone cases enter cohort denominators; scenario steps and
   optional cases retain diagnostic detail without duplicate weighting. Each new
   case result records `quality_cohort_included`; historical membership stays null.
3. Apply trust checks before quality judgments. Missing subjects, unreadable artifacts,
   absent or mismatched hashes, incomplete outcomes or conflicting Trace/Receipt
   facts produce `not_evaluated`. Per-case artifact read failures also fail the
   existing governance case so the rest of the analysis can proceed safely.
   Read each artifact once as bytes; parsing, Gate checks and observed hashes use
   that same snapshot. Quality requires a valid outcome in the last `final_output`
   itself, agreeing with Receipt and any declared metadata outcome. Legacy outcome
   fallback remains available for GRR compatibility but cannot establish quality.
4. On verified complete artifacts, an outcome mismatch or failed deterministic Gate
   proves `failed`. Answer semantics and task completion lack implemented positive
   verifiers and remain `not_evaluated`; keywords, citations, or tool success do not
   establish either.
5. A refusal may pass only as `curated_refusal_decision_matched`: expected resolution,
   expected outcome and actual refusal agree, all required governance Gates pass,
   and no declared business semantics remain unevaluated. This matches the curated
   decision label; it proves neither wording quality nor universal absence of an answer.
6. Report `verified_success_rate = passed / total` and
   `assessment_coverage_rate = (passed + failed) / total`; empty denominators yield
   null. Missing and unevaluated cases never disappear from total. These projections
   do not change GRR, Gate Profiles, Release Decision or `judge_mode=none`.
7. Persist quality on existing JSONL case rows and write a separate versioned quality
   summary JSON plus Markdown/Receipt projections. Include cohort membership and reason codes,
   not raw answers, prompts, tool payloads or secrets.

## Alternatives and consequences

- Reusing GRR or diagnostic PASSED would assert unmeasured quality; rejected.
- Accepting unbound judge scores would introduce another trust boundary before the
  semantic evaluator exists; deferred to a separately scoped verifier design.
- Treating all refusals as successful answers would inflate the answer cohort; rejected.
- Missing/invalid artifacts now produce a failed case with unevaluated quality rather
  than aborting the whole analysis. Existing successful and failed governed results
  must retain their meaning; both behavior paths require regression evidence.
- Strict case parsing can expose previously ignored fields. Supported suite fixtures
  must pass; unknown configuration must be repaired explicitly, not silently dropped.

## Verification and follow-up

The [P0-1B scope](../features/agent-kernel-quality/scope-p0-1b.md) and
[TDD report](../features/agent-kernel-quality/tdd-p0-1b.md) cover curated refusal positive/negative cases, answer and
task non-upgrade, integrity precedence, fixed denominators, strict contracts, historical
results, scenario weighting and artifact parity. Later task/semantic verifiers must
provide their own bound evidence and versioned rules before positive quality decisions
are enabled. No production state, dependency configuration or release authority changes.
