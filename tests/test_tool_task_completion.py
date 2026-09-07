from proof_agent.contracts.manifest import ReActConfig


def test_manifest_preserves_frozen_tool_task_requirements():
    config = ReActConfig.model_validate({
        'planner': {}, 'max_tool_calls': 2,
        'tool_task_plan': {'steps': [
            {'step_id': 'query', 'tool_name': 'query', 'parameters': {'query': 'demo'}},
            {'step_id': 'sum', 'tool_name': 'calculate',
             'bindings': {'values': {'step_id': 'query', 'path': ['amounts']}},
             'calculation': {'operation': 'sum', 'operand_parameter': 'values', 'result_field': 'total'}}
        ]}
    })
    assert config.model_dump()['tool_task_plan']['steps'][1]['step_id'] == 'sum'


def test_required_plan_prevents_premature_final_and_binds_query_result():
    from proof_agent.contracts import (ReActActionProposal, ReActActionType, ReasoningSummary,
        ReceiptOutcome, PolicyDecision, PolicyDecisionType, EnforcementPoint,
        ToolObservationTruth, ObservationRecord)
    from proof_agent.contracts.tool_tasks import ToolTaskPlan
    from proof_agent.control.workflow.controlled_react import (
        ControlledReActOrchestrator, ControlledReActPorts, ControlledReActStartRequest,
        ObservationEffect, AnswerSynthesisResult)
    calls = []
    class Planner:
        def plan(self, state):
            return ReActActionProposal(action_id='answer', action_type=ReActActionType.GENERATE_FINAL_ANSWER,
                risk_level='low', reasoning_summary=ReasoningSummary(goal='report', observations=(),
                candidate_actions=(ReActActionType.GENERATE_FINAL_ANSWER,), selected_action=ReActActionType.GENERATE_FINAL_ANSWER,
                rationale_summary='premature', risk_flags=(), required_evidence=()))
    class Policy:
        def evaluate(self, state, action):
            return PolicyDecision(decision=PolicyDecisionType.ALLOW, enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
                reason='test', policy_rule_id='test', trace_event_id='test')
    class Tool:
        def observe(self, state, action, identity):
            calls.append((action.target_tool_name, dict(action.parameters)))
            result = {'amounts': ['0.1', '0.2']} if action.target_tool_name == 'query' else {'total': '0.3'}
            truth = ToolObservationTruth(truth_ref=identity.truth_ref, observation_id=identity.observation_id,
                action_id=action.action_id, tool_name=action.target_tool_name, authorized_result=result,
                redaction_metadata={'executed': True})
            return ObservationEffect(truth_artifact=truth, observation_record=ObservationRecord(
                observation_id=identity.observation_id, action_id=action.action_id, action_type=action.action_type,
                round=state.plan_round, truth_ref=identity.truth_ref, source_refs=(f'tool://{action.target_tool_name}',)), trace_projection={})
    class Answer:
        def synthesize(self, state, action, context):
            return AnswerSynthesisResult(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS, final_output='done', message='done')
    plan = ToolTaskPlan.model_validate({'steps': [
        {'step_id': 'query', 'tool_name': 'query', 'parameters': {'query': 'demo'}},
        {'step_id': 'sum', 'tool_name': 'calculate', 'bindings': {'values': {'step_id': 'query', 'path': ['amounts']}},
         'calculation': {'operation': 'sum', 'operand_parameter': 'values', 'result_field': 'total'}}]})
    result = ControlledReActOrchestrator(ports=ControlledReActPorts(planner=Planner(), policy=Policy(),
        tool_observation=Tool(), answer_synthesis=Answer())).start(ControlledReActStartRequest(
            run_id='task_test', template_name='react_enterprise_qa_v3', template_descriptor_version='react_enterprise_qa.v3',
            question='compute report', tool_task_plan=plan, max_tool_calls=2))
    assert calls == [('query', {'query': 'demo'}), ('calculate', {'values': ('0.1', '0.2')})]
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
