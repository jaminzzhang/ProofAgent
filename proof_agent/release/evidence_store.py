from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
import re

from proof_agent.capabilities.artifacts import ArtifactStoreError
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactObjectVersion,
    ArtifactOwner,
    ArtifactPutRequest,
)
from proof_agent.contracts.ports.artifacts import ArtifactStore
from proof_agent.release.contracts import EvidenceRef, ProductionCandidateBinding
from proof_agent.release.attestation import EvidenceAttestationEnvelope
from proof_agent.release.digests import (
    build_content_addressed_uri,
    candidate_binding_sha256,
    digest_ref,
    reject_duplicate_json_keys,
)
from proof_agent.release.verifier import ArtifactUnavailableError


@dataclass(frozen=True, slots=True)
class StoredReleaseEvidence:
    evidence: EvidenceRef
    artifact: ArtifactObjectVersion


def persist_release_evidence(
    *,
    store: ArtifactStore,
    release_id: str,
    candidate: ProductionCandidateBinding,
    gate_id: str,
    evidence_id: str,
    artifact_name: str,
    kind: str,
    content: bytes,
    produced_at: datetime,
    expires_at: datetime | None = None,
) -> StoredReleaseEvidence:
    """Persist one evidence payload through the existing exact-version store."""

    if not content:
        raise ValueError("release evidence content must not be empty")
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", release_id) is None:
        raise ValueError("release evidence release_id is invalid")
    if produced_at.tzinfo is None or produced_at.utcoffset() is None:
        raise ValueError("release evidence produced_at must be timezone-aware")
    binding = candidate_binding_sha256(candidate)
    digest = digest_ref(content)
    artifact = store.put_immutable(
        ArtifactPutRequest(
            kind=ArtifactKind.RELEASE_EVIDENCE,
            owner=ArtifactOwner(
                owner_type="release",
                owner_id=release_id,
            ),
            content_type="application/json",
            expected_sha256=digest.sha256,
            expected_size_bytes=digest.length,
            display_filename=artifact_name,
            expires_at=expires_at,
        ),
        BytesIO(content),
    )
    if artifact.sha256 != digest.sha256 or artifact.size_bytes != digest.length:
        raise ArtifactStoreError("stored release evidence does not match its exact reference")
    return StoredReleaseEvidence(
        evidence=EvidenceRef(
            evidence_id=evidence_id,
            kind=kind,
            uri=build_content_addressed_uri(digest.sha256),
            digest=digest,
            candidate_binding_sha256=binding,
            produced_at=produced_at,
            expires_at=expires_at,
        ),
        artifact=artifact,
    )


def persist_release_evidence_attestation(
    *,
    store: ArtifactStore,
    release_id: str,
    evidence: EvidenceRef,
    envelope: bytes,
) -> ArtifactObjectVersion:
    """Persist one validated detached envelope as an exact release artifact."""

    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", release_id) is None:
        raise ValueError("release evidence release_id is invalid")
    reject_duplicate_json_keys(envelope)
    parsed = EvidenceAttestationEnvelope.model_validate_json(envelope)
    if (
        parsed.evidence_id != evidence.evidence_id
        or parsed.artifact_sha256 != evidence.digest.sha256
    ):
        raise ValueError("release evidence attestation does not match its EvidenceRef")
    digest = digest_ref(envelope)
    return store.put_immutable(
        ArtifactPutRequest(
            kind=ArtifactKind.RELEASE_ATTESTATION,
            owner=ArtifactOwner(owner_type="release", owner_id=release_id),
            content_type="application/json",
            expected_sha256=digest.sha256,
            expected_size_bytes=digest.length,
            display_filename=f"{evidence.digest.sha256}.attestation.json",
            expires_at=evidence.expires_at,
        ),
        BytesIO(envelope),
    )


class ArtifactStoreEvidenceReader:
    """Resolve content-addressed EvidenceRefs to pinned Artifact Store versions."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        exact_versions: Mapping[str, ArtifactObjectVersion],
    ) -> None:
        self._store = store
        self._exact_versions = dict(exact_versions)

    def read(self, evidence: EvidenceRef) -> bytes:
        try:
            ref = self._exact_versions[evidence.evidence_id]
            if ref.sha256 != evidence.digest.sha256 or ref.size_bytes != evidence.digest.length:
                raise ArtifactUnavailableError("evidence exact version does not match manifest")
            if self._store.head_exact(ref) != ref:
                raise ArtifactUnavailableError("evidence exact version is unavailable")
            with self._store.open_exact(ref) as stream:
                content = stream.read(ref.size_bytes + 1)
        except ArtifactUnavailableError:
            raise
        except (KeyError, ArtifactStoreError, OSError) as exc:
            raise ArtifactUnavailableError("evidence exact version is unavailable") from exc
        if type(content) is not bytes:
            raise ArtifactUnavailableError("evidence exact version returned non-bytes content")
        return content


__all__ = [
    "ArtifactStoreEvidenceReader",
    "StoredReleaseEvidence",
    "persist_release_evidence",
    "persist_release_evidence_attestation",
]
