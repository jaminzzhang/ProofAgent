from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast

from pydantic import Field, field_serializer, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ResolvedKnowledgeBinding(FrozenModel):
    binding_id: str
    source_scope: Literal["package", "shared"]
    source_id: str
    source_version_id: str
    provider: str
    provider_params: Mapping[str, Any] = Field(default_factory=FrozenDict)
    alias: str | None = None
    failure_mode: str = "required"
    fusion_weight: float = 1.0
    top_k: int | None = None
    routing_metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)

    @field_validator("provider_params", "routing_metadata", mode="after")
    @classmethod
    def freeze_mapping(cls, value: Any) -> Any:
        return freeze_value(value)

    @field_serializer("provider_params", "routing_metadata")
    def serialize_mapping(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _jsonable(value))


class ResolvedKnowledgeBindingSet(FrozenModel):
    bindings: tuple[ResolvedKnowledgeBinding, ...]
