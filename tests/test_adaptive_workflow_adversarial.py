"""Independent adversarial checks for ADR-0255 runtime boundaries.

Each failed assertion represents lost mandatory clarification/acceptance, an
execution that succeeds beyond its budget, or private Task content in normal Trace.
These tests use bounded synthetic ports, never external models or production data.
"""
from dataclasses import replace
import json

import pytest

from proof_agent.contracts import ContextAdmission, ReceiptOutcome, ReActActionProposal, ReActActionType, ReasoningSummary
from proof_agent.contracts.workflow_policy import AssurancePolicy, InteractionPolicy, WorkflowBudget, WorkflowExecutionPolicy
from proof_agent.contracts.workflow_task import AcceptanceCriterion
from proof_agent.control.workflow.controlled_react import ControlledReActOrchestrator, ControlledReActPorts, ControlledReActStartRequest
from proof_agent.control.workflow.execution_budget import WorkflowBudgetLedger
from tests.test_retrieval_task_completion import _Answer, _Intent, _Knowledge, _Trace, _harness, QUERY_A
from tests.test_tool_task_execution import Tool, orchestrator as tool_orchestrator, request as tool_request
from tests.test_workflow_goal_execution import task, run


def test_private_task_trace_preserves_closed_control_reason_codes_only(tmp_path):
    from proof_agent.observability.audit.task_redaction import TaskTraceProjection
    project = TaskTraceProjection(task(tmp_path))
    assert project({'reason': 'active_time_exhausted'})['reason'] == 'active_time_exhausted'
    assert project({'stage': {'reason': 'lite_optional_memory'}})['stage']['reason'] == 'lite_optional_memory'
    assert project({'reason': 'Personalized to private member 12345678'})['reason'] == '[restricted_task_content]'


class ContextMissingIntent(_Intent):
    def resolve(self, state):
        result = super().resolve(state)
        return result.model_copy(update={'intent_resolution': result.intent_resolution.model_copy(update={
            'recommended_next_action': ReActActionType.ASK_CLARIFICATION,
            'missing_fields': ('product_id',),
        })})


class ClarifyingPlanner:
    def plan(self, state):
        return ReActActionProposal(action_id='clarify_product', action_type=ReActActionType.ASK_CLARIFICATION,
            risk_level='low', parameters={'missing_fields': ('product_id',)},
            reasoning_summary=ReasoningSummary(goal='Resolve missing product identity.', observations=(),
                candidate_actions=(ReActActionType.ASK_CLARIFICATION,), selected_action=ReActActionType.ASK_CLARIFICATION,
                rationale_summary='Product identity is required before this retrieval.', risk_flags=(), required_evidence=()))


@pytest.mark.parametrize('complexity', ['standard', 'lite'])
def test_required_intent_clarification_precedes_compiled_retrieval(complexity):
    knowledge = _Knowledge()
    workflow = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=ClarifyingPlanner(), knowledge_observation=knowledge, answer_synthesis=_Answer(),
        intent_resolution=ContextMissingIntent(queries=((QUERY_A, True),)),
        execution_policy=WorkflowExecutionPolicy(complexity=complexity), interaction_policy=InteractionPolicy(),
    ))
    result = workflow.start(ControlledReActStartRequest(run_id='required_context', template_name='react_enterprise_qa_v3',
        template_descriptor_version='react_enterprise_qa.v3', question='Which policy applies?'))
    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert knowledge.queries == []


def test_verified_tool_report_satisfies_corresponding_goal_criterion(tmp_path):
    snapshot = task(tmp_path)
    goal = snapshot.goal.model_copy(update={'acceptance_criteria': (AcceptanceCriterion(
        criterion_id='calculation', description='Verify the exact sum.', verifier='verified_tool', tool_step_id='sum'),)})
    snapshot = snapshot.model_copy(update={'goal': goal})
    tool = Tool()
    result = tool_orchestrator(tool).start(tool_request(conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert result.tool_task_report is not None
    assert len(tool.calls) == 2
    assert result.workflow_task_update.phase == 'complete'
    assert result.workflow_task_update.assessments[0].status == 'satisfied'


def test_final_answer_cannot_complete_after_the_active_budget_deadline(tmp_path):
    clock = [0.0]
    policy = WorkflowExecutionPolicy(budget=WorkflowBudget(max_active_seconds=1))
    ledger = WorkflowBudgetLedger(policy.budget, clock=lambda: clock[0])
    workflow, _, answer, _, _ = _harness(queries=((QUERY_A, True),), execution_policy=policy, budget_ledger=ledger)
    synthesize = answer.synthesize

    def slow_final(*args):
        result = synthesize(*args)
        clock[0] = 2.0
        return result

    answer.synthesize = slow_final
    result = run(workflow, task(tmp_path))
    assert result.workflow_task_update.usage_delta.active_seconds >= 2
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_task_update.phase != 'complete'


def test_task_objective_does_not_leak_to_the_ordinary_trace(tmp_path):
    marker = 'PRIVATE_TASK_OBJECTIVE_SYNTHETIC_73918'
    snapshot = task(tmp_path)
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={'objective': marker})})
    trace = _Trace()
    workflow, *_ = _harness(queries=((QUERY_A, True),), trace=trace)
    workflow.start(ControlledReActStartRequest(run_id='private_task', template_name='react_enterprise_qa_v3',
        template_descriptor_version='react_enterprise_qa.v3', question=marker,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot)))
    assert marker not in json.dumps(trace.events)


