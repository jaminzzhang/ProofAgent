from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal, cast

from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class ModelRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelCallRole(str, Enum):
    FINAL_ANSWER = "final_answer"
    INTENT_RESOLUTION = "intent_resolution"
    REACT_PLANNER = "react_planner"
    HARNESS_REVIEW = "harness_review"
    RETRIEVAL_PLANNER = "retrieval_planner"
    RETRIEVAL_EVALUATOR = "retrieval_evaluator"
    INGESTION = "ingestion"
    ROUTING = "routing"


class ModelMessage(FrozenModel):
    role: ModelRole
    content: str
    name: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


class TokenUsage(FrozenModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int | None = None


class ModelFunctionSchema(FrozenModel):
    """Provider-neutral function call contract for structured model output."""

    name: str
    description: str = ""
    parameters_schema: Mapping[str, Any] = Field(default_factory=FrozenDict)
    strict: bool = True

    @field_validator("parameters_schema", mode="after")
    @classmethod
    def freeze_parameters_schema(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("parameters_schema")
    def serialize_parameters_schema(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast("dict[str, Any]", _json_plain(value))


class ModelRequest(FrozenModel):
    messages: tuple[ModelMessage, ...]
    provider: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    stream: bool = False
    response_format: Literal["text", "json"] = "text"
    function_schema: ModelFunctionSchema | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    evidence_sources: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("messages", "evidence_sources", mode="after")
    @classmethod
    def freeze_sequences(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)


def _json_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_plain(item) for item in value]
    return value


class ModelResponse(FrozenModel):
    content: str
    provider_name: str
    model_name: str
    refusal_reason: str | None = None
    token_usage: TokenUsage | None = None
    finish_reason: str | None = None
    raw_response_id: str | None = None


class ModelConnectionResolutionRecord(FrozenModel):
    """Trace-safe projection of a model connection resolution."""

    role: ModelCallRole
    model_source: Literal["inline", "shared", "custom"]
    provider: str
    model_identifier: str
    usage_params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    connection_id: str | None = None
    base_url_host: str | None = None
    credential_ref: Mapping[str, str] | None = None
    warnings: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("usage_params", mode="after")
    @classmethod
    def freeze_usage_params(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("usage_params")
    def serialize_usage_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)
