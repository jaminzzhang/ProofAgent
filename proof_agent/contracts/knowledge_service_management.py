"""Browser-safe projections for Knowledge Source Service management through the BFF."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, computed_field

from proof_agent.contracts._base import StrictFrozenModel


KnowledgeServiceIdentifier = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
    ),
]


class KnowledgeServiceReadinessProjection(StrictFrozenModel):
    state: Literal["ready", "unavailable"]
    revision: str | None = Field(default=None, min_length=1, max_length=255)
    blockers: tuple[str, ...] = Field(default_factory=tuple, max_length=16)


class KnowledgeServiceSpaceProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier


class KnowledgeServiceSourceProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier


class KnowledgeServiceBaseProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier


class KnowledgeServiceSourceVersionProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_source_id: KnowledgeServiceIdentifier
    knowledge_source_version_id: KnowledgeServiceIdentifier
    source_kind: Literal["document", "dataset"]
    media_type: str = Field(min_length=1, max_length=255)


class KnowledgeServiceReleaseProjection(StrictFrozenModel):
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_version_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    source_version_count: int = Field(ge=1, le=10_000)
    state: Literal["queryable", "retired"]


class KnowledgeServiceManagementSummary(StrictFrozenModel):
    spaces: int = Field(ge=0)
    sources: int = Field(ge=0)
    bases: int = Field(ge=0)
    source_versions: int = Field(ge=0)
    releases: int = Field(ge=0)


class KnowledgeServiceManagementWorkspace(StrictFrozenModel):
    schema_version: Literal["knowledge-service-management.v1"] = "knowledge-service-management.v1"
    readiness: KnowledgeServiceReadinessProjection
    spaces: tuple[KnowledgeServiceSpaceProjection, ...] = Field(max_length=1_000)
    sources: tuple[KnowledgeServiceSourceProjection, ...] = Field(max_length=10_000)
    bases: tuple[KnowledgeServiceBaseProjection, ...] = Field(max_length=10_000)
    source_versions: tuple[KnowledgeServiceSourceVersionProjection, ...] = Field(max_length=10_000)
    releases: tuple[KnowledgeServiceReleaseProjection, ...] = Field(max_length=10_000)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> KnowledgeServiceManagementSummary:
        return KnowledgeServiceManagementSummary(
            spaces=len(self.spaces),
            sources=len(self.sources),
            bases=len(self.bases),
            source_versions=len(self.source_versions),
            releases=len(self.releases),
        )


__all__ = [
    "KnowledgeServiceBaseProjection",
    "KnowledgeServiceIdentifier",
    "KnowledgeServiceManagementSummary",
    "KnowledgeServiceManagementWorkspace",
    "KnowledgeServiceReadinessProjection",
    "KnowledgeServiceReleaseProjection",
    "KnowledgeServiceSourceProjection",
    "KnowledgeServiceSourceVersionProjection",
    "KnowledgeServiceSpaceProjection",
]
