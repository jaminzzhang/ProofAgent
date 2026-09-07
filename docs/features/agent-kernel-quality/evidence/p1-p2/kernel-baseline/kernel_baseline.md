# Agent kernel diagnostic baseline

- baseline_version: agent-kernel-baseline.v1
- source_fingerprint: sha256:7a2c615a2083e85d4752b8a972369ecbb8caaf25fdfe11265267167e9497b757
- execution_scope: synthetic_local
- production_readiness: not_evaluated
- status: passed_with_diagnostics

These fixed synthetic probes do not measure population answer accuracy.

- numeric_answer_validation: passed_with_diagnostics
  expected: correct_answer_accepted, wrong_amount_rejected=true; observed: correct_answer_accepted=true, wrong_amount_rejected=true
- compound_retrieval_completion: passed_with_diagnostics
  expected: both_sources_queried, both_facts_reach_answer=true; observed: both_sources_queried=true, both_facts_reach_answer=true
- intent_rewrite_reaches_kss: passed_with_diagnostics
  expected: required_rewrite_reaches_kss=true; observed: required_rewrite_reaches_kss=true
- structured_fact_reaches_answer: passed_with_diagnostics
  expected: structured_amount_reaches_answer=true; observed: structured_amount_reaches_answer=true
- long_conversation_constraints: passed_with_diagnostics
  expected: budget_retained, submission_prohibition_retained=true; observed: budget_retained=true, submission_prohibition_retained=true
