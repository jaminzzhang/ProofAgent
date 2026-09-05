# Agent kernel diagnostic baseline

- baseline_version: agent-kernel-baseline.v1
- source_fingerprint: sha256:1f5ba02edbc244f91b42f296c81583afe257559e8cacc5490b0f6fc448dc496a
- execution_scope: synthetic_local
- production_readiness: not_evaluated
- status: needs_review

These fixed synthetic probes do not measure population answer accuracy.

- numeric_answer_validation: needs_review
  expected: correct_answer_accepted, wrong_amount_rejected=true; observed: correct_answer_accepted=true, wrong_amount_rejected=false
- compound_retrieval_completion: passed_with_diagnostics
  expected: both_sources_queried, both_facts_reach_answer=true; observed: both_sources_queried=true, both_facts_reach_answer=true
- intent_rewrite_reaches_kss: passed_with_diagnostics
  expected: required_rewrite_reaches_kss=true; observed: required_rewrite_reaches_kss=true
- structured_fact_reaches_answer: needs_review
  expected: structured_amount_reaches_answer=true; observed: structured_amount_reaches_answer=false
- long_conversation_constraints: needs_review
  expected: budget_retained, submission_prohibition_retained=true; observed: budget_retained=false, submission_prohibition_retained=false
