from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import ConfigDict, Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.workflow_execution import WorkflowStageStatus


VALIDATION_CAPTURE_FORBIDDEN_KEYS = frozenset(
    {
        "raw_prompt",
        "raw_context",
        "raw_evidence",
        "raw_tool_payload",
        "raw_tool_payloads",
        "tool_payload",
        "tool_payloads",
        "provider_response",
        "provider_responses",
        "complete_provider_response",
        "complete_provider_responses",
        "runtime_state",
        "runtime_state_dict",
        "runtime_state_dicts",
        "langgraph_state",
        "chain_of_thought",
        "raw_chain_of_thought",
        "secret",
        "secrets",
        "password",
        "api_key",
        "access_token",
        "bearer",
        "authorization",
    }
)


class ValidationCaptureModel(FrozenModel):
    """Base model for Sensitive Validation Capture payload contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ValidationCaptureSourceReference(ValidationCaptureModel):
    """References that identify the executed configuration without raw YAML dumps."""

    run_id: str
    run_purpose: str
    agent_id: str | None = None
    agent_version_id: str | None = None
    draft_id: str | None = None
    validation_id: str | None = None
    template_name: str
    template_descriptor_version: str
    stage_configuration_source_type: str
    stage_configuration_source_reference: str | None = None
    effective_stage_configuration_ref: str | None = None


class WorkflowStagePromptValueCapture(ValidationCaptureModel):
    """Allowed effective Workflow Stage prompt values captured for validation."""

    stage_id: str
    stage_label: str | None = None
    prompt_values: Mapping[str, Any] = Field(default_factory=FrozenDict)
    prompt_field_names: tuple[str, ...] = Field(default_factory=tuple)
    prompt_character_count: int = 0
    redaction_applied: bool = False
    source: str | None = None

    @field_validator("prompt_values", mode="after")
    @classmethod
    def freeze_prompt_values(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, root="stage_prompt_values")
        return freeze_value(value)

    @field_serializer("prompt_values")
    def serialize_prompt_values(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class WorkflowStageContextConfigurationCapture(ValidationCaptureModel):
    """Selected context option keys from the run-start execution input."""

    stage_id: str
    stage_label: str | None = None
    selected_context_options: tuple[str, ...] = Field(default_factory=tuple)
    available_context_options: tuple[str, ...] = Field(default_factory=tuple)


class WorkflowStageContextApplicationProjection(ValidationCaptureModel):
    """Applied context safe summary returned by Workflow Template Execution."""

    stage_id: str
    stage_label: str | None = None
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, root="context_applications")
        return freeze_value(value)

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class WorkflowStageResultVerificationProjection(ValidationCaptureModel):
    """Intermediate stage result projection without continuation state."""

    stage_id: str
    stage_label: str | None = None
    status: WorkflowStageStatus
    outcome: ReceiptOutcome | None = None
    summary: Mapping[str, Any] = Field(default_factory=FrozenDict)
    produced_fact_refs: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("summary", mode="after")
    @classmethod
    def freeze_summary(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, root="stage_results")
        return freeze_value(value)

    @field_serializer("summary")
    def serialize_summary(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class WorkflowStageFailureDiagnosticProjection(ValidationCaptureModel):
    """Exceptional stage-stop diagnostic without raw failure payloads."""

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


class WorkflowStageLlmInteractionCapture(ValidationCaptureModel):
    """Sensitive validation-only LLM request/response JSON for stage tuning."""

    stage_id: str
    stage_label: str | None = None
    role: str
    provider: str
    model: str
    request_json: Mapping[str, Any] = Field(default_factory=FrozenDict)
    response_json: Any | None = None
    response_content_length: int = 0
    response_json_parse_error_code: str | None = None

    @field_validator("request_json", "response_json", mode="after")
    @classmethod
    def freeze_json(cls, value: Any) -> Any:
        _reject_forbidden_keys(value, root="llm_interactions")
        return freeze_value(value)

    @field_serializer("request_json")
    def serialize_request_json(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))

    @field_serializer("response_json")
    def serialize_response_json(self, value: Any) -> Any:
        return _jsonable(value)


class ValidationCaptureResultSummary(ValidationCaptureModel):
    """Terminal governed result projection for one validation attempt."""

    outcome: ReceiptOutcome
    final_output: str = ""
    final_output_length: int = 0
    fact_refs: tuple[str, ...] = Field(default_factory=tuple)
    approval_pause: Mapping[str, Any] | None = None
    clarification_need: Mapping[str, Any] | None = None

    @field_validator("approval_pause", "clarification_need", mode="after")
    @classmethod
    def freeze_optional_mapping(cls, value: Any) -> Any:
        if value is None:
            return None
        _reject_forbidden_keys(value, root="result_summary")
        return freeze_value(value)

    @field_serializer("approval_pause", "clarification_need")
    def serialize_optional_mapping(
        self,
        value: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return cast(dict[str, Any], _jsonable(value))


class ValidationCaptureExclusionSummary(ValidationCaptureModel):
    """Excluded categories and coarse sanitizer facts for validation capture."""

    excluded_categories: tuple[str, ...] = Field(default_factory=tuple)
    sanitizer_version: str
    redacted_secret_count: int = 0
    dropped_unsafe_key_count: int = 0
    redaction_applied: bool = False


class ValidationCaptureV2Payload(ValidationCaptureModel):
    """Typed payload stored inside a Sensitive Validation Capture Artifact."""

    capture_contract_version: Literal["validation_capture.v2"] = "validation_capture.v2"
    source: ValidationCaptureSourceReference
    stage_prompt_values: tuple[WorkflowStagePromptValueCapture, ...] = Field(
        default_factory=tuple
    )
    context_configuration: tuple[WorkflowStageContextConfigurationCapture, ...] = Field(
        default_factory=tuple
    )
    context_applications: tuple[WorkflowStageContextApplicationProjection, ...] = Field(
        default_factory=tuple
    )
    stage_results: tuple[WorkflowStageResultVerificationProjection, ...] = Field(
        default_factory=tuple
    )
    failure_diagnostics: tuple[WorkflowStageFailureDiagnosticProjection, ...] = Field(
        default_factory=tuple
    )
    llm_interactions: tuple[WorkflowStageLlmInteractionCapture, ...] = Field(
        default_factory=tuple
    )
    result_summary: ValidationCaptureResultSummary
    exclusions: ValidationCaptureExclusionSummary


def _reject_forbidden_keys(value: Any, *, root: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in VALIDATION_CAPTURE_FORBIDDEN_KEYS:
                raise ValueError(f"{root} contains forbidden validation capture key: {key}")
            _reject_forbidden_keys(item, root=root)
    elif isinstance(value, list | tuple):
        for item in value:
            _reject_forbidden_keys(item, root=root)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
