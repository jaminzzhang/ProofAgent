"""Stable health projections for Knowledge Source Service process roles."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


KnowledgeServiceDependencyName = Literal["postgresql", "object_storage", "search"]


class KnowledgeServiceLiveness(BaseModel):
    """Process liveness without dependency-readiness claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["knowledge-service-health.v1"] = "knowledge-service-health.v1"
    status: Literal["alive"] = "alive"
    service: Literal["knowledge-source-service"] = "knowledge-source-service"
    release_identity: str = Field(min_length=1)


class KnowledgeServiceDependencyReadiness(BaseModel):
    """One bounded dependency status without endpoint or credential details."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: KnowledgeServiceDependencyName
    status: Literal["ready", "unavailable"]


class KnowledgeServiceReadiness(BaseModel):
    """Readiness of every authority-bearing API dependency."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["knowledge-service-readiness.v1"] = (
        "knowledge-service-readiness.v1"
    )
    status: Literal["ready", "unavailable"]
    service: Literal["knowledge-source-service"] = "knowledge-source-service"
    release_identity: str = Field(min_length=1)
    dependencies: tuple[KnowledgeServiceDependencyReadiness, ...]
