from datetime import date
from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.workflow_policy import AssurancePolicy
from proof_agent.control.workflow.assurance import evaluate_assurance


def evidence(**kwargs):
    return EvidenceChunk(source='source:a', content='Limit is 10.', citation='source:a#1',
                         status=EvidenceStatus.ACCEPTED, **kwargs)


def test_more_chunks_from_one_source_do_not_satisfy_two_sources():
    result = evaluate_assurance(AssurancePolicy(evidence={'min_sources': 2}),
                                evidence=(evidence(), evidence()), message='Limit is 10.')
    assert 'insufficient_independent_sources' in result.violations


def test_republished_identical_content_with_different_source_ids_counts_once():
    first = evidence(source_id='publisher:a')
    duplicate = first.model_copy(update={'source': 'mirror:b', 'source_id': 'publisher:b',
                                         'citation': 'mirror:b#2', 'content': ' LIMIT  is 10. '})
    result = evaluate_assurance(AssurancePolicy(evidence={'min_sources': 2}), evidence=(first, duplicate))
    assert result.source_count == 1
    assert not result.passed


def test_unknown_usage_or_model_confidence_is_not_assurance():
    result = evaluate_assurance(AssurancePolicy(level='strict'),
                                evidence=(evidence(metadata={'confidence': 1}),), message='Excellent policy')
    assert not result.passed
    assert 'required_claim_unassessed' in result.violations


def test_grounded_retains_fact_validation_and_strict_requires_assessed_claims():
    result = evaluate_assurance(AssurancePolicy(), evidence=(evidence(),), message='Limit is 20.')
    assert not result.passed
    good = evaluate_assurance(AssurancePolicy(level='strict'), evidence=(evidence(),), message='Limit is 10.')
    assert good.passed


def test_freshness_requires_source_date_not_retrieval_timestamp():
    policy = AssurancePolicy(evidence={'max_age_days': 30})
    missing = evaluate_assurance(policy, evidence=(evidence(metadata={'observed_at': '2026-09-12'}),),
                                 message='Limit is 10.', today=date(2026, 9, 12))
    assert 'source_date_unavailable' in missing.violations
    stale = evaluate_assurance(policy, evidence=(evidence(metadata={'effective_date': '2026-01-01'}),),
                               message='Limit is 10.', today=date(2026, 9, 12))
    assert 'source_expired_or_future' in stale.violations


def test_checkpoint_requirements_cannot_relax_global_assurance():
    policy = AssurancePolicy(evidence={'min_sources': 2}, checkpoints={'finalization': {'min_sources': 1}})
    assert not evaluate_assurance(policy, evidence=(evidence(),), message='Limit is 10.').passed


def test_explicit_unknown_applicability_is_blocking():
    result = evaluate_assurance(AssurancePolicy(level='basic'), evidence=(evidence(metadata={'applicability': 'unknown'}),),
                                message='Limit is 10.')
    assert 'applicability_unresolved' in result.violations


def test_insufficient_sources_block_before_answer_model_in_real_orchestrator():
    from tests.test_retrieval_task_completion import _harness, _start, QUERY_A
    workflow, knowledge, answer, trace, planner = _harness(queries=((QUERY_A, True),),
        assurance_policy=AssurancePolicy(evidence={'min_sources': 2}))
    result = _start(workflow)
    assert result.outcome.value == 'REFUSED_NO_EVIDENCE'
    assert not answer.contexts
