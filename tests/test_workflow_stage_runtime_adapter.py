from __future__ import annotations

from proof_agent.contracts import (
    ApprovalPause,
    PolicyDecisionType,
    ReceiptOutcome,
    WorkflowStageResult,
    WorkflowStageStatus,
)
from proof_agent.runtime.workflow_stage_adapter import WorkflowStageResultRuntimeAdapter


def test_adapter_maps_plan_continuation_to_state_delta() -> None:
    adapter = WorkflowStageResultRuntimeAdapter()
    result = WorkflowStageResult(
        stage_id="plan",
        status=WorkflowStageStatus.COMPLETED,
        summary={"action_type": "plan_retrieval"},
        continuation={
            "step_count": 1,
            "action": {"action_id": "act_1", "action_type": "plan_retrieval"},
            "reasoning_summary": {"selected_action": "plan_retrieval"},
        },
    )

    delta = adapter.to_state_delta(result)

    assert delta["step_count"] == 1
    assert delta["action"] == {"action_id": "act_1", "action_type": "plan_retrieval"}
    assert delta["reasoning_summary"] == {"selected_action": "plan_retrieval"}
    assert delta["stage_results"][0]["stage_id"] == "plan"
    assert delta["stage_results"][0]["summary"] == {"action_type": "plan_retrieval"}
    assert delta["stage_results"][0]["continuation"] == {}


def test_adapter_maps_clarification_waiting_result() -> None:
    adapter = WorkflowStageResultRuntimeAdapter()
    result = WorkflowStageResult(
        stage_id="clarification",
        status=WorkflowStageStatus.WAITING,
        outcome=ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
        summary={"missing_field_count": 1},
        continuation={
            "governance_refusal": ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION,
            "governance_message": "Please provide the policy id.",
            "final_output": "Please provide the policy id.",
            "clarification_need": {
                "missing_fields": ["policy_id"],
                "message": "Please provide the policy id.",
            },
        },
    )

    delta = adapter.to_state_delta(result)

    assert delta["governance_refusal"] is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert delta["final_output"] == "Please provide the policy id."
    assert delta["clarification_need"]["missing_fields"] == ["policy_id"]
    assert delta["stage_results"][0]["outcome"] == "WAITING_FOR_USER_CLARIFICATION"


def test_adapter_maps_retrieval_continuation_lists() -> None:
    adapter = WorkflowStageResultRuntimeAdapter()
    result = WorkflowStageResult(
        stage_id="retrieval",
        status=WorkflowStageStatus.COMPLETED,
        summary={"accepted_evidence_count": 1},
        continuation={
            "review_results": [{"final_decision": "allow"}],
            "evidence": [{"source": "kb://policy.md", "status": "accepted"}],
        },
    )

    delta = adapter.to_state_delta(result)

    assert delta["review_results"] == [{"final_decision": "allow"}]
    assert delta["evidence"] == [{"source": "kb://policy.md", "status": "accepted"}]
    assert delta["stage_results"][0]["summary"] == {"accepted_evidence_count": 1}


def test_adapter_maps_approval_pause_without_leaking_continuation() -> None:
    adapter = WorkflowStageResultRuntimeAdapter()
    pause = ApprovalPause(
        approval_id="appr_001",
        action_id="act_tool_1",
        tool_name="customer_lookup",
        policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
        checkpoint_ref="thread:run_001",
        summary={"risk_level": "medium"},
    )
    result = WorkflowStageResult(
        stage_id="tool",
        status=WorkflowStageStatus.WAITING,
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        summary={"approval_id": "appr_001", "tool_name": "customer_lookup"},
        continuation={"approval_pause": pause},
    )

    delta = adapter.to_state_delta(result)

    assert delta["approval_pause"] == pause
    assert delta["stage_results"][0]["summary"] == {
        "approval_id": "appr_001",
        "tool_name": "customer_lookup",
    }
    assert delta["stage_results"][0]["continuation"] == {}

