"""Durable fenced publication-preparation job contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from proof_agent.capabilities.knowledge.hybrid.publication import PublicationCommit
from proof_agent.contracts._base import StrictFrozenModel


class PublicationPreparationJob(StrictFrozenModel):
    preparation_job_id: str = Field(min_length=1, max_length=255)
    operation_id: str = Field(min_length=1, max_length=255)
    validation_id: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=255)
    source_revision: int = Field(ge=1)
    source_draft_version_id: str = Field(min_length=1, max_length=255)
    smoke_query: str = Field(min_length=1, max_length=4_096)
    state: Literal["READY", "CLAIMED", "PREPARED", "FAILED"]
    fencing_token: int = Field(ge=0)
    worker_id: str | None = Field(default=None, min_length=1, max_length=512)
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    prepared_commit: PublicationCommit | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    safe_reason: str | None = Field(default=None, min_length=1, max_length=1_000)
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def require_lifecycle_shape(self) -> Self:
        for value in (
            self.created_at,
            self.updated_at,
            self.claimed_at,
            self.lease_expires_at,
            self.completed_at,
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(
                    "publication preparation timestamps must be timezone-aware"
                )
        claimed = self.state == "CLAIMED"
        if claimed != (
            self.worker_id is not None
            and self.claimed_at is not None
            and self.lease_expires_at is not None
        ):
            raise ValueError(
                "publication preparation claim fields do not match state"
            )
        terminal = self.state in {"PREPARED", "FAILED"}
        if terminal != (self.completed_at is not None):
            raise ValueError(
                "publication preparation completion does not match state"
            )
        if (self.state == "PREPARED") != (self.prepared_commit is not None):
            raise ValueError(
                "publication preparation result does not match state"
            )
        failed = self.state == "FAILED"
        if failed != (self.failure_code is not None and self.safe_reason is not None):
            raise ValueError(
                "publication preparation failure does not match state"
            )
        if (
            self.prepared_commit is not None
            and self.prepared_commit.attempt.validation_id != self.validation_id
        ):
            raise ValueError(
                "prepared publication commit validation identity diverges"
            )
        return self


class PublicationPreparationClaim(StrictFrozenModel):
    preparation_job_id: str = Field(min_length=1, max_length=255)
    operation_id: str = Field(min_length=1, max_length=255)
    worker_id: str = Field(min_length=1, max_length=512)
    fencing_token: int = Field(ge=1)
    claimed_at: datetime
    lease_expires_at: datetime

    @model_validator(mode="after")
    def require_lease(self) -> Self:
        if (
            self.claimed_at.tzinfo is None
            or self.claimed_at.utcoffset() is None
            or self.lease_expires_at.tzinfo is None
            or self.lease_expires_at.utcoffset() is None
            or self.lease_expires_at <= self.claimed_at
        ):
            raise ValueError("publication preparation lease is invalid")
        return self


__all__ = ["PublicationPreparationClaim", "PublicationPreparationJob"]
