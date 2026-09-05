# Evaluation Analysis Receipt

analyzer_version: evaluation-analyzer.v1
analysis_id: p0-1b-synthetic-fixed-artifacts
suite_id: p0-1b-synthetic
suite_version: 1
subject_manifest_id: fixed-artifacts
subject_manifest_version: 1
gate_profile_id: core_analyzer_gates.v1
judge_mode: none
release_decision: blocked
release_blocking_reasons: required_case_pass_rate below release threshold, artifact_sufficiency_rate below release threshold, deterministic_gate_pass_rate below release threshold
governed_resolution_rate: 0.667
scenario_governed_resolution_rate: 0.000
subject_coverage_rate: 0.833
artifact_sufficiency_rate: 0.857
failed_cases: refusal-wrong-outcome, refusal-missing-subject

## Verified Quality

- schema_version: evaluation-quality.v1
- cohort_scope: required_standalone_cases
- total_required_cases: 6
- unclassified_required_count: 1

GRR measures governed resolution. Quality uses separate targets and verifiers.
Verified success = passed / total; coverage = (passed + failed) / total.
Unevaluated cases remain in total. With unmeasured cases this is not an accuracy estimate.
An empty cohort is n/a. Refusal success only matches the curated refusal decision;
it does not verify wording or prove that no answer exists. Answer semantics and task
completion have no positive verifier in this version. Quality is not a release gate.

| target | total | passed | failed | not_evaluated | verified_success_rate | assessment_coverage_rate |
|---|---:|---:|---:|---:|---:|---:|
| answer_correctness | 1 | 0 | 0 | 1 | 0.000 | 0.000 |
| refusal_appropriateness | 3 | 1 | 1 | 1 | 0.333 | 0.667 |
| task_completion | 1 | 0 | 0 | 1 | 0.000 | 0.000 |

### Case Quality

- answer-unmeasured: answer_correctness; not_evaluated; answer_semantics_not_evaluated
- refusal-matched: refusal_appropriateness; passed; curated_refusal_decision_matched
- refusal-wrong-outcome: refusal_appropriateness; failed; governed_resolution_failed
- refusal-missing-subject: refusal_appropriateness; not_evaluated; missing_subject
- task-unmeasured: task_completion; not_evaluated; task_completion_not_evaluated
- unclassified-legacy: unclassified; not_evaluated; unclassified_expectation
- optional-refusal (outside cohort): refusal_appropriateness; passed; curated_refusal_decision_matched
