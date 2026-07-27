from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import base64
import binascii
import hashlib
from pathlib import Path
import re
from typing import Literal, Mapping, Protocol, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import ValidationError
from pydantic import Field
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from proof_agent.capabilities.artifacts.materialization import MaterializationError
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    Permission,
)
from proof_agent.contracts.artifacts import ArtifactObjectVersion
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.ports.audit import AuditRepository
from proof_agent.contracts.ports.release_registry import ReleaseRegistryRepository
from proof_agent.contracts.release_registry import (
    ReleaseBundleIndex,
    ReleaseLifecycleState,
    ReleaseRegistryRecord,
    ReleaseTrustIdentity,
)
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import OperatorIdentityContext
from proof_agent.release.digests import reject_duplicate_json_keys


router = APIRouter(prefix="/releases", tags=["release-bundles"])

_ARTIFACT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_INDEX_NAME = "release-bundle-index.json"
_ATTESTATION_NAME = "release-bundle-index.json.attestation"
_MAX_INDEX_BYTES = 8 * 1024 * 1024
_MAX_ATTESTATION_BYTES = 8 * 1024 * 1024


class ReleaseBundleMaterializer(Protocol):
    def materialize(self, ref: ArtifactObjectVersion) -> Path: ...


class ReleaseBundleAttestationVerifier(Protocol):
    def verify(
        self,
        *,
        index: bytes,
        attestation: bytes,
        trust_identity: ReleaseTrustIdentity,
    ) -> bool: ...


class _ReleaseBundleAttestation(StrictFrozenModel):
    schema_version: Literal["proofagent.release-bundle-attestation.v1"]
    protocol_id: Literal["ed25519-sha256-v1"]
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=1, max_length=512)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_base64: str = Field(min_length=1, max_length=1024)


def release_bundle_signature_payload(index: bytes) -> bytes:
    """Return the domain-separated bytes covered by a release-bundle signature."""

    return b"proofagent.release-bundle-index.v1\0" + hashlib.sha256(index).digest()


