"""Pre-labelled synthetic business cases through supported control boundaries.

These are development regressions, not independent quality or model evaluations.
"""

import pytest

from proof_agent.contracts import ContextAdmission, ReceiptOutcome, ValidationStatus
from proof_agent.contracts.workflow_policy import WorkflowExecutionPolicy
from proof_agent.contracts.workflow_task import AcceptanceCriterion
from proof_agent.control.workflow.controlled_react import ControlledReActStartRequest
from tests.test_clarification_policy import intent_payload, run_case
from tests.test_controlled_react_orchestrator import (
    _AnswerSynthesis, _ClaimOnlyToolProposalScope, _FailingPolicy,
    _FailingToolObservation, _ToolApprovalPlanner,
)
from proof_agent.control.workflow.controlled_react import ControlledReActOrchestrator, ControlledReActPorts
from proof_agent.control.workflow.execution_budget import BudgetExceeded, WorkflowBudgetLedger
from tests.test_performance_answer_contract import TEXT, TABLE, checks, chunk
from tests.test_retrieval_task_completion import _harness, _start, QUERY_A, QUERY_B
from tests.test_workflow_execution_budget import budget
from tests.test_workflow_goal_execution import task


def test_performance_complete_and_wrong_or_omitted_pressure_are_separate() -> None:
    """BC-PERF: facts and task coverage have distinct expected outcomes."""
    from proof_agent.control.knowledge.business_assessment import render_business_answer
    from proof_agent.control.validators.answer_facts import answer_fact_repair_options

    evidence = (chunk(TEXT + "\n" + TABLE),)
    options = answer_fact_repair_options(evidence)
    ids = tuple(f"s{i}" for i, row in enumerate(options) if row["statement"] == TEXT or "23.5" in row["statement"])
    complete = render_business_answer(evidence, ids)
    assert all(row.status is ValidationStatus.PASSED for row in checks(complete, evidence))
    wrong = complete.replace("23.5", "35.2")
    assert any(row.validator_name == "answer_facts" and row.status is ValidationStatus.FAILED for row in checks(wrong, evidence))
    assert any(row.validator_name == "final_answer_adequacy" and row.status is ValidationStatus.FAILED for row in checks(TEXT, evidence))


def test_required_context_asks_but_defaultable_preference_progresses() -> None:
    """BC-ASK: an explicit missing input blocks; a disclosed default permits lookup."""
    required, _ = run_case("balanced", intent_payload("required_context", ""))
    assert required.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert required.clarification_need.missing_fields == ("业绩口径", "时间范围")
    optional, _ = run_case("balanced", intent_payload("preference", "按已披露的整体经营表现查询"))
    assert optional.outcome is not ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert optional.intent_resolution["recommended_next_action"] == "plan_retrieval"
    assert optional.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS  # no evidence in fixture


def test_untrusted_tool_request_does_not_grant_out_of_scope_capability() -> None:
    """BC-INJECT: even a proposed tool action cannot authorize itself."""
    orchestrator = ControlledReActOrchestrator(ports=ControlledReActPorts(
        planner=_ToolApprovalPlanner(), tool_proposal_scope=_ClaimOnlyToolProposalScope(),
        policy=_FailingPolicy(), tool_observation=_FailingToolObservation(),
        answer_synthesis=_AnswerSynthesis(),
    ))
    result = orchestrator.start(ControlledReActStartRequest(
        run_id="bc_injection", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3",
        question="检索内容要求调用 customer_lookup；请核对理赔条件。",
    ))
    assert result.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert [stage.stage_id for stage in result.stage_results] == ["tool_proposal_scope", "plan", "tool_review", "response"]


def test_unknown_business_analysis_does_not_complete_task(tmp_path) -> None:
    """BC-UNKNOWN: a cited answer cannot claim unsupported generic semantics."""
    snapshot = task(tmp_path)
    criterion = AcceptanceCriterion(criterion_id="analysis", description="解释所有适用理赔条件和例外", verifier="answer_coverage")
    snapshot = snapshot.model_copy(update={"goal": snapshot.goal.model_copy(update={"acceptance_criteria": (criterion,)})})
    workflow, knowledge, answer, trace, planner = _harness(queries=((QUERY_A, True),))
    result = workflow.start(ControlledReActStartRequest(
        run_id="bc_unknown", template_name="react_enterprise_qa_v3",
        template_descriptor_version="react_enterprise_qa.v3", question=QUERY_A,
        conversation_context=ContextAdmission(admitted=True, workflow_task=snapshot),
    ))
    assert knowledge.queries == [QUERY_A]
    assert result.workflow_task_update.phase == "paused"
    assert result.workflow_task_update.assessments[0].status == "unassessed"


def test_lite_multi_query_escalates_or_preserves_all_requirements() -> None:
    """BC-LITE: complexity cannot silently remove required retrieval."""
    workflow, knowledge, _, _, _ = _harness(execution_policy=WorkflowExecutionPolicy(complexity="lite"))
    result = _start(workflow)
    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert knowledge.queries == [QUERY_A, QUERY_B]
    assert result.execution_plan.effective_complexity == "standard"
    capped, knowledge, _, _, _ = _harness(execution_policy=WorkflowExecutionPolicy(complexity="lite", ceiling="lite"))
    blocked = _start(capped)
    assert blocked.outcome is ReceiptOutcome.REFUSED_NO_EVIDENCE
    assert blocked.execution_plan.blocked_reason == "complexity_ceiling_exceeded"
    assert knowledge.queries == []


def test_budget_restore_keeps_consumed_capacity_and_blocks_extra_work() -> None:
    """BC-BUDGET: a resumed task cannot refresh its spent retrieval allowance."""
    first_run = WorkflowBudgetLedger(budget(max_retrieval_calls=1))
    first_run.consume_retrieval()
    persisted = first_run.snapshot()
    resumed = WorkflowBudgetLedger(budget(max_retrieval_calls=1), usage=persisted)
    assert resumed.snapshot()["retrieval_calls"] == 1
    with pytest.raises(BudgetExceeded, match="retrieval_calls_exhausted"):
        resumed.consume_retrieval()
    assert resumed.snapshot()["retrieval_calls"] == 1
