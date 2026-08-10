"""Durable fenced command contracts for Metadata Workbook V2."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictStr, StringConstraints, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_index import ExactArtifactRef


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]


class MetadataWorkbookJobV2(StrictFrozenModel):
    job_id: NonBlankStr
    operation_id: NonBlankStr
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    source_revision: int = Field(ge=1)
    command: Literal["generate_export", "create_preview", "apply_preview"]
    resource_id: NonBlankStr
    parent_resource_id: NonBlankStr | None = None
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_ref: ExactArtifactRef | None = None
    expected_preview_identity: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    reason: NonBlankStr | None = None
    state: Literal["READY", "CLAIMED", "COMPLETED", "FAILED"]
    fencing_token: int = Field(ge=0)
    worker_id: NonBlankStr | None = None
    claimed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    failure_code: NonBlankStr | None = None
    safe_reason: NonBlankStr | None = None
    created_by: NonBlankStr
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def require_command_and_lifecycle_consistency(self) -> Self:
        preview_inputs = (
            self.parent_resource_id is not None and self.original_ref is not None
        )
        apply_inputs = (
            self.expected_preview_identity is not None and self.reason is not None
        )
        if self.command == "generate_export" and (
            preview_inputs
            or apply_inputs
            or self.parent_resource_id is not None
            or self.original_ref is not None
        ):
            raise ValueError("generate_export job contains unrelated inputs")
        if self.command == "create_preview" and (
            not preview_inputs or apply_inputs
        ):
            raise ValueError("create_preview job requires an Export and exact artifact")
        if self.command == "apply_preview" and (
            not apply_inputs
            or self.parent_resource_id is not None
            or self.original_ref is not None
        ):
            raise ValueError("apply_preview job requires exact Preview identity and reason")
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
                raise ValueError("Metadata Workbook job timestamps must be timezone-aware")
        claimed = self.state == "CLAIMED"
        if claimed != (
            self.worker_id is not None
            and self.claimed_at is not None
            and self.lease_expires_at is not None
        ):
            raise ValueError("Metadata Workbook claim fields do not match job state")
        terminal = self.state in {"COMPLETED", "FAILED"}
        if terminal != (self.completed_at is not None):
            raise ValueError("Metadata Workbook completion fields do not match job state")
        failed = self.state == "FAILED"
        if failed != (self.failure_code is not None and self.safe_reason is not None):
            raise ValueError("Metadata Workbook failure fields do not match job state")
        return self


class MetadataWorkbookJobClaimV2(StrictFrozenModel):
    job_id: NonBlankStr
    operation_id: NonBlankStr
    worker_id: NonBlankStr
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
            raise ValueError("Metadata Workbook claim timestamps must be timezone-aware")
        if self.lease_expires_at <= self.claimed_at:
            raise ValueError("Metadata Workbook claim expiry must follow claim time")
        return self


__all__ = ["MetadataWorkbookJobClaimV2", "MetadataWorkbookJobV2"]
