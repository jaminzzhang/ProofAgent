"""Shared HTTP contracts for Business Flow Skill Pack configuration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from proof_agent.control.agent_configuration_skill_packs import (
    BusinessFlowSkillPackCreateCommand,
    BusinessFlowSkillPackUpdateCommand,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationSkillPackResult,
)
from proof_agent.delivery.agent_configuration_workflow_http import (
    WorkflowStagePromptRequest,
    workflow_stage_prompt_config,
)


class BusinessFlowSkillPackCreateFields(BaseModel):
    """Transport-neutral fields for creating one complete Skill Pack."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]*$")
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    intent_patterns: list[str] = Field(default_factory=list)
    intent_taxonomy_refs: list[str] = Field(default_factory=list)
    stage_prompt_addenda: dict[str, WorkflowStagePromptRequest] = Field(
        default_factory=dict
    )
    knowledge_binding_refs: list[str] = Field(default_factory=list)
    tool_contract_refs: list[str] = Field(default_factory=list)
    policy_rule_refs: list[str] = Field(default_factory=list)
    validator_refs: list[str] = Field(default_factory=list)
    admission: dict[str, Any] = Field(default_factory=dict)
    default: bool = False


class BusinessFlowSkillPackUpdateFields(BaseModel):
    """Transport-neutral fields for partially updating one Skill Pack."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1)
    description: str | None = Field(default=None, min_length=1)
    intent_patterns: list[str] | None = None
    intent_taxonomy_refs: list[str] | None = None
    stage_prompt_addenda: dict[str, WorkflowStagePromptRequest] | None = None
    knowledge_binding_refs: list[str] | None = None
    tool_contract_refs: list[str] | None = None
    policy_rule_refs: list[str] | None = None
    validator_refs: list[str] | None = None
    admission: dict[str, Any] | None = None
    default: bool | None = None


def business_flow_skill_pack_create_command(
    request: BusinessFlowSkillPackCreateFields,
) -> BusinessFlowSkillPackCreateCommand:
    """Translate one strict HTTP create request to the Workspace command."""

    return BusinessFlowSkillPackCreateCommand(
        pack_id=request.id,
        label=request.label,
        description=request.description,
        intent_patterns=tuple(request.intent_patterns),
        intent_taxonomy_refs=tuple(request.intent_taxonomy_refs),
        stage_prompt_addenda={
            stage_id: workflow_stage_prompt_config(prompt)
            for stage_id, prompt in request.stage_prompt_addenda.items()
        },
        knowledge_binding_refs=tuple(request.knowledge_binding_refs),
        tool_contract_refs=tuple(request.tool_contract_refs),
        policy_rule_refs=tuple(request.policy_rule_refs),
        validator_refs=tuple(request.validator_refs),
        admission=request.admission,
        default=request.default,
    )


def business_flow_skill_pack_update_command(
    request: BusinessFlowSkillPackUpdateFields,
) -> BusinessFlowSkillPackUpdateCommand:
    """Translate one strict HTTP update request to the Workspace command."""

    return BusinessFlowSkillPackUpdateCommand(
        label=request.label,
        description=request.description,
        intent_patterns=(
            None
            if request.intent_patterns is None
            else tuple(request.intent_patterns)
        ),
        intent_taxonomy_refs=(
            None
            if request.intent_taxonomy_refs is None
            else tuple(request.intent_taxonomy_refs)
        ),
        stage_prompt_addenda=(
            None
            if request.stage_prompt_addenda is None
            else {
                stage_id: workflow_stage_prompt_config(prompt)
                for stage_id, prompt in request.stage_prompt_addenda.items()
            }
        ),
        knowledge_binding_refs=(
            None
            if request.knowledge_binding_refs is None
            else tuple(request.knowledge_binding_refs)
        ),
        tool_contract_refs=(
            None
            if request.tool_contract_refs is None
            else tuple(request.tool_contract_refs)
        ),
        policy_rule_refs=(
            None
            if request.policy_rule_refs is None
            else tuple(request.policy_rule_refs)
        ),
        validator_refs=(
            None
            if request.validator_refs is None
            else tuple(request.validator_refs)
        ),
        admission=request.admission,
        default=request.default,
    )


def business_flow_skill_pack_result_payload(
    result: AgentConfigurationSkillPackResult,
) -> dict[str, Any]:
    """Serialize the revisioned Workspace projection for either Delivery mode."""

    payload = asdict(result.configuration)
    payload["revision"] = result.record.revision
    return payload
