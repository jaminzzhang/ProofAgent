"""Published Agent Version binding to the sole KSS Knowledge authority."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, model_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel
from proof_agent.contracts.secrets import ProductionSecretHandle, SecretPurpose


StrictNonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ResolvedKnowledgeBinding(FrozenModel):
    """Legacy value object retained only for migration diagnostics.

    It is intentionally excluded from ``ResolvedKnowledgeBindingSet`` and therefore
    cannot be loaded into a Published Agent Version.
    """

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


class ResolvedKnowledgeSourceServiceBinding(FrozenModel):
    """Immutable KSS authority pinned by one Published Agent Version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding_kind: Literal["knowledge_source_service"] = "knowledge_source_service"
    binding_id: StrictNonBlankStr
    provider: Literal["knowledge_source_service"] = "knowledge_source_service"
    knowledge_base_release_id: StrictNonBlankStr
    client_credential_ref: ProductionSecretHandle
    admission_scorer_id: StrictNonBlankStr
    admission_scorer_revision: StrictNonBlankStr
    failure_mode: Literal["required"] = "required"

    @model_validator(mode="after")
    def require_knowledge_credential_reference(self) -> Self:
        if self.client_credential_ref.purpose is not SecretPurpose.KNOWLEDGE_CREDENTIAL:
            raise ValueError(
                "Knowledge Source Service binding requires a Knowledge credential reference"
            )
        return self


ResolvedKnowledgeBindingItem = ResolvedKnowledgeSourceServiceBinding


class ResolvedKnowledgeBindingSet(FrozenModel):
    bindings: tuple[ResolvedKnowledgeBindingItem, ...]


__all__ = [
    "ResolvedKnowledgeBinding",
    "ResolvedKnowledgeBindingItem",
    "ResolvedKnowledgeBindingSet",
    "ResolvedKnowledgeSourceServiceBinding",
]
