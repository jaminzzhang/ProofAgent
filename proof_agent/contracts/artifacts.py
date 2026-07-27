from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Self

from pydantic import Field, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel


_SHA256 = re.compile(r"[0-9a-f]{64}")
_OBJECT_KEY = re.compile(
    r"objects/[0-9a-f]{2}/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}"
)


class ArtifactKind(StrEnum):
    RUN_TRACE = "run_trace"
    GOVERNANCE_RECEIPT = "governance_receipt"
    VALIDATION_CAPTURE = "validation_capture"
    KNOWLEDGE_SOURCE = "knowledge_source"
    KNOWLEDGE_INDEX_MEMBER = "knowledge_index_member"
    KNOWLEDGE_MANIFEST = "knowledge_manifest"
    AGENT_CONFIGURATION_BUNDLE = "agent_configuration_bundle"
    EVALUATION_EVIDENCE = "evaluation_evidence"
    RELEASE_MANIFEST = "release_manifest"
    HTML_REPORT = "html_report"
    BUNDLE_INDEX = "bundle_index"
    RELEASE_ATTESTATION = "release_attestation"
    RELEASE_CLOSURE_AUDIT = "release_closure_audit"
    SOFTWARE_BILL_OF_MATERIALS = "software_bill_of_materials"
    BUILD_PROVENANCE = "build_provenance"
    ARTIFACT_MANIFEST = "artifact_manifest"


class ArtifactOwner(StrictFrozenModel):
    owner_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    owner_id: str = Field(min_length=1, max_length=512)

    @field_validator("owner_id")
    @classmethod
    def validate_owner_id(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value) or value.strip() != value:
            raise ValueError("artifact owner_id is invalid")
        return value


class ArtifactPutRequest(StrictFrozenModel):
    kind: ArtifactKind
    owner: ArtifactOwner
    content_type: str = Field(min_length=1, max_length=255)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_size_bytes: int = Field(ge=1, le=5 * 1024 * 1024 * 1024)
    display_filename: str | None = Field(default=None, max_length=255)
    expires_at: datetime | None = None

    @field_validator("display_filename")
    @classmethod
    def validate_display_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            value in {".", ".."}
            or value.strip() != value
            or "/" in value
            or "\\" in value
            or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("artifact display filename is invalid")
        return value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("artifact expiry must be timezone-aware")
        return value


class ArtifactObjectVersion(StrictFrozenModel):
    object_id: str = Field(min_length=1, max_length=128)
    bucket: str = Field(min_length=1, max_length=255)
    object_key: str
    version_id: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024 * 1024)
    kind: ArtifactKind
    owner: ArtifactOwner
    content_type: str = Field(min_length=1, max_length=255)
    created_at: datetime
    expires_at: datetime | None = None
    display_filename: str | None = Field(default=None, max_length=255)

    @field_validator("object_key")
    @classmethod
    def validate_object_key(cls, value: str) -> str:
        if _OBJECT_KEY.fullmatch(value) is None:
            raise ValueError("artifact object key must be system-generated")
        return value

    @field_validator("created_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("artifact timestamp must be timezone-aware")
        return value

    @field_validator("display_filename")
    @classmethod
    def validate_display_filename(cls, value: str | None) -> str | None:
        return ArtifactPutRequest.validate_display_filename(value)


class ArtifactManifestMember(StrictFrozenModel):
    member_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
    artifact: ArtifactObjectVersion


class ArtifactManifest(StrictFrozenModel):
    manifest_id: str = Field(min_length=1, max_length=128)
    owner: ArtifactOwner
    members: tuple[ArtifactManifestMember, ...] = Field(min_length=1, max_length=10_000)
    created_at: datetime

    @model_validator(mode="after")
    def validate_members(self) -> Self:
        member_ids = [member.member_id for member in self.members]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("artifact manifest contains duplicate member ids")
        identities = [
            (
                member.artifact.bucket,
                member.artifact.object_key,
                member.artifact.version_id,
            )
            for member in self.members
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("artifact manifest contains duplicate exact members")
        if any(member.artifact.owner != self.owner for member in self.members):
            raise ValueError("artifact manifest member owner does not match")
        if self.created_at.utcoffset() is None:
            raise ValueError("artifact manifest timestamp must be timezone-aware")
        return self


class ArtifactVisibility(StrEnum):
    INVISIBLE = "invisible"
    VISIBLE = "visible"
    EXPIRED = "expired"
    CORRUPT = "corrupt"


class ArtifactOwnerBinding(StrictFrozenModel):
    owner: ArtifactOwner
    manifest: ArtifactObjectVersion
    visibility: ArtifactVisibility
    visible_at: datetime | None = None
    result_available: bool = False

    @model_validator(mode="after")
    def validate_visible_binding(self) -> Self:
        if self.manifest.kind is not ArtifactKind.ARTIFACT_MANIFEST:
            raise ValueError("owner binding requires an artifact manifest")
        if self.manifest.owner != self.owner:
            raise ValueError("owner binding manifest owner does not match")
        if self.visibility is ArtifactVisibility.VISIBLE:
            if self.visible_at is None or not self.result_available:
                raise ValueError("visible owner requires timestamp and available result")
        elif self.result_available:
            raise ValueError("non-visible owner cannot expose a result")
        return self


class BoundArtifactManifest(StrictFrozenModel):
    binding: ArtifactOwnerBinding
    manifest: ArtifactManifest

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if self.binding.owner != self.manifest.owner:
            raise ValueError("bound artifact manifest owner does not match")
        return self


__all__ = [
    "ArtifactKind",
    "ArtifactManifest",
    "ArtifactManifestMember",
    "ArtifactObjectVersion",
    "ArtifactOwner",
    "ArtifactOwnerBinding",
    "ArtifactPutRequest",
    "ArtifactVisibility",
    "BoundArtifactManifest",
]
