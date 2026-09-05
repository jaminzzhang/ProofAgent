# Agent kernel diagnostic baseline

- baseline_version: agent-kernel-baseline.v1
- source_fingerprint: sha256:c2a261c277f2491c73525f8f24c772bbd5c8094e6c66573dcded2a9745806b5a
- execution_scope: synthetic_local
- production_readiness: not_evaluated
- status: needs_review

These fixed synthetic probes do not measure population answer accuracy.

- numeric_answer_validation: needs_review
  expected: correct_answer_accepted, wrong_amount_rejected=true; observed: correct_answer_accepted=true, wrong_amount_rejected=false
- compound_retrieval_completion: needs_review
  expected: both_sources_queried, both_facts_reach_answer=true; observed: both_sources_queried=false, both_facts_reach_answer=false
- intent_rewrite_reaches_kss: needs_review
  expected: required_rewrite_reaches_kss=true; observed: required_rewrite_reaches_kss=false
- structured_fact_reaches_answer: needs_review
  expected: structured_amount_reaches_answer=true; observed: structured_amount_reaches_answer=false
- long_conversation_constraints: needs_review
  expected: budget_retained, submission_prohibition_retained=true; observed: budget_retained=false, submission_prohibition_retained=false
