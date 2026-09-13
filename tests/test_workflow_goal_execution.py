from datetime import UTC, datetime, timedelta
from proof_agent.contracts import ContextAdmission, ReceiptOutcome
from proof_agent.contracts.workflow_task import GoalContract, TaskOwner
from proof_agent.contracts.workflow_policy import InteractionPolicy
from tests.test_retrieval_task_completion import _harness, QUERY_A
from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest


def task(tmp_path, **goal_fields):
    from proof_agent.contracts.workflow_task import WorkflowTaskSnapshot
    now = datetime.now(UTC)
    goal = GoalContract(task_id='task_test', revision=1, objective=QUERY_A, source_input_ref='input:test',
                        acceptance_criteria=({'criterion_id': 'answer', 'description': 'Source support',
                                              'verifier': 'source_support', 'query': QUERY_A},), **goal_fields)
    return WorkflowTaskSnapshot(goal=goal, owner=TaskOwner(actor_subject='actor', agent_id='agent', agent_version='v1'),
                    version=1, created_at=now, updated_at=now, raw_content_expires_at=now + timedelta(days=90))


def run(workflow, snapshot):
    return workflow.start(ControlledReActStartRequest(run_id='run_goal', template_name='react_enterprise_qa_v3',
                template_descriptor_version='1', question=QUERY_A,
                conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))


def test_missing_goal_context_blocks_before_any_model_or_retrieval(tmp_path):
    workflow, knowledge, answer, trace, planner = _harness(interaction_policy=InteractionPolicy())
    result = run(workflow, task(tmp_path, required_context=('product_id',)))
    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert not knowledge.queries and not planner.states
    assert result.workflow_task_update.question.fields[0].name == 'product_id'


def test_autonomous_missing_context_returns_bounded_result_without_question(tmp_path):
    workflow, knowledge, answer, trace, planner = _harness(interaction_policy=InteractionPolicy(mode='autonomous'))
    result = run(workflow, task(tmp_path, required_context=('product_id',)))
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_task_update.question is None
    assert result.workflow_task_update.phase == 'paused'
    assert not knowledge.queries


def test_goal_query_is_required_even_when_intent_omits_it(tmp_path):
    workflow, knowledge, answer, trace, planner = _harness(queries=())
    result = run(workflow, task(tmp_path))
    assert knowledge.queries == [QUERY_A]
    assert result.workflow_task_update.phase == 'complete'
    assert result.workflow_task_update.assessments[0].status == 'satisfied'


def test_unverifiable_semantic_goal_never_becomes_complete(tmp_path):
    snapshot = task(tmp_path)
    from proof_agent.contracts.workflow_task import AcceptanceCriterion
    criterion = AcceptanceCriterion(criterion_id='meaning', description='Explain all applicable rules', verifier='answer_coverage')
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={'acceptance_criteria': (criterion,)})})
    workflow, knowledge, answer, trace, planner = _harness(queries=((QUERY_A, True),))
    result = run(workflow, snapshot)
    assert result.workflow_task_update.phase == 'paused'
    assert result.workflow_task_update.assessments[0].status == 'unassessed'


def test_private_task_and_update_never_enter_general_result_or_context_dump(tmp_path):
    context = ContextAdmission(admitted=True, workflow_task=task(tmp_path))
    assert 'workflow_task' not in context.model_dump(mode='json')
    workflow, *_ = _harness(queries=((QUERY_A, True),))
    result = run(workflow, context.workflow_task)
    assert 'workflow_task_update' not in result.model_dump(mode='json')
