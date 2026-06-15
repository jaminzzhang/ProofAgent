from __future__ import annotations

import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowStageConfigurationTraceStageSummary,
    WorkflowStageConfigurationTraceSummary,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
)


def test_workflow_stage_availability_set_reports_available_stages() -> None:
    availability = WorkflowStageAvailabilitySet(
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        stages=(
            WorkflowStageAvailability(
                stage_id="plan",
                available=True,
                reason=WorkflowStageAvailabilityReason.ALWAYS_AVAILABLE,
            ),
            WorkflowStageAvailability(
                stage_id="tool",
                available=False,
                reason=WorkflowStageAvailabilityReason.CAPABILITY_DISABLED,
                capability="tools",
            ),
        ),
    )

    assert availability.is_available("plan") is True
    assert availability.is_available("tool") is False
    assert availability.is_available("missing") is False
    assert availability.available_stage_ids == ("plan",)
    with pytest.raises(ValidationError):
        availability.stages[0].available = False


def test_workflow_stage_availability_set_rejects_duplicate_stage_ids() -> None:
    with pytest.raises(ValidationError):
        WorkflowStageAvailabilitySet(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(
                WorkflowStageAvailability(
                    stage_id="plan",
                    available=True,
                    reason=WorkflowStageAvailabilityReason.ALWAYS_AVAILABLE,
                ),
                WorkflowStageAvailability(
                    stage_id="plan",
                    available=True,
                    reason=WorkflowStageAvailabilityReason.ALWAYS_AVAILABLE,
                ),
            ),
        )


def test_effective_workflow_stage_configuration_uses_typed_frozen_stages() -> None:
    configuration = EffectiveWorkflowStageConfiguration(
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        stages=(
            EffectiveWorkflowStageConfigurationStage(
                id="plan",
                label="Plan",
                description="Propose the next governed ReAct action.",
                required=True,
                model_bearing=True,
                editable_prompt_fields=("business_context",),
                available_context_options=("include_agent_purpose",),
                prompt={"business_context": "Claims context."},
                context={"include_agent_purpose": True},
                source_override={"configured": True},
            ),
        ),
        capabilities={"tools": {"enabled": False}},
    )

    assert configuration.stage_ids == ("plan",)
    assert configuration.stage("plan").label == "Plan"
    assert configuration.model_dump(mode="json")["stages"] == [
        {
            "id": "plan",
            "label": "Plan",
            "description": "Propose the next governed ReAct action.",
            "required": True,
            "model_bearing": True,
            "editable_prompt_fields": ["business_context"],
            "available_context_options": ["include_agent_purpose"],
            "prompt": {"business_context": "Claims context."},
            "context": {"include_agent_purpose": True},
            "source_override": {"configured": True},
        }
    ]
    with pytest.raises(TypeError):
        configuration.stage("plan").prompt["business_context"] = "mutated"


def test_effective_workflow_stage_configuration_rejects_duplicate_stage_ids() -> None:
    stage = EffectiveWorkflowStageConfigurationStage(
        id="plan",
        label="Plan",
        description="Propose the next governed ReAct action.",
        required=True,
        model_bearing=True,
    )

    with pytest.raises(ValidationError):
        EffectiveWorkflowStageConfiguration(
            template_name="react_enterprise_qa",
            template_descriptor_version="react_enterprise_qa.v1",
            stages=(stage, stage),
        )


def test_workflow_stage_configuration_trace_summary_is_trace_safe() -> None:
    summary = WorkflowStageConfigurationTraceSummary(
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION,
            reference="published_version:version_001",
        ),
        template_name="react_enterprise_qa",
        template_descriptor_version="react_enterprise_qa.v1",
        stages=(
            WorkflowStageConfigurationTraceStageSummary(
                stage_id="plan",
                prompt_field_names=("business_context",),
                prompt_character_count=15,
                context_option_names=("include_agent_purpose",),
                redacted=True,
            ),
        ),
    )

    payload = summary.model_dump(mode="json")

    assert payload["source"] == {
        "source_type": "published_agent_version",
        "reference": "published_version:version_001",
    }
    assert payload["stages"] == [
        {
            "stage_id": "plan",
            "prompt_field_names": ["business_context"],
            "prompt_character_count": 15,
            "context_option_names": ["include_agent_purpose"],
            "redacted": True,
        }
    ]
    assert "raw_prompt" not in str(payload)
