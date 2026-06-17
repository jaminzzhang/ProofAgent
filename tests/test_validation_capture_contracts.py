from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import ReceiptOutcome, WorkflowStageStatus
from proof_agent.contracts.validation_capture import (
    ValidationCaptureExclusionSummary,
    ValidationCaptureResultSummary,
    ValidationCaptureSourceReference,
    ValidationCaptureV2Payload,
    WorkflowStageContextApplicationProjection,
    WorkflowStageContextConfigurationCapture,
    WorkflowStageFailureDiagnosticProjection,
    WorkflowStagePromptValueCapture,
    WorkflowStageResultVerificationProjection,
)


def _minimal_payload(**overrides: object) -> ValidationCaptureV2Payload:
    payload = {
        "source": ValidationCaptureSourceReference(
            run_id="run_validation",
            run_purpose="validation",
            agent_id="agent_001",
            draft_id="draft_001",
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stage_configuration_source_type="package_local_latest",
            stage_configuration_source_reference="package:agent.yaml",
            effective_stage_configuration_ref=None,
        ),
        "stage_prompt_values": (
            WorkflowStagePromptValueCapture(
                stage_id="plan",
                stage_label="Plan",
                prompt_values={"business_context": "Claims QA context."},
                prompt_field_names=("business_context",),
                prompt_character_count=18,
                redaction_applied=False,
            ),
        ),
        "context_configuration": (
            WorkflowStageContextConfigurationCapture(
                stage_id="plan",
                stage_label="Plan",
                selected_context_options=("conversation_summary",),
                available_context_options=("conversation_summary",),
            ),
        ),
        "context_applications": (
            WorkflowStageContextApplicationProjection(
                stage_id="plan",
                stage_label="Plan",
                summary={
                    "stage_id": "plan",
                    "context_options": ("conversation_summary",),
                    "business_context_addendum_length": 18,
                },
            ),
        ),
        "stage_results": (
            WorkflowStageResultVerificationProjection(
                stage_id="plan",
                stage_label="Plan",
                status=WorkflowStageStatus.COMPLETED,
                outcome=None,
                summary={"action_type": "plan_retrieval"},
                produced_fact_refs=("action:act_1",),
            ),
        ),
        "failure_diagnostics": (
            WorkflowStageFailureDiagnosticProjection(
                stage_id="plan",
                stage_label="Plan",
                event_type="model_output_normalization_failed",
                status=WorkflowStageStatus.BLOCKED,
                error_code="model_output_contract_validation_failed",
                role="react_planner",
                raw_content_length=31,
                related_event_id="evt_0004",
                contract_name="ReActActionProposal",
                violation_codes=("missing",),
                field_paths=("action_type",),
                violation_count=1,
            ),
        ),
        "result_summary": ValidationCaptureResultSummary(
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            final_output="Travel meals require receipts.",
            final_output_length=30,
            fact_refs=("model_response:final_answer",),
        ),
        "exclusions": ValidationCaptureExclusionSummary(
            excluded_categories=(
                "raw_prompt",
                "raw_context",
                "raw_evidence",
                "tool_payload",
                "provider_response",
                "runtime_state",
                "chain_of_thought",
            ),
            sanitizer_version="validation_capture.v2",
            redacted_secret_count=0,
            dropped_unsafe_key_count=0,
            redaction_applied=False,
        ),
    }
    payload.update(overrides)
    return ValidationCaptureV2Payload(**payload)


def test_validation_capture_v2_payload_uses_semantic_sections() -> None:
    payload = _minimal_payload()

    dumped = payload.model_dump(mode="json")

    assert dumped["capture_contract_version"] == "validation_capture.v2"
    assert set(dumped) == {
        "capture_contract_version",
        "source",
        "stage_prompt_values",
        "context_configuration",
        "context_applications",
        "stage_results",
        "failure_diagnostics",
        "result_summary",
        "exclusions",
    }
    assert dumped["source"]["run_id"] == "run_validation"
    assert dumped["stage_prompt_values"][0]["stage_id"] == "plan"
    assert dumped["stage_prompt_values"][0]["stage_label"] == "Plan"
    assert dumped["context_configuration"][0]["selected_context_options"] == [
        "conversation_summary"
    ]
    assert dumped["context_applications"][0]["summary"]["stage_id"] == "plan"
    assert dumped["stage_results"][0]["produced_fact_refs"] == ["action:act_1"]
    assert dumped["failure_diagnostics"][0]["field_paths"] == ["action_type"]
    assert dumped["result_summary"]["final_output"] == "Travel meals require receipts."


@pytest.mark.parametrize(
    ("section", "value"),
    (
        ("stage_prompt_values", {"raw_prompt": "never"}),
        ("context_applications", {"raw_context": "never"}),
        ("stage_results", {"runtime_state": "never"}),
        ("result_summary", {"provider_response": "never"}),
    ),
)
def test_validation_capture_v2_payload_rejects_forbidden_keys(
    section: str,
    value: dict[str, str],
) -> None:
    payload = _minimal_payload()
    data = payload.model_dump(mode="python")

    if section == "stage_prompt_values":
        data[section][0]["prompt_values"] = value
    elif section == "context_applications":
        data[section][0]["summary"] = value
    elif section == "stage_results":
        data[section][0]["summary"] = value
    elif section == "result_summary":
        data[section]["approval_pause"] = value

    with pytest.raises(ValidationError):
        ValidationCaptureV2Payload(**data)


def test_validation_capture_failure_diagnostic_rejects_free_form_message() -> None:
    payload = _minimal_payload()
    data = payload.model_dump(mode="python")
    data["failure_diagnostics"][0]["message"] = "raw validation detail should not pass"

    with pytest.raises(ValidationError):
        ValidationCaptureV2Payload(**data)
