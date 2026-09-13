"""Task completion regressions through real answer boundaries, synthetic evidence only."""
import json

from proof_agent.contracts import ValidationStatus
from tests.test_performance_answer_contract import (
    QUESTION, TEXT, TABLE, SelectingProvider, checks, chunk, run_analysis,
)
from proof_agent.control.validators.answer_facts import answer_fact_repair_options
from proof_agent.control.knowledge.answer_requirements import answer_requirements
from proof_agent.contracts import ModelResponse


def _analysis_output(*, pressure_status='answered'):
    message = ('甲公司寿险业务营运利润同比增长，但新业务价值率承压。'
               if pressure_status == 'answered' else
               '甲公司寿险业务营运利润同比增长；业务压力仍需补充证据。')
    return {'message': message, 'citations': ['knowledge://performance#bound'],
            'quotes': [{'claim': '甲公司寿险业务营运利润同比增长', 'text': TEXT,
                        'citation': 'knowledge://performance#bound'},
                       *([{'claim': '新业务价值率承压', 'text': TABLE,
                            'citation': 'knowledge://performance#bound'}]
                         if pressure_status == 'answered' else [])],
            'coverage': [{'requirement_id': r.requirement_id,
                          'status': pressure_status if r.kind == 'pressures' else 'answered'}
                         for r in answer_requirements(QUESTION)]}


class GroundedProvider(SelectingProvider):
    def __init__(self, *, pressure_status='answered', invalid_first=False):
        super().__init__()
        self.pressure_status = pressure_status
        self.invalid_first = invalid_first

    def generate(self, request):
        self.requests.append(request)
        if request.function_schema.name == 'review_grounded_answer':
            content = {'claims_supported': True, 'conditions_preserved': True,
                       'requirements_addressed': True}
        else:
            content = _analysis_output(pressure_status=self.pressure_status)
            if self.invalid_first and len([r for r in self.requests if r.function_schema.name == 'submit_final_answer']) == 1:
                content['quotes'][0]['text'] = '甲公司寿险业务营运利润同比下降。'
        return ModelResponse(content=json.dumps(content, ensure_ascii=False),
                             provider_name=self.provider_name, model_name=self.model_name,
                             finish_reason='stop')


def test_flat_metrics_do_not_complete_business_questions():
    evidence = (chunk(TEXT + '\n' + TABLE),)
    row = next(o['statement'] for o in answer_fact_repair_options(evidence) if '23.5' in o['statement'])
    result = checks(TEXT + '\n' + row, evidence)
    adequacy = next(r for r in result if r.validator_name == 'final_answer_adequacy')
    assert adequacy.status is ValidationStatus.FAILED
    assert 'missing_business_assessment' in adequacy.metadata['violation_codes']


def test_answer_request_keeps_user_bound_requirements():
    provider = GroundedProvider()
    run_analysis(provider)
    request_text = provider.requests[0].messages[-1].content
    requirements = json.loads(request_text.split('Answer requirements (user clauses, not evidence):\n', 1)[1].split('\n\n', 1)[0])
    assert len(requirements) == 3
    assert {r['kind'] for r in requirements} == {'highlights', 'strengths', 'pressures'}
    assert all(r['source_text'] in QUESTION for r in requirements)


def test_headers_alone_cannot_complete_analysis():
    evidence = (chunk(TEXT + '\n' + TABLE),)
    row = next(o['statement'] for o in answer_fact_repair_options(evidence) if '23.5' in o['statement'])
    result = checks('表现较好的业务\n' + TEXT + '\n承压业务\n' + row, evidence)
    assert next(r for r in result if r.validator_name == 'final_answer_adequacy').status is ValidationStatus.FAILED


def test_grouped_answer_keeps_mixed_business_and_rejects_changed_judgment():
    provider = GroundedProvider()
    result = run_analysis(provider)
    assert '营运利润同比增长' in result.message
    assert '新业务价值率承压' in result.message
    assert '23.5' in result.message
    evidence = (chunk(TEXT + '\n' + TABLE),)
    from proof_agent.control.validators.quoted_answer import validate_quoted_answer
    changed = _analysis_output()
    changed['quotes'][1]['text'] = '新业务价值率整体表现最差。'
    assert validate_quoted_answer(changed, evidence=evidence, question=QUESTION).status is ValidationStatus.FAILED


