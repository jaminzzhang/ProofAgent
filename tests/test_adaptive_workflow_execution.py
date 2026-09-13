from proof_agent.contracts import ReceiptOutcome
from proof_agent.contracts.workflow_policy import WorkflowExecutionPolicy
from tests.test_retrieval_task_completion import _harness, _start, QUERY_A, QUERY_B


def test_lite_retrieves_required_evidence_without_planner_calls():
    workflow, knowledge, answer, trace, planner = _harness(
        queries=((QUERY_A, True),), execution_policy=WorkflowExecutionPolicy(complexity='lite'))
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert knowledge.queries == [QUERY_A]
    assert planner.states == []
    assert result.execution_plan.effective_complexity == 'lite'


def test_lite_preserves_evidence_failure_gate():
    workflow, knowledge, answer, trace, planner = _harness(
        queries=((QUERY_A, True),), modes={QUERY_A: 'empty'},
        execution_policy=WorkflowExecutionPolicy(complexity='lite'))
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert knowledge.queries == [QUERY_A]
    assert not answer.contexts


def test_lite_escalation_executes_all_required_queries_and_exposes_effective_plan():
    workflow, knowledge, answer, trace, planner = _harness(
        execution_policy=WorkflowExecutionPolicy(complexity='lite'))
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.execution_plan.effective_complexity == 'standard'
    assert result.execution_plan.escalated


def test_ceiling_refuses_before_retrieval_instead_of_dropping_requirements():
    workflow, knowledge, answer, trace, planner = _harness(
        execution_policy=WorkflowExecutionPolicy(complexity='lite', ceiling='lite'))
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert knowledge.queries == []
    assert result.execution_plan.blocked_reason == 'complexity_ceiling_exceeded'
