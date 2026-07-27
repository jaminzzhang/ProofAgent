from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactObjectVersion


_ARTIFACT_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_RELEASE_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"


class ReleaseLifecycleState(StrEnum):
    PREPARING = "PREPARING"
    FINALIZED = "FINALIZED"


class ReleaseBundleMemberRole(StrEnum):
    RELEASE_MANIFEST = "release_manifest"
    READINESS_REPORT = "readiness_report"
    CLOSURE_AUDIT = "closure_audit"
    EVIDENCE = "evidence"
    SBOM = "sbom"
    PROVENANCE = "provenance"


_ROLE_KINDS: dict[ReleaseBundleMemberRole, frozenset[ArtifactKind]] = {
    ReleaseBundleMemberRole.RELEASE_MANIFEST: frozenset({ArtifactKind.RELEASE_MANIFEST}),
    ReleaseBundleMemberRole.READINESS_REPORT: frozenset({ArtifactKind.HTML_REPORT}),
    ReleaseBundleMemberRole.CLOSURE_AUDIT: frozenset(
        {ArtifactKind.RELEASE_CLOSURE_AUDIT}
    ),
    ReleaseBundleMemberRole.EVIDENCE: frozenset({ArtifactKind.EVALUATION_EVIDENCE}),
    ReleaseBundleMemberRole.SBOM: frozenset(
        {ArtifactKind.SOFTWARE_BILL_OF_MATERIALS}
    ),
    ReleaseBundleMemberRole.PROVENANCE: frozenset({ArtifactKind.BUILD_PROVENANCE}),
}


class ReleaseTrustIdentity(StrictFrozenModel):
    protocol_id: str = Field(min_length=1, max_length=128)
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=1, max_length=512)


class ReleaseBundleIndexMember(StrictFrozenModel):
    artifact_name: str = Field(pattern=_ARTIFACT_NAME_PATTERN)
    role: ReleaseBundleMemberRole
    artifact: ArtifactObjectVersion

    @model_validator(mode="after")
    def validate_member(self) -> Self:
        if self.artifact_name in {".", ".."}:
            raise ValueError("release artifact name is invalid")
        if self.artifact_name in {
            "release-bundle-index.json",
            "release-bundle-index.json.attestation",
        }:
            raise ValueError("Bundle Index bootstrap artifacts cannot index themselves")
        if self.artifact.kind not in _ROLE_KINDS[self.role]:
            raise ValueError("release artifact kind does not match its Bundle Index role")
        fixed_name = {
            ReleaseBundleMemberRole.RELEASE_MANIFEST: "release-gate-manifest.json",
            ReleaseBundleMemberRole.READINESS_REPORT: "release-readiness-report.html",
        }.get(self.role)
        if fixed_name is not None and self.artifact_name != fixed_name:
            raise ValueError("release artifact name does not match its fixed role")
        if self.artifact.display_filename != self.artifact_name:
            raise ValueError("release artifact filename does not match its exact reference")
        return self


class ReleaseBundleIndex(StrictFrozenModel):
    schema_version: Literal["proofagent.release-bundle-index.v1"]
    release_id: str = Field(pattern=_RELEASE_ID_PATTERN)
    candidate_binding_sha256: str = Field(pattern=_SHA256_PATTERN)
    release_manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    members: tuple[ReleaseBundleIndexMember, ...] = Field(min_length=1, max_length=10_000)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_index(self) -> Self:
        names = tuple(member.artifact_name for member in self.members)
        if len(names) != len(set(names)):
            raise ValueError("release Bundle Index artifact names must be unique")
        exact_objects = tuple(
            (
                member.artifact.bucket,
                member.artifact.object_key,
                member.artifact.version_id,
            )
            for member in self.members
        )
        if len(exact_objects) != len(set(exact_objects)):
            raise ValueError("release Bundle Index exact objects must be unique")
        if any(
            member.artifact.owner.owner_type != "release"
            or member.artifact.owner.owner_id != self.release_id
            for member in self.members
        ):
            raise ValueError("release Bundle Index member owner does not match release")
        manifests = tuple(
            member
            for member in self.members
            if member.role is ReleaseBundleMemberRole.RELEASE_MANIFEST
        )
        if len(manifests) != 1:
            raise ValueError("release Bundle Index requires exactly one Release Gate Manifest")
        if manifests[0].artifact.sha256 != self.release_manifest_sha256:
            raise ValueError("release Bundle Index manifest digest does not match")
        return self

    def member(self, artifact_name: str) -> ReleaseBundleIndexMember | None:
        return next(
            (member for member in self.members if member.artifact_name == artifact_name),
            None,
        )


