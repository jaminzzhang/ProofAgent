from types import SimpleNamespace
import pytest

from proof_agent.contracts import (EffectiveToolProposalScope, ToolProposalInterface, ToolProposalParameter,
    ToolProposalParameterSource, ReActActionType, ReceiptOutcome)
from proof_agent.contracts.workflow_policy import InteractionPolicy
from tests.test_retrieval_task_completion import _action, _harness, _start, QUERY_A
from tests.test_workflow_goal_execution import run, task


@pytest.mark.parametrize('stage', ['goal', 'plan', 'evidence', 'tool_input', 'finalization'])
def test_planner_optional_question_is_controlled_at_every_checkpoint(stage):
    workflow, knowledge, answer, trace, planner = _harness(queries=((QUERY_A, True),),
        interaction_policy=InteractionPolicy(mode='autonomous'))
    proposal = _action(action_type=ReActActionType.ASK_CLARIFICATION).model_copy(update={'parameters': {
        'missing_fields': ('format',), 'interaction_stage': stage,
        'clarification_assessments': ({'field': 'format', 'kind': 'preference', 'default_assumption': 'brief'},)}})
    planner.plan = lambda state: proposal
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert knowledge.queries == [QUERY_A]


def test_missing_user_tool_parameter_becomes_typed_hil_before_dispatch(tmp_path):
    class Scope:
        def resolve(self, state):
            return EffectiveToolProposalScope(run_id=state.run_id, plan_round=state.plan_round, schema_digest='sha256:test',
                tool_interfaces=(ToolProposalInterface(tool_contract_id='lookup', purpose='Lookup', risk_level='low',
                    read_only=True, requires_approval=False, parameters=(ToolProposalParameter(name='count', required=True,
                        value_type='integer', value_source=ToolProposalParameterSource.USER_SUPPLIED),)),))
    workflow, knowledge, answer, trace, planner = _harness(queries=(), interaction_policy=InteractionPolicy(),
                        tool_proposal_scope=Scope(), tool_observation=SimpleNamespace())
    planner.plan = lambda state: _action(action_type=ReActActionType.PROPOSE_TOOL_CALL).model_copy(
        update={'target_tool_name': 'lookup'})
    snapshot = task(tmp_path)
    # An unassessed tool goal gives the tool planner a turn without retrieval requirements.
    from proof_agent.contracts.workflow_task import AcceptanceCriterion
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={'acceptance_criteria': (
        AcceptanceCriterion(criterion_id='tool', description='Lookup result', verifier='verified_tool', tool_step_id='lookup'),)})})
    result = run(workflow, snapshot)
    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.workflow_task_update.question.stage == 'tool'
    assert result.workflow_task_update.question.fields[0].value_type == 'integer'