def test_tool_checkpoint_restores_the_effective_execution_plan(tmp_path):
    from tests.test_tool_task_execution import PrematurePlanner
    from proof_agent.control.workflow.controlled_react.local_stores import FileControlledReActSnapshotStore, FileObservationTruthStore
    policy = WorkflowExecutionPolicy(complexity='lite')
    snapshots = FileControlledReActSnapshotStore(tmp_path / 'snapshots')
    truths = FileObservationTruthStore(tmp_path / 'truths')
    first = tool_orchestrator(Tool(), planner=PrematurePlanner(fail_after=1), execution_policy=policy,
        snapshot_store=snapshots, observation_truth_store=truths)
    with pytest.raises(InterruptedError):
        first.start(tool_request())
    assert first.last_execution_plan.effective_complexity == 'standard'
    second = tool_orchestrator(Tool(), execution_policy=policy, snapshot_store=snapshots, observation_truth_store=truths)
    result = second.start(replace(tool_request(), task_checkpoint_ref=first.last_task_checkpoint_ref))
    assert result.execution_plan.effective_complexity == first.last_execution_plan.effective_complexity
    assert result.execution_plan.escalated


def test_tool_report_cannot_erase_explicit_independent_source_requirement():
    workflow = tool_orchestrator(Tool(), assurance_policy=AssurancePolicy(evidence={'min_sources': 2}))
    result = workflow.start(tool_request())
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.tool_task_report is None


def test_equivalent_serialized_assurance_keeps_tool_acceptance_behavior():
    policy = AssurancePolicy()
    restored = AssurancePolicy.model_validate(policy.model_dump(mode='json'))
    original_result = tool_orchestrator(Tool(), assurance_policy=policy).start(tool_request())
    restored_result = tool_orchestrator(Tool(), assurance_policy=restored).start(tool_request())
    assert original_result.execution_plan.configuration_digest == restored_result.execution_plan.configuration_digest
    assert original_result.outcome == restored_result.outcome


def test_task_derived_intent_risk_text_does_not_leak_to_ordinary_trace(tmp_path):
    member = '739187312'
    snapshot = task(tmp_path)
    snapshot = snapshot.model_copy(update={'goal': snapshot.goal.model_copy(update={
        'objective': f'Explain the benefits privately to member {member}.',
    })})

    class PrivateRiskIntent(_Intent):
        def resolve(self, state):
            result = super().resolve(state)
            return result.model_copy(update={'intent_resolution': result.intent_resolution.model_copy(update={
                'risk_flags': (f'Personalization includes member {member}',),
            })})

    trace = _Trace()
    workflow = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=ClarifyingPlanner(), knowledge_observation=_Knowledge(), answer_synthesis=_Answer(),
        intent_resolution=PrivateRiskIntent(queries=((QUERY_A, True),)), trace=trace,
        execution_policy=WorkflowExecutionPolicy(complexity='lite'),
    ))
    run(workflow, snapshot)
    assert member not in json.dumps(trace.events)


def test_memory_tail_cannot_complete_after_active_budget_deadline(tmp_path):
    clock = [0.0]
    policy = WorkflowExecutionPolicy(budget=WorkflowBudget(max_active_seconds=1))
    ledger = WorkflowBudgetLedger(policy.budget, clock=lambda: clock[0])

    class SlowMemory:
        def read(self, state):
            return {}

        def prepare_write(self, state, answer):
            clock[0] = 2.0
            return None

    workflow, *_ = _harness(queries=((QUERY_A, True),), execution_policy=policy,
        budget_ledger=ledger, memory=SlowMemory())
    result = run(workflow, task(tmp_path))
    assert result.workflow_task_update.usage_delta.active_seconds >= 2
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert result.workflow_task_update.phase != 'complete'