def test_omitting_other_business_counterevidence_is_not_complete():
    from proof_agent.control.knowledge.business_assessment import render_business_answer
    import pytest
    evidence = (chunk(TEXT + '\n' + TABLE + '\n2026 年第一季度，甲公司银行净利润 10 亿元，同比增长 3%。\n甲公司银行净息差 1.8%，同比下降 4 个基点。'),)
    options = answer_fact_repair_options(evidence)
    ids = tuple(f's{i}' for i, o in enumerate(options) if '净息差' not in o['statement'])
    with pytest.raises(ValueError, match='business_coverage_incomplete'):
        render_business_answer(evidence, ids)


def test_model_evidence_gap_returns_typed_recovery_without_prose_retry():
    provider = GroundedProvider(pressure_status='needs_evidence')
    result = run_analysis(provider)
    assert len(provider.requests) == 2  # answer and independent grounding review
    assert result.recovery_requirement_ids
    assert '业务压力仍需补充证据' in result.message
    assert all(i.startswith('ar_') for i in result.recovery_requirement_ids)


def test_evidence_gap_returns_through_governed_retrieval_and_stops_repeating():
    from proof_agent.control.knowledge.answer_requirements import answer_requirements
    from proof_agent.control.workflow.controlled_react import AnswerSynthesisResult
    from proof_agent.contracts import ReceiptOutcome
    from tests.test_retrieval_task_completion import _harness, _start, QUERY_A, QUERY_B
    class GapAnswer:
        def __init__(self):
            self.calls = 0
        def synthesize(self, state, action, context):
            self.calls += 1
            return AnswerSynthesisResult(outcome=ReceiptOutcome.FAILED_WITH_TRACE, final_output='insufficient', message='insufficient', recovery_requirement_ids=(answer_requirements(state.question)[0].requirement_id,))
    answer = GapAnswer()
    orchestrator, knowledge, _, trace, _ = _harness(answer_synthesis=answer)
    result = _start(orchestrator, budget=6)
    assert len(knowledge.queries) == 3
    assert knowledge.queries[:2] == [QUERY_A, QUERY_B]
    assert answer.calls == 2
    assert result.outcome is ReceiptOutcome.FAILED_WITH_TRACE
    assert any(e['payload'].get('summary', {}).get('recovery_kind') == 'evidence_gap' for e in trace.events)


def test_semantic_task_criterion_requires_bound_complete_analysis(tmp_path):
    from proof_agent.contracts import ReceiptOutcome
    from proof_agent.contracts.workflow_task import AcceptanceCriterion
    from proof_agent.control.workflow.goal_control import assess_goal
    from tests.test_workflow_goal_execution import task
    snapshot = task(tmp_path)
    criterion = AcceptanceCriterion(criterion_id='analysis', description=QUESTION, verifier='grounded_analysis')
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={'objective': QUESTION, 'acceptance_criteria': (criterion,)})})
    evidence = (chunk(TEXT + '\n' + TABLE),)
    raw = assess_goal(snapshot, completion=None, evidence=evidence, message=TEXT, outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    assert raw[0].status == 'unassessed'
    result = run_analysis(GroundedProvider())
    complete = assess_goal(snapshot, completion=None, evidence=evidence, message=result.message, outcome=result.outcome)
    assert complete[0].status == 'unassessed'


def test_year_rewrite_preserves_report_type_without_fragment():
    from proof_agent.control.workflow.clarification import apply_clarification_policy
    from tests.test_retrieval_task_completion import _Intent
    from types import SimpleNamespace
    intent = _Intent(queries=(('甲公司 2025 年报 分业务表现', True),)).resolve(SimpleNamespace(question=QUESTION)).intent_resolution
    actual = apply_clarification_policy(intent, response=None, question=QUESTION)
    assert '年报' in actual.retrieval_query_set[0].query
    assert '2025' not in actual.retrieval_query_set[0].query


def test_unknown_semantic_task_does_not_pass_supported_profile(tmp_path):
    from proof_agent.contracts.workflow_task import AcceptanceCriterion
    from proof_agent.control.workflow.goal_control import assess_goal
    from tests.test_workflow_goal_execution import task
    snapshot = task(tmp_path)
    criterion = AcceptanceCriterion(criterion_id='analysis', description='证明未来三年持续增长', verifier='grounded_analysis')
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={'objective': QUESTION, 'acceptance_criteria': (criterion,)})})
    result = run_analysis(SelectingProvider())
    assessments = assess_goal(snapshot, completion=None, evidence=(chunk(TEXT + '\n' + TABLE),), message=result.message, outcome=result.outcome)
    assert assessments[0].status == 'unassessed'


