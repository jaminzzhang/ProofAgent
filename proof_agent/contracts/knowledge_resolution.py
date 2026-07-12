from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_serializer,
    field_validator,
    model_validator,
)

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.knowledge_index import ExactArtifactRef


StrictNonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]
StrictPositiveInt = Annotated[StrictInt, Field(gt=0)]
FinitePositiveFloat = Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


class ResolvedKnowledgeBinding(FrozenModel):
    binding_kind: Literal["legacy"] = "legacy"
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


class ResolvedHybridKnowledgeBinding(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_kind: Literal["hybrid"] = "hybrid"
    binding_id: StrictNonBlankStr
    source_scope: Literal["shared"] = "shared"
    source_id: StrictNonBlankStr
    provider: Literal["hybrid_index"] = "hybrid_index"
    source_publication_id: StrictNonBlankStr
    source_snapshot_id: StrictNonBlankStr
    index_generation_id: StrictNonBlankStr
    source_publication_seq: StrictPositiveInt
    retrieval_profile_revision_id: StrictNonBlankStr
    manifest_ref: ExactArtifactRef
    publication_attestation_id: StrictNonBlankStr
    failure_mode: Literal["required", "advisory"] = "required"
    fusion_weight: FinitePositiveFloat = 1.0


ResolvedKnowledgeBindingItem = Annotated[
    ResolvedKnowledgeBinding | ResolvedHybridKnowledgeBinding,
    Field(discriminator="binding_kind"),
]


class ResolvedKnowledgeBindingSet(FrozenModel):
    bindings: tuple[ResolvedKnowledgeBindingItem, ...]

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_binding_discriminators(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        bindings = value.get("bindings")
        if not isinstance(bindings, list | tuple):
            return value

        migrated_bindings: list[Any] = []
        changed = False
        for binding in bindings:
            if isinstance(binding, Mapping) and "binding_kind" not in binding:
                migrated_bindings.append({**binding, "binding_kind": "legacy"})
                changed = True
            else:
                migrated_bindings.append(binding)

        if not changed:
            return value
        return {**value, "bindings": tuple(migrated_bindings)}

    @model_validator(mode="after")
    def reject_mismatched_legacy_hybrid_provider(self) -> Self:
        if any(
            isinstance(binding, ResolvedKnowledgeBinding) and binding.provider == "hybrid_index"
            for binding in self.bindings
        ):
            raise ValueError("hybrid_index provider requires binding_kind='hybrid'")
        return self
