"""Durable, fenced metadata workbook import job contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import Field, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_index import ExactArtifactRef


class MetadataImportJob(StrictFrozenModel):
    """PostgreSQL-authoritative work item for one exact workbook revision."""

    import_job_id: str = Field(min_length=1, max_length=255)
    operation_id: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=255)
    document_id: str = Field(min_length=1, max_length=255)
    revision_id: str = Field(min_length=1, max_length=255)
    source_revision: int = Field(ge=1)
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    filename: str = Field(min_length=1, max_length=255)
    original_ref: ExactArtifactRef
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["READY", "CLAIMED", "COMPLETED", "FAILED"]
    fencing_token: int = Field(ge=0)
    worker_id: str | None = Field(default=None, min_length=1, max_length=512)
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    safe_reason: str | None = Field(default=None, min_length=1, max_length=1_000)
    result_import_id: str | None = Field(default=None, min_length=1, max_length=512)
    created_by: str = Field(min_length=1, max_length=512)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def require_consistent_lifecycle(self) -> Self:
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
                raise ValueError("metadata import timestamps must be timezone-aware")
        claimed = self.state == "CLAIMED"
        if claimed != (
            self.worker_id is not None
            and self.claimed_at is not None
            and self.lease_expires_at is not None
        ):
            raise ValueError("metadata import claim fields do not match job state")
        terminal = self.state in {"COMPLETED", "FAILED"}
        if terminal != (self.completed_at is not None):
            raise ValueError("metadata import completion timestamp does not match job state")
        if (self.state == "COMPLETED") != (self.result_import_id is not None):
            raise ValueError("metadata import result does not match job state")
        failed = self.state == "FAILED"
        if failed != (self.failure_code is not None and self.safe_reason is not None):
            raise ValueError("metadata import failure fields do not match job state")
        if self.content_sha256 != self.original_ref.sha256:
            raise ValueError("metadata import content identity diverges from artifact")
        return self


class MetadataImportJobClaim(StrictFrozenModel):
    """One expiring ownership fence for a metadata import job."""

    import_job_id: str = Field(min_length=1, max_length=255)
    operation_id: str = Field(min_length=1, max_length=255)
    worker_id: str = Field(min_length=1, max_length=512)
    fencing_token: int = Field(ge=1)
    claimed_at: datetime
    lease_expires_at: datetime

    @model_validator(mode="after")
    def require_aware_ordered_lease(self) -> Self:
        if (
            self.claimed_at.tzinfo is None
            or self.claimed_at.utcoffset() is None
            or self.lease_expires_at.tzinfo is None
            or self.lease_expires_at.utcoffset() is None
        ):
            raise ValueError("metadata import lease timestamps must be timezone-aware")
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("metadata import lease must expire after it is claimed")
        return self


__all__ = ["MetadataImportJob", "MetadataImportJobClaim"]
