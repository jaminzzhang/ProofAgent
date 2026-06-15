from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, cast

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class WorkflowStageConfigurationModel(FrozenModel):
    """Base for Workflow Stage configuration contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkflowStageAvailabilityReason(str, Enum):
    """Reason one Workflow Template Stage is available or unavailable."""

    ALWAYS_AVAILABLE = "always_available"
    CAPABILITY_ENABLED = "capability_enabled"
    CAPABILITY_DISABLED = "capability_disabled"


class WorkflowStageAvailability(WorkflowStageConfigurationModel):
    """Resolved availability of one Workflow Template Stage."""

    stage_id: str
    available: bool
    reason: WorkflowStageAvailabilityReason
    capability: str = "none"


class WorkflowStageAvailabilitySet(WorkflowStageConfigurationModel):
    """Resolved Workflow Stage Availability for one template and Agent Contract."""

    template_name: str
    template_descriptor_version: str
    stages: tuple[WorkflowStageAvailability, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def reject_duplicate_stage_ids(self) -> WorkflowStageAvailabilitySet:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for stage in self.stages:
            if stage.stage_id in seen:
                duplicates.add(stage.stage_id)
            seen.add(stage.stage_id)
        if duplicates:
            raise ValueError(
                "WorkflowStageAvailabilitySet stage ids must be unique: "
                + ", ".join(sorted(duplicates))
            )
        return self

    def is_available(self, stage_id: str) -> bool:
        return any(stage.stage_id == stage_id and stage.available for stage in self.stages)

    @property
    def available_stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.stage_id for stage in self.stages if stage.available)


class WorkflowStageConfigurationRuntimeSourceType(str, Enum):
    """Trace-safe category for the source of stage runtime configuration."""

    PUBLISHED_AGENT_VERSION = "published_agent_version"
    PACKAGE_LOCAL_LATEST = "package_local_latest"


class WorkflowStageConfigurationRuntimeSource(WorkflowStageConfigurationModel):
    """Trace-safe reference to a run's Workflow Stage configuration source."""

    source_type: WorkflowStageConfigurationRuntimeSourceType
    reference: str | None = None


class WorkflowStageConfigurationTraceStageSummary(WorkflowStageConfigurationModel):
    """Trace-safe summary for one effective Workflow Template Stage configuration."""

    stage_id: str
    prompt_field_names: tuple[str, ...] = Field(default_factory=tuple)
    prompt_character_count: int = 0
    context_option_names: tuple[str, ...] = Field(default_factory=tuple)
    redacted: bool = True


class WorkflowStageConfigurationTraceSummary(WorkflowStageConfigurationModel):
    """Trace-safe summary of a run's Workflow Stage configuration."""

    source: WorkflowStageConfigurationRuntimeSource
    template_name: str
    template_descriptor_version: str
    stages: tuple[WorkflowStageConfigurationTraceStageSummary, ...] = Field(
        default_factory=tuple
    )


class PublishedAgentRuntimeFacts(WorkflowStageConfigurationModel):
    """Published Agent runtime facts copied into Workflow Template Execution."""

    agent_id: str
    agent_version_id: str
    workflow_stage_availability: WorkflowStageAvailabilitySet
    effective_stage_configuration: EffectiveWorkflowStageConfiguration


class ResolvedWorkflowStageRuntimeConfiguration(WorkflowStageConfigurationModel):
    """Resolved Workflow Stage runtime configuration facts for one run or publication."""

    workflow_stage_availability: WorkflowStageAvailabilitySet
    effective_stage_configuration: EffectiveWorkflowStageConfiguration
    configuration_source: WorkflowStageConfigurationRuntimeSource
    trace_summary: WorkflowStageConfigurationTraceSummary


class EffectiveWorkflowStageConfigurationStage(WorkflowStageConfigurationModel):
    """Effective configuration for one available Workflow Template Stage."""

    id: str
    label: str
    description: str
    required: bool
    model_bearing: bool
    editable_prompt_fields: tuple[str, ...] = Field(default_factory=tuple)
    available_context_options: tuple[str, ...] = Field(default_factory=tuple)
    prompt: Mapping[str, Any] = Field(default_factory=FrozenDict)
    context: Mapping[str, bool] = Field(default_factory=FrozenDict)
    source_override: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("prompt", "context", "source_override", mode="after")
    @classmethod
    def freeze_mappings(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("prompt", "context", "source_override")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class EffectiveWorkflowStageConfiguration(WorkflowStageConfigurationModel):
    """Effective Workflow Stage Configuration for available stages."""

    template_name: str
    template_descriptor_version: str
    stages: tuple[EffectiveWorkflowStageConfigurationStage, ...] = Field(default_factory=tuple)
    capabilities: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("capabilities", mode="after")
    @classmethod
    def freeze_capabilities(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("capabilities")
    def serialize_capabilities(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))

    @model_validator(mode="after")
    def reject_duplicate_stage_ids(self) -> EffectiveWorkflowStageConfiguration:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for stage in self.stages:
            if stage.id in seen:
                duplicates.add(stage.id)
            seen.add(stage.id)
        if duplicates:
            raise ValueError(
                "EffectiveWorkflowStageConfiguration stage ids must be unique: "
                + ", ".join(sorted(duplicates))
            )
        return self

    @property
    def stage_ids(self) -> tuple[str, ...]:
        return tuple(stage.id for stage in self.stages)

    def stage(self, stage_id: str) -> EffectiveWorkflowStageConfigurationStage:
        for candidate in self.stages:
            if candidate.id == stage_id:
                return candidate
        raise KeyError(stage_id)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