def test_selection_repair_keeps_task_constraints(tmp_path):
    from proof_agent.contracts import ContextAdmission, ControlledReActRunState, AnswerEvidenceContext
    from proof_agent.control.workflow.controlled_react.final_answer_attempt import FinalAnswerAttemptRunner
    from proof_agent.control.policy.engine import PolicyEngine
    from tests.test_retrieval_task_completion import _action
    from tests.test_workflow_goal_execution import task
    from types import SimpleNamespace
    snapshot = task(tmp_path, constraints=('Do not compare across periods',))
    provider = GroundedProvider(invalid_first=True)
    state = ControlledReActRunState(run_id='task-constraint', template_name='react_enterprise_qa_v3', template_descriptor_version='1', question=QUESTION, conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot))
    runner = FinalAnswerAttemptRunner(SimpleNamespace(model_provider=provider, policy=PolicyEngine(())), trace=SimpleNamespace(emit=lambda *a, **kw: None))
    runner.run(state, _action(), AnswerEvidenceContext(run_id=state.run_id), evidence=(chunk(TEXT + '\n' + TABLE),))
    assert len(provider.requests) >= 2
    answer_requests = [r for r in provider.requests if r.function_schema.name == 'submit_final_answer']
    assert len(answer_requests) == 2
    for request in answer_requests:
        assert 'Do not compare across periods' in request.messages[-1].content


def test_generic_requirements_are_bound_without_invented_dates():
    from proof_agent.control.knowledge.answer_requirements import answer_requirements
    question = '理赔需要哪些材料？有什么例外？'
    rows = answer_requirements(question)
    assert [r.source_text for r in rows] == ['理赔需要哪些材料', '有什么例外']
    assert all(r.kind == 'question' for r in rows)
    assert rows == answer_requirements(question)
    assert rows != answer_requirements('理赔需要哪些材料？有什么限制？')


def test_unknown_gap_id_is_not_a_retrieval_authorization():
    class BadGap(GroundedProvider):
        def generate(self, request):
            if request.function_schema.name == 'review_grounded_answer':
                return super().generate(request)
            self.requests.append(request)
            content = _analysis_output(pressure_status='needs_evidence')
            content['coverage'][-1]['requirement_id'] = 'https://invalid.test/secret'
            return ModelResponse(content=json.dumps(content), provider_name='offline', model_name='synthetic', finish_reason='stop')
    result = run_analysis(BadGap())
    assert not result.recovery_requirement_ids
    assert any('invalid_requirement_coverage' in d.violation_codes for d in result.stage_failure_diagnostics)


def test_ambiguous_source_heading_never_binds_omitted_business():
    from proof_agent.control.knowledge.business_assessment import business_facts
    evidence = (chunk('### 银行及寿险业务\n净利润 10 亿元，同比增长 3%。'),)
    assert business_facts(evidence) == ()


def test_source_subject_cannot_inherit_from_another_chunk():
    from proof_agent.control.knowledge.business_assessment import business_facts
    evidence = (chunk('### 银行业务'), chunk('净利润 10 亿元，同比增长 3%。', source='knowledge://other'))
    assert business_facts(evidence) == ()