class ReleaseFinalization(StrictFrozenModel):
    candidate_binding_sha256: str = Field(pattern=_SHA256_PATTERN)
    release_manifest: ArtifactObjectVersion
    bundle_index: ArtifactObjectVersion
    detached_attestation: ArtifactObjectVersion
    trust_identity: ReleaseTrustIdentity
    finalized_at: AwareDatetime


class ReleaseRegistryRecord(StrictFrozenModel):
    schema_version: Literal["proofagent.release-registry.v1"]
    release_id: str = Field(pattern=_RELEASE_ID_PATTERN)
    state: ReleaseLifecycleState
    candidate_binding_sha256: str = Field(pattern=_SHA256_PATTERN)
    release_manifest: ArtifactObjectVersion
    created_at: AwareDatetime
    created_by: str = Field(min_length=1, max_length=512)
    finalization: ReleaseFinalization | None = None

    @field_validator("release_manifest")
    @classmethod
    def validate_release_manifest_kind(
        cls,
        value: ArtifactObjectVersion,
    ) -> ArtifactObjectVersion:
        if value.kind is not ArtifactKind.RELEASE_MANIFEST:
            raise ValueError("Release Registry requires a Release Gate Manifest")
        return value

    @model_validator(mode="after")
    def validate_state_shape(self) -> Self:
        if self.release_manifest.owner.owner_type != "release":
            raise ValueError("Release Registry artifact owner must be release")
        if self.release_manifest.owner.owner_id != self.release_id:
            raise ValueError("Release Registry artifact owner does not match release")
        if self.state is ReleaseLifecycleState.PREPARING and self.finalization is not None:
            raise ValueError("PREPARING release cannot contain finalization")
        if self.state is ReleaseLifecycleState.FINALIZED and self.finalization is None:
            raise ValueError("FINALIZED release requires finalization")
        return self


def finalize_release_record(
    current: ReleaseRegistryRecord,
    finalization: ReleaseFinalization,
) -> ReleaseRegistryRecord:
    """Apply the sole legal Release Registry transition without persistence effects."""

    if current.state is not ReleaseLifecycleState.PREPARING:
        raise ValueError("only a PREPARING release can be finalized")
    if finalization.candidate_binding_sha256 != current.candidate_binding_sha256:
        raise ValueError("release finalization candidate binding does not match")
    if finalization.release_manifest != current.release_manifest:
        raise ValueError("release finalization manifest does not match")
    if finalization.finalized_at < current.created_at:
        raise ValueError("release finalization cannot precede preparation")
    owner = current.release_manifest.owner
    if (
        finalization.bundle_index.kind is not ArtifactKind.BUNDLE_INDEX
        or finalization.bundle_index.owner != owner
        or finalization.bundle_index.display_filename != "release-bundle-index.json"
    ):
        raise ValueError("release finalization Bundle Index is invalid")
    if (
        finalization.detached_attestation.kind is not ArtifactKind.RELEASE_ATTESTATION
        or finalization.detached_attestation.owner != owner
        or finalization.detached_attestation.display_filename
        != "release-bundle-index.json.attestation"
    ):
        raise ValueError("release finalization detached attestation is invalid")
    payload = current.model_dump(mode="python")
    payload.update(
        state=ReleaseLifecycleState.FINALIZED,
        finalization=finalization,
    )
    return ReleaseRegistryRecord.model_validate(payload)


__all__ = [
    "ReleaseBundleIndex",
    "ReleaseBundleIndexMember",
    "ReleaseBundleMemberRole",
    "ReleaseFinalization",
    "ReleaseLifecycleState",
    "ReleaseRegistryRecord",
    "ReleaseTrustIdentity",
    "finalize_release_record",
]
