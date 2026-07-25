"""Sanitized deployment identity reported by production readiness endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.run_execution import RoleActivationState


ProductionRole = Literal[
    "api",
    "run_executor",
    "knowledge_worker",
    "dashboard",
    "operator_chat",
]


class ProductionDeploymentIdentity(StrictFrozenModel):
    """Candidate identity safe to expose from unauthenticated readiness."""

    release_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    image_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_slot: Literal["blue", "green"]
    role: ProductionRole
    activation_state: RoleActivationState
    schema_revision: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    schema_compatible_from: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    schema_compatible_through: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    deployment_compatibility_manifest_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$"
    )

    @field_validator(
        "release_id",
        "schema_revision",
        "schema_compatible_from",
        "schema_compatible_through",
    )
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if value.strip() != value or any(ord(char) < 32 for char in value):
            raise ValueError("production readiness identity must be trace-safe")
        return value


__all__ = ["ProductionDeploymentIdentity", "ProductionRole"]