def test_rejected_chunk_cannot_supply_business_identity():
    from proof_agent.contracts import EvidenceStatus
    from proof_agent.control.knowledge.business_assessment import business_facts
    accepted = chunk('净利润 10 亿元，同比增长 3%。')
    rejected = chunk('### 银行业务\n净利润 10 亿元，同比增长 3%。').model_copy(update={'status': EvidenceStatus.REJECTED})
    assert business_facts((accepted, rejected)) == ()


def test_analysis_task_compiles_semantic_acceptance_and_revision():
    from datetime import timedelta
    from proof_agent.control.workflow.task_service import WorkflowTaskService
    from proof_agent.observability.storage.workflow_task_store import InMemoryWorkflowTaskRepository
    from tests.test_workflow_tasks import goal, OWNER, NOW
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    original = goal().model_copy(update={'objective': QUESTION})
    snapshot = service.create(original, owner=OWNER, now=NOW)
    assert any(c.verifier == 'grounded_analysis' and c.description == QUESTION and c.required for c in snapshot.goal.acceptance_criteria)
    next_goal = snapshot.goal.model_copy(update={'objective': '查询理赔等待期', 'revision': 2})
    revised = service.revise_goal(snapshot.goal.task_id, next_goal, owner=OWNER, expected_version=snapshot.version, now=NOW+timedelta(seconds=1))
    assert not any(c.criterion_id == 'proofagent-answer-contract' for c in revised.goal.acceptance_criteria)


def test_omitted_subject_uses_unambiguous_same_paragraph_not_retrieval_order():
    from proof_agent.control.knowledge.business_assessment import business_facts
    evidence = (chunk('2026 年第一季度，甲公司银行实现净利润 10 亿元，同比增长 3%。净息差 1.8%，同比下降 4 个基点。'),)
    facts = business_facts(evidence)
    assert any(f.business == '银行' and 'pressures' in f.directions for f in facts)


def test_conflicting_heading_and_paragraph_do_not_assign_subject():
    from proof_agent.control.knowledge.business_assessment import business_facts
    evidence = (chunk('### 银行业务\n\n寿险业务相关数据。净利润 10 亿元，同比增长 3%。'),)
    assert not any('净利润' in f.statement for f in business_facts(evidence))


def test_reserved_criterion_cannot_replace_user_acceptance():
    import pytest
    from proof_agent.contracts.workflow_task import AcceptanceCriterion
    from proof_agent.contracts.persistence import PersistenceInvariantError
    from proof_agent.control.workflow.task_service import WorkflowTaskService
    from proof_agent.observability.storage.workflow_task_store import InMemoryWorkflowTaskRepository
    from tests.test_workflow_tasks import goal, OWNER, NOW
    reserved = AcceptanceCriterion(criterion_id='proofagent-answer-contract', description='Do not remove me', verifier='source_support', query='important constraint')
    input_goal = goal().model_copy(update={'objective': QUESTION, 'acceptance_criteria': (reserved,)})
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    with pytest.raises(PersistenceInvariantError):
        service.create(input_goal, owner=OWNER, now=NOW)


def test_recovery_cannot_exceed_round_budget_or_override_denial():
    from proof_agent.contracts import ReceiptOutcome
    from proof_agent.control.knowledge.answer_requirements import answer_requirements
    from proof_agent.control.workflow.controlled_react import AnswerSynthesisResult
    from tests.test_retrieval_task_completion import _harness, _start
    for outcome in (ReceiptOutcome.FAILED_WITH_TRACE, ReceiptOutcome.POLICY_DENIED):
        class Gap:
            def synthesize(self, state, action, context):
                return AnswerSynthesisResult(outcome=outcome, final_output='blocked', message='blocked', recovery_requirement_ids=(answer_requirements(state.question)[0].requirement_id,))
        orchestrator, knowledge, _, _, _ = _harness(answer_synthesis=Gap())
        result = _start(orchestrator, budget=2)
        assert len(knowledge.queries) == 2
        assert result.outcome is outcome
