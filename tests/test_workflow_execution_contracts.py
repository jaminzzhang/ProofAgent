from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    ApprovalPause,
    ClarificationNeed,
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    EvidenceChunk,
    EvidenceStatus,
    PolicyDecisionType,
    ReceiptOutcome,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStageFailureDiagnostic,
    WorkflowStageResult,
    WorkflowStageStatus,
    WorkflowTemplateExecutionInput,
    WorkflowTemplateExecutionResult,
)


def test_workflow_stage_result_freezes_summary_and_continuation() -> None:
    result = WorkflowStageResult(
        stage_id="plan",
        status=WorkflowStageStatus.COMPLETED,
        summary={"action_type": "plan_retrieval"},
        continuation={"action": {"action_id": "act_1"}},
    )

    with pytest.raises(TypeError):
        result.summary["extra"] = "blocked"
    with pytest.raises(TypeError):
        result.continuation["extra"] = "blocked"


@pytest.mark.parametrize(
    "forbidden_key",
    (
        "raw_prompt",
        "raw_context",
        "raw_tool_payload",
        "provider_response",
        "langgraph_state",
        "chain_of_thought",
        "secret",
    ),
)
def test_workflow_stage_result_rejects_raw_summary_keys(
    forbidden_key: str,
) -> None:
    with pytest.raises(ValidationError):
        WorkflowStageResult(
            stage_id="model_answer",
            status=WorkflowStageStatus.COMPLETED,
            summary={forbidden_key: "must not enter ordinary stage results"},
        )


def test_workflow_stage_result_rejects_nested_raw_summary_keys() -> None:
    with pytest.raises(ValidationError):
        WorkflowStageResult(
            stage_id="tool",
            status=WorkflowStageStatus.WAITING,
            summary={"debug": {"raw_tool_payload": {"policy_id": "POL-001"}}},
        )


def test_workflow_stage_failure_diagnostic_is_independent_fact() -> None:
    diagnostic = WorkflowStageFailureDiagnostic(
        stage_id="intent_resolution",
        stage_label="Intent Resolution",
        event_type="model_output_normalization_failed",
        status=WorkflowStageStatus.BLOCKED,
        error_code="model_output_contract_validation_failed",
        role="intent_resolution",
        raw_content_length=378,
        related_event_id="evt_0011",
        contract_name="IntentResolution",
        violation_codes=("missing",),
        field_paths=("recommended_next_action",),
        violation_count=1,
    )
    result = WorkflowTemplateExecutionResult(
        run_id="run_001",
        template_name="react_enterprise_qa_v2",
        template_descriptor_version="react_enterprise_qa.v2",
        outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
        final_output="The intent resolution output failed validation.",
        message="The intent resolution output failed validation.",
        stage_failure_diagnostics=(diagnostic,),
    )

    assert result.stage_failure_diagnostics == (diagnostic,)


def test_approval_pause_is_a_trace_safe_execution_fact() -> None:
    pause = ApprovalPause(
        approval_id="appr_001",
        action_id="act_tool_1",
        tool_name="customer_lookup",
        policy_decision=PolicyDecisionType.REQUIRE_APPROVAL,
        checkpoint_ref="thread:run_001",
        expires_at="2026-06-15T10:00:00Z",
        summary={"risk_level": "medium", "parameter_count": 2},
    )

    assert pause.tool_name == "customer_lookup"
    assert pause.policy_decision is PolicyDecisionType.REQUIRE_APPROVAL
    with pytest.raises(TypeError):
        pause.summary["raw_tool_payload"] = {}


def test_clarification_need_is_distinct_from_approval_pause() -> None:
    need = ClarificationNeed(
        action_id="act_clarify_1",
        missing_fields=("policy_id",),
        message="Please provide the policy id.",
        summary={"missing_field_count": 1},
    )

    assert need.missing_fields == ("policy_id",)
    assert need.message == "Please provide the policy id."
    with pytest.raises(TypeError):
        need.summary["extra"] = "blocked"


def test_workflow_template_execution_input_carries_stage_runtime_facts() -> None:
    execution_input = WorkflowTemplateExecutionInput(
        run_id="run_001",
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        question="What is the reimbursement rule for travel meals?",
        agent_id="react_enterprise_qa",
        agent_version_id="version_001",
        effective_stage_configuration_ref="version_001:effective_workflow_stage_configuration",
        workflow_stage_availability=WorkflowStageAvailabilitySet(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(
                WorkflowStageAvailability(
                    stage_id="plan",
                    available=True,
                    reason=WorkflowStageAvailabilityReason.ALWAYS_AVAILABLE,
                ),
            ),
        ),
        effective_stage_configuration=EffectiveWorkflowStageConfiguration(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(
                EffectiveWorkflowStageConfigurationStage(
                    id="plan",
                    label="Plan",
                    description="Propose the next governed ReAct action.",
                    required=True,
                    model_bearing=True,
                    prompt={"business_context": "Claims context."},
                ),
            ),
        ),
        stage_configuration_source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION,
            reference="published_version:version_001",
        ),
    )

    assert execution_input.template_name == "react_enterprise_qa"
    assert execution_input.workflow_stage_availability.is_available("plan") is True
    assert execution_input.effective_stage_configuration.stage("plan").label == "Plan"
    assert (
        execution_input.stage_configuration_source.source_type
        is WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION
    )
    assert execution_input.effective_stage_configuration_ref == (
        "version_001:effective_workflow_stage_configuration"
    )


def test_workflow_template_execution_result_contains_governed_facts_only() -> None:
    evidence = EvidenceChunk(
        source="kb://policy.md",
        content="Trace-safe test evidence content.",
        admission_score=0.91,
        status=EvidenceStatus.ACCEPTED,
    )
    stage_result = WorkflowStageResult(
        stage_id="model_answer",
        status=WorkflowStageStatus.COMPLETED,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        summary={"accepted_evidence_count": 1},
        produced_fact_refs=("model_response:final_answer",),
    )
    result = WorkflowTemplateExecutionResult(
        run_id="run_001",
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        final_output="Travel meals are reimbursed when supported by receipts.",
        message="Travel meals are reimbursed when supported by receipts.",
        evidence=(evidence,),
        stage_results=(stage_result,),
        reasoning_summary={"selected_action": "plan_retrieval"},
        review_results=({"final_decision": "allow"},),
        model_usage_summary={"request_count": 1},
        trace_summary_refs=("published_version:version_001",),
        agent_id="react_enterprise_qa",
        agent_version_id="version_001",
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.stage_results == (stage_result,)
    assert result.trace_summary_refs == ("published_version:version_001",)


def test_workflow_template_execution_result_rejects_stage_result_continuation() -> None:
    stage_result = WorkflowStageResult(
        stage_id="plan",
        status=WorkflowStageStatus.COMPLETED,
        summary={"action_type": "plan_retrieval"},
        continuation={"action": {"action_id": "act_1"}},
    )

    with pytest.raises(ValidationError):
        WorkflowTemplateExecutionResult(
            run_id="run_001",
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Answer.",
            message="Answer.",
            stage_results=(stage_result,),
        )


def test_workflow_template_execution_result_rejects_artifact_paths() -> None:
    with pytest.raises(ValidationError):
        WorkflowTemplateExecutionResult(
            run_id="run_001",
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Answer.",
            message="Answer.",
            trace_path="/tmp/trace.jsonl",
        )