class Ed25519ReleaseBundleAttestationVerifier:
    """Verify the bounded detached envelope against deployment-owned public keys."""

    def __init__(self, public_keys: Mapping[str, bytes]) -> None:
        if not public_keys:
            raise ValueError("at least one release attestation public key is required")
        parsed: dict[str, Ed25519PublicKey] = {}
        for key_id, raw in public_keys.items():
            if not key_id or len(key_id) > 512 or len(raw) != 32:
                raise ValueError("release attestation public key configuration is invalid")
            parsed[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        self._public_keys = parsed

    def verify(
        self,
        *,
        index: bytes,
        attestation: bytes,
        trust_identity: ReleaseTrustIdentity,
    ) -> bool:
        try:
            reject_duplicate_json_keys(attestation)
            envelope = _ReleaseBundleAttestation.model_validate_json(attestation)
            if (
                trust_identity.protocol_id != envelope.protocol_id
                or trust_identity.issuer != envelope.issuer
                or trust_identity.subject != envelope.subject
                or trust_identity.key_id != envelope.key_id
                or envelope.artifact_sha256 != hashlib.sha256(index).hexdigest()
            ):
                return False
            public_key = self._public_keys.get(envelope.key_id)
            if public_key is None:
                return False
            signature = base64.b64decode(envelope.signature_base64, validate=True)
            if len(signature) != 64:
                return False
            public_key.verify(signature, release_bundle_signature_payload(index))
        except (
            ValidationError,
            ValueError,
            UnicodeDecodeError,
            binascii.Error,
            InvalidSignature,
        ):
            return False
        return True


@router.get("")
def list_releases(
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, object]:
    _require_export_permission(request, identity, release_id="registry", artifact_name="list")
    releases: list[dict[str, object]] = []
    for record in _repository(request).list():
        artifact_names: tuple[str, ...] = ()
        bundle_available = False
        if record.state is ReleaseLifecycleState.FINALIZED:
            try:
                index = _verified_index(request, record)
            except HTTPException:
                pass
            else:
                repository = _repository(request)
                now = _now(request)
                members_visible = all(
                    repository.resolve_exact_visible(member.artifact, now=now)
                    == member.artifact
                    for member in index.members
                )
                if members_visible:
                    artifact_names = (
                        _INDEX_NAME,
                        _ATTESTATION_NAME,
                        *(member.artifact_name for member in index.members),
                    )
                    bundle_available = True
        releases.append(
            {
                "release_id": record.release_id,
                "state": record.state.value,
                "candidate_binding_sha256": record.candidate_binding_sha256,
                "created_at": record.created_at.isoformat(),
                "finalized_at": (
                    record.finalization.finalized_at.isoformat()
                    if record.finalization is not None
                    else None
                ),
                "bundle_available": bundle_available,
                "artifact_names": artifact_names,
            }
        )
    return {"releases": releases}


@router.get("/{release_id}/bundle/{artifact_name}")
def download_release_bundle_artifact(
    release_id: str,
    artifact_name: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> FileResponse:
    if not _valid_name(release_id) or not _valid_name(artifact_name):
        raise HTTPException(status_code=404, detail="release_artifact_not_found")
    _require_export_permission(
        request,
        identity,
        release_id=release_id,
        artifact_name=artifact_name,
    )
    try:
        record = _repository(request).get(release_id)
        if record is None:
            raise HTTPException(status_code=404, detail="release_not_found")
        if record.state is not ReleaseLifecycleState.FINALIZED:
            raise HTTPException(status_code=409, detail="release_not_finalized")
        index = _verified_index(request, record)
        assert record.finalization is not None
        if artifact_name == _INDEX_NAME:
            ref = record.finalization.bundle_index
        elif artifact_name == _ATTESTATION_NAME:
            ref = record.finalization.detached_attestation
        else:
            member = index.member(artifact_name)
            if member is None:
                raise HTTPException(status_code=404, detail="release_artifact_not_found")
            ref = member.artifact
        exact = _repository(request).resolve_exact_visible(ref, now=_now(request))
        if exact != ref:
            raise HTTPException(status_code=404, detail="release_artifact_not_available")
        cache_path = _materialize(request, exact)
        _verify_cache_file(cache_path, exact)
        _append_audit(
            request,
            identity=identity,
            release_id=release_id,
            artifact_name=artifact_name,
            object_id=exact.object_id,
            outcome=AuditOutcome.SUCCEEDED,
        )
    except HTTPException as exc:
        _append_audit(
            request,
            identity=identity,
            release_id=release_id,
            artifact_name=artifact_name,
            object_id=None,
            outcome=AuditOutcome.FAILED,
            reason_code=str(exc.detail),
        )
        raise
    except (MaterializationError, OSError) as exc:
        _append_audit(
            request,
            identity=identity,
            release_id=release_id,
            artifact_name=artifact_name,
            object_id=None,
            outcome=AuditOutcome.FAILED,
            reason_code="release_artifact_verification_failed",
        )
        raise HTTPException(
            status_code=409,
            detail="release_artifact_verification_failed",
        ) from exc
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        cache_path,
        media_type=exact.content_type,
        filename=artifact_name,
        headers=headers,
    )


def _verified_index(request: Request, record: ReleaseRegistryRecord) -> ReleaseBundleIndex:
    finalization = record.finalization
    if finalization is None:
        raise HTTPException(status_code=409, detail="release_not_finalized")
    repository = _repository(request)
    now = _now(request)
    index_ref = repository.resolve_exact_visible(finalization.bundle_index, now=now)
    attestation_ref = repository.resolve_exact_visible(
        finalization.detached_attestation,
        now=now,
    )
    if index_ref != finalization.bundle_index or attestation_ref != finalization.detached_attestation:
        raise HTTPException(status_code=404, detail="release_bundle_bootstrap_not_available")
    if index_ref.size_bytes > _MAX_INDEX_BYTES:
        raise HTTPException(status_code=409, detail="release_bundle_index_too_large")
    if attestation_ref.size_bytes > _MAX_ATTESTATION_BYTES:
        raise HTTPException(status_code=409, detail="release_bundle_attestation_too_large")
    try:
        index_path = _materialize(request, index_ref)
        attestation_path = _materialize(request, attestation_ref)
        index_bytes = _read_cache_file(index_path, index_ref)
        attestation_bytes = _read_cache_file(attestation_path, attestation_ref)
        trusted = _attestation_verifier(request).verify(
            index=index_bytes,
            attestation=attestation_bytes,
            trust_identity=finalization.trust_identity,
        )
        if trusted is not True:
            raise HTTPException(
                status_code=409,
                detail="release_bundle_attestation_invalid",
            )
        reject_duplicate_json_keys(index_bytes)
        index = ReleaseBundleIndex.model_validate_json(index_bytes)
    except HTTPException:
        raise
    except (MaterializationError, OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
        raise HTTPException(
            status_code=409,
            detail="release_bundle_verification_failed",
        ) from exc
    if (
        index.release_id != record.release_id
        or index.candidate_binding_sha256 != record.candidate_binding_sha256
        or index.release_manifest_sha256 != record.release_manifest.sha256
    ):
        raise HTTPException(status_code=409, detail="release_bundle_binding_mismatch")
    manifest = index.member("release-gate-manifest.json")
    if manifest is None or manifest.artifact != record.release_manifest:
        raise HTTPException(status_code=409, detail="release_bundle_manifest_mismatch")
    return index


def _read_cache_file(path: Path, ref: ArtifactObjectVersion) -> bytes:
    _verify_cache_file(path, ref)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise MaterializationError("verified artifact cache became unavailable") from exc
    if len(content) != ref.size_bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
        raise MaterializationError("verified artifact cache digest changed")
    return content


def _verify_cache_file(path: Path, ref: ArtifactObjectVersion) -> None:
    try:
        if not path.is_file() or path.stat().st_size != ref.size_bytes:
            raise MaterializationError("verified artifact cache length changed")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != ref.sha256:
            raise MaterializationError("verified artifact cache digest changed")
    except OSError as exc:
        raise MaterializationError("verified artifact cache is unavailable") from exc


def _valid_name(value: str) -> bool:
    return value not in {".", ".."} and _ARTIFACT_NAME.fullmatch(value) is not None


def _require_export_permission(
    request: Request,
    identity: OperatorIdentityContext,
    *,
    release_id: str,
    artifact_name: str,
) -> None:
    if Permission.AUDIT_EXPORT in identity.permissions:
        return
    _append_audit(
        request,
        identity=identity,
        release_id=release_id,
        artifact_name=artifact_name,
        object_id=None,
        outcome=AuditOutcome.DENIED,
        reason_code="audit_export_permission_required",
    )
    raise HTTPException(status_code=403, detail="audit_export_permission_required")


def _append_audit(
    request: Request,
    *,
    identity: OperatorIdentityContext,
    release_id: str,
    artifact_name: str,
    object_id: str | None,
    outcome: AuditOutcome,
    reason_code: str | None = None,
) -> None:
    repository = getattr(request.app.state, "release_bundle_audit_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="release_bundle_audit_unavailable")
    session = getattr(request.state, "session_resolution", None)
    metadata: dict[str, object] = {"artifact_name": artifact_name}
    if object_id is not None:
        metadata["object_id"] = object_id
    if reason_code is not None:
        metadata["reason_code"] = reason_code
    cast(AuditRepository, repository).append(
        AuditMetadataRecord(
            audit_id=str(uuid4()),
            category=AuditCategory.OPERATIONS,
            event_type="release_bundle.download",
            outcome=outcome,
            actor=AuditActorFacts(
                subject=identity.operator_id,
                identity_provider=(
                    "oidc"
                    if getattr(request.app.state, "proof_agent_mode", "development")
                    == "production"
                    else "local"
                ),
                session_id=str(getattr(session, "session_id", "unavailable")),
                permissions=tuple(sorted(item.value for item in identity.permissions)),
            ),
            occurred_at=_now(request).isoformat(),
            target_type="release",
            target_id=release_id,
            metadata=metadata,
        )
    )


def _repository(request: Request) -> ReleaseRegistryRepository:
    repository = getattr(request.app.state, "release_registry_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="release_registry_unavailable")
    return cast(ReleaseRegistryRepository, repository)


def _materialize(request: Request, ref: ArtifactObjectVersion) -> Path:
    materializer = getattr(request.app.state, "release_bundle_materializer", None)
    if materializer is None:
        raise HTTPException(status_code=503, detail="release_bundle_materializer_unavailable")
    return cast(ReleaseBundleMaterializer, materializer).materialize(ref)


def _attestation_verifier(request: Request) -> ReleaseBundleAttestationVerifier:
    verifier = getattr(request.app.state, "release_bundle_attestation_verifier", None)
    if verifier is None:
        raise HTTPException(status_code=503, detail="release_bundle_verifier_unavailable")
    return cast(ReleaseBundleAttestationVerifier, verifier)


def _now(request: Request) -> datetime:
    clock = getattr(request.app.state, "release_bundle_clock", None)
    if clock is None:
        return datetime.now(UTC)
    return cast(Callable[[], datetime], clock)()


__all__ = [
    "Ed25519ReleaseBundleAttestationVerifier",
    "ReleaseBundleAttestationVerifier",
    "ReleaseBundleMaterializer",
    "release_bundle_signature_payload",
    "router",
]
