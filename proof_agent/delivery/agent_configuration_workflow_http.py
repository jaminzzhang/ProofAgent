"""Shared HTTP contracts for Agent Workflow configuration routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts import (
    WorkflowStageConfig,
    WorkflowStageContextConfig,
    WorkflowStagePromptConfig,
)
from proof_agent.contracts.workflow_policy import (
    AssurancePolicy,
    InteractionPolicy,
    WorkflowExecutionPolicy,
)


class WorkflowPolicyPatchRequest(BaseModel):
    """Absent sections stay untouched; explicit null removes one policy section."""

    model_config = ConfigDict(extra="forbid")

    execution: WorkflowExecutionPolicy | None = None
    interaction: InteractionPolicy | None = None
    assurance: AssurancePolicy | None = None

    def as_patch(self) -> dict[str, Any]:
        """Preserve explicit fields even inside the frozen checkpoint mappings."""

        payload = self.model_dump(mode="json", exclude_unset=True)
        for section in ("interaction", "assurance"):
            policy = getattr(self, section)
            if policy is not None and "checkpoints" in policy.model_fields_set:
                payload[section]["checkpoints"] = {
                    stage: checkpoint.model_dump(mode="json", exclude_unset=True)
                    for stage, checkpoint in policy.checkpoints.items()
                }
        return payload


class WorkflowExecutionPreviewRequest(BaseModel):
    """Compile an unsaved policy against one exact Draft revision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1, strict=True)
    policy: WorkflowPolicyPatchRequest = Field(default_factory=WorkflowPolicyPatchRequest)


class WorkflowStagePromptRequest(BaseModel):
    """Stage-level business Prompt settings accepted by the Dashboard API."""

    model_config = ConfigDict(extra="forbid")

    business_context: str | None = None
    task_instructions: list[str] = Field(default_factory=list)
    output_preferences: list[str] = Field(default_factory=list)


class WorkflowStageUpdateItemRequest(BaseModel):
    """One Workflow Stage configuration item."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    prompt: WorkflowStagePromptRequest = Field(default_factory=WorkflowStagePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


class WorkflowStagePreviewRequest(BaseModel):
    """Unsaved Prompt and Context options for a bounded Stage preview."""

    model_config = ConfigDict(extra="forbid")

    prompt: WorkflowStagePromptRequest = Field(default_factory=WorkflowStagePromptRequest)
    context: dict[str, bool] = Field(default_factory=dict)


def workflow_template_payload(descriptor: Any) -> dict[str, Any]:
    """Serialize one backend-owned Workflow Template Descriptor."""

    payload = asdict(descriptor)
    payload["stages"] = [asdict(stage) for stage in descriptor.stages]
    return payload


def workflow_stage_prompt_config(
    prompt: WorkflowStagePromptRequest,
) -> WorkflowStagePromptConfig:
    """Translate one strict HTTP Prompt fragment to the Control contract."""

    return WorkflowStagePromptConfig(
        business_context=prompt.business_context or "",
        task_instructions=tuple(prompt.task_instructions),
        output_preferences=tuple(prompt.output_preferences),
    )


def workflow_stage_config_request(
    item: WorkflowStageUpdateItemRequest,
) -> WorkflowStageConfig:
    """Translate one strict HTTP Stage item to the Control contract."""

    return WorkflowStageConfig(
        id=item.id,
        prompt=workflow_stage_prompt_config(item.prompt),
        context=WorkflowStageContextConfig(options=item.context),
    )


__all__ = [
    "WorkflowExecutionPreviewRequest",
    "WorkflowPolicyPatchRequest",
    "WorkflowStagePreviewRequest",
    "WorkflowStagePromptRequest",
    "WorkflowStageUpdateItemRequest",
    "workflow_stage_config_request",
    "workflow_stage_prompt_config",
    "workflow_template_payload",
]
