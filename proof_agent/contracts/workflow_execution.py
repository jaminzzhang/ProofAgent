from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
import re
from typing import Any, cast

from pydantic import ConfigDict, Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.evidence import EvidenceChunk
from proof_agent.contracts.policy import PolicyDecisionType
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.workflow_stage_configuration import (
    EffectiveWorkflowStageConfiguration,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
)


SUMMARY_FORBIDDEN_KEYS = frozenset(
    {
        "raw_prompt",
        "raw_context",
        "raw_tool_payload",
        "provider_response",
        "langgraph_state",
        "chain_of_thought",
        "raw_chain_of_thought",
        "secret",
        "password",
        "api_key",
        "access_token",
        "bearer",
        "authorization",
    }
)

CONTINUATION_FORBIDDEN_KEYS = frozenset(
    {
        "chain_of_thought",
        "raw_chain_of_thought",
        "secret",
        "password",
        "api_key",
        "access_token",
        "bearer",
        "authorization",
    }
)


class WorkflowExecutionModel(FrozenModel):
    """Base for Workflow Template Execution contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class WorkflowStageStatus(str, Enum):
    """Status of one Workflow Template Stage result."""

    COMPLETED = "completed"
    BLOCKED = "blocked"
    WAITING = "waiting"
    SKIPPED = "skipped"


class WorkflowTemplateExecutionInput(WorkflowExecutionModel):
    """Run-scoped input facts for Workflow Template Execution."""

    run_id: str
    template_name: str
    template_descriptor_version: str
    question: str
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    effective_stage_configuration_ref: str | None = None
    workflow_stage_availability: WorkflowStageAvailabilitySet
    effective_stage_configuration: EffectiveWorkflowStageConfiguration
    stage_configuration_source: WorkflowStageConfigurationRuntimeSource
    conversation_context_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("conversation_context_summary", mode="after")
    @classmethod
    def freeze_conversation_context_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, SUMMARY_FORBIDDEN_KEYS, root="conversation_context_summary")
        return freeze_value(value)

    @field_serializer("conversation_context_summary")
    def serialize_conversation_context_summary(
        self,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class ApprovalPause(WorkflowExecutionModel):
    """Trace-safe fact for a workflow waiting on operator approval."""

    approval_id: str
    action_id: str
    tool_name: str
    policy_decision: PolicyDecisionType
    checkpoint_ref: str
    expires_at: str | None = None
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, SUMMARY_FORBIDDEN_KEYS, root="summary")
        return freeze_value(value)

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class ClarificationNeed(WorkflowExecutionModel):
    """Trace-safe fact for a workflow waiting on missing user information."""

    action_id: str | None = None
    missing_fields: tuple[str, ...] = Field(default_factory=tuple)
    message: str
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, SUMMARY_FORBIDDEN_KEYS, root="summary")
        return freeze_value(value)

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class WorkflowStageResult(WorkflowExecutionModel):
    """Typed envelope for one Workflow Template Stage result."""

    stage_id: str
    status: WorkflowStageStatus
    outcome: ReceiptOutcome | None = None
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
    produced_fact_refs: tuple[str, ...] = Field(default_factory=tuple)
    continuation: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, SUMMARY_FORBIDDEN_KEYS, root="summary")
        return freeze_value(value)

    @field_validator("continuation", mode="after")
    @classmethod
    def freeze_continuation(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, CONTINUATION_FORBIDDEN_KEYS, root="continuation")
        return freeze_value(value)

    @field_serializer("summary", "continuation")
    def serialize_mappings(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class WorkflowStageFailureDiagnostic(WorkflowExecutionModel):
    """Trace-safe diagnostic fact for an exceptional Workflow Template Stage stop."""

    stage_id: str
    stage_label: str | None = None
    event_type: str
    status: WorkflowStageStatus
    error_code: str
    role: str | None = None
    raw_content_length: int | None = None
    related_event_id: str | None = None
    contract_name: str | None = None
    violation_codes: tuple[str, ...] = Field(default_factory=tuple)
    field_paths: tuple[str, ...] = Field(default_factory=tuple)
    violation_count: int = 0

    @field_validator(
        "stage_id",
        "stage_label",
        "event_type",
        "error_code",
        "role",
        "related_event_id",
        "contract_name",
        mode="after",
    )
    @classmethod
    def bound_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_diagnostic_text(value)

    @field_validator("violation_codes", "field_paths", mode="after")
    @classmethod
    def bound_sequence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_bounded_diagnostic_text(item) for item in value)[:20]


class WorkflowStageLlmInteraction(WorkflowExecutionModel):
    """Sensitive validation-only model input/output fact for one stage call."""

    stage_id: str
    stage_label: str | None = None
    role: str
    provider: str
    model: str
    request_json: Mapping[str, Any] = Field(default_factory=FrozenDict)
    response_json: Any | None = None
    response_content_length: int = 0
    response_json_parse_error_code: str | None = None

    @field_validator(
        "stage_id",
        "stage_label",
        "role",
        "provider",
        "model",
        "response_json_parse_error_code",
        mode="after",
    )
    @classmethod
    def bound_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _bounded_diagnostic_text(value)

    @field_validator("request_json", "response_json", mode="after")
    @classmethod
    def freeze_json(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("request_json")
    def serialize_request_json(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))

    @field_serializer("response_json")
    def serialize_response_json(self, value: Any) -> Any:
        return _jsonable(value)


class WorkflowTemplateExecutionResult(WorkflowExecutionModel):
    """Governed facts produced by one Workflow Template Execution."""

    run_id: str
    template_name: str
    template_descriptor_version: str
    outcome: ReceiptOutcome
    final_output: str
    message: str
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    effective_stage_configuration_ref: str | None = None
    approval_pause: ApprovalPause | None = None
    clarification_need: ClarificationNeed | None = None
    evidence: tuple[EvidenceChunk, ...] = Field(default_factory=tuple)
    stage_results: tuple[WorkflowStageResult, ...] = Field(default_factory=tuple)
    intent_resolution: Mapping[str, Any] | None = None
    reasoning_summary: Mapping[str, Any] | None = None
    review_results: tuple[Mapping[str, Any], ...] = Field(default_factory=tuple)
    stage_context_applications: tuple[Mapping[str, Any], ...] = Field(
        default_factory=tuple
    )
    stage_failure_diagnostics: tuple[WorkflowStageFailureDiagnostic, ...] = Field(
        default_factory=tuple
    )
    stage_llm_interactions: tuple[WorkflowStageLlmInteraction, ...] = Field(
        default_factory=tuple
    )
    model_usage_summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
    trace_summary_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator(
        "intent_resolution",
        "reasoning_summary",
        "model_usage_summary",
        mode="after",
    )
    @classmethod
    def freeze_optional_mapping(cls, value: Any) -> Any:
        if value is None:
            return None
        _reject_forbidden_keys(value, SUMMARY_FORBIDDEN_KEYS, root="execution_result")
        return freeze_value(value)

    @field_validator("review_results", "stage_context_applications", mode="after")
    @classmethod
    def freeze_mapping_tuple(
        cls,
        value: tuple[Mapping[str, Any], ...],
    ) -> tuple[Mapping[str, Any], ...]:
        for item in value:
            _reject_forbidden_keys(item, SUMMARY_FORBIDDEN_KEYS, root="execution_result")
        return tuple(cast(Mapping[str, Any], freeze_value(item)) for item in value)

    @field_validator("stage_results", mode="after")
    @classmethod
    def reject_stage_result_continuation(
        cls,
        value: tuple[WorkflowStageResult, ...],
    ) -> tuple[WorkflowStageResult, ...]:
        for item in value:
            if item.continuation:
                raise ValueError(
                    "WorkflowTemplateExecutionResult stage_results must not include "
                    "Workflow Stage Continuation State"
                )
        return value

    @field_serializer("intent_resolution", "reasoning_summary", "model_usage_summary")
    def serialize_optional_mapping(
        self,
        value: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return cast(dict[str, Any], _jsonable(value))

    @field_serializer("review_results", "stage_context_applications")
    def serialize_mapping_tuples(
        self,
        value: tuple[Mapping[str, Any], ...],
    ) -> list[dict[str, Any]]:
        return [cast(dict[str, Any], _jsonable(item)) for item in value]


def _reject_forbidden_keys(
    value: Any,
    forbidden_keys: frozenset[str],
    *,
    root: str,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in forbidden_keys:
                raise ValueError(f"{root} contains forbidden workflow execution key: {key}")
            _reject_forbidden_keys(item, forbidden_keys, root=root)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_forbidden_keys(item, forbidden_keys, root=root)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def _bounded_diagnostic_text(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.: -]+", "_", value.strip())
    return (cleaned or "unknown")[:160]
