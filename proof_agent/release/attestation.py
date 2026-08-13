from __future__ import annotations

import base64
import binascii
import hashlib
import os
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, ValidationError, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.release_registry import ReleaseTrustIdentity
from proof_agent.release.contracts import EvidenceRef, GateResult
from proof_agent.release.digests import (
    canonical_json_bytes,
    gate_result_sha256,
    reject_duplicate_json_keys,
    sha256_hex,
)
from proof_agent.release.verifier import (
    AttestationUnavailableError,
    VerifiedAttestationClaims,
)


_MAX_TRUST_POLICY_BYTES = 1024 * 1024
_MAX_EVIDENCE_ATTESTATION_BYTES = 64 * 1024


class EvidenceAttestationEnvelope(StrictFrozenModel):
    schema_version: Literal["proofagent.release-evidence-attestation.v1"]
    protocol_id: Literal["ed25519-sha256-v1"]
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=1, max_length=512)
    evidence_id: str = Field(min_length=1, max_length=512)
    gate_id: str = Field(min_length=1, max_length=128)
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_base64: str = Field(min_length=1, max_length=1024)


class EvidenceAttestationTrustEntry(StrictFrozenModel):
    protocol_id: Literal["ed25519-sha256-v1"]
    issuer: str = Field(min_length=1, max_length=2048)
    subject: str = Field(min_length=1, max_length=2048)
    key_id: str = Field(min_length=1, max_length=512)
    public_key_base64: str = Field(min_length=1, max_length=256)


class EvidenceAttestationTrustPolicy(StrictFrozenModel):
    schema_version: Literal["proofagent.release-evidence-trust.v1"]
    identities: tuple[EvidenceAttestationTrustEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_key_ids(self) -> Self:
        key_ids = tuple(identity.key_id for identity in self.identities)
        if len(key_ids) != len(set(key_ids)):
            raise ValueError("release evidence trust key ids must be unique")
        return self


def evidence_attestation_signature_payload(
    envelope: EvidenceAttestationEnvelope | Mapping[str, object],
) -> bytes:
    values = (
        envelope.model_dump(mode="json")
        if isinstance(envelope, EvidenceAttestationEnvelope)
        else dict(envelope)
    )
    values.pop("signature_base64", None)
    digest = hashlib.sha256(canonical_json_bytes(values)).digest()
    return b"proofagent.release-evidence-attestation.v1\0" + digest


def build_evidence_attestation(
    *,
    result: GateResult,
    evidence: EvidenceRef,
    artifact: bytes,
    trust_identity: ReleaseTrustIdentity,
    signer: Callable[[bytes], bytes],
) -> bytes:
    """Build a detached envelope using a caller-owned workload/KMS signer."""

    if evidence not in result.evidence:
        raise ValueError("attested evidence must belong to the Gate Result")
    unsigned: dict[str, object] = {
        "schema_version": "proofagent.release-evidence-attestation.v1",
        "protocol_id": trust_identity.protocol_id,
        "issuer": trust_identity.issuer,
        "subject": trust_identity.subject,
        "key_id": trust_identity.key_id,
        "evidence_id": evidence.evidence_id,
        "gate_id": result.gate_id,
        "artifact_sha256": sha256_hex(artifact),
        "candidate_binding_sha256": result.candidate_binding_sha256,
        "gate_result_sha256": gate_result_sha256(result),
    }
    payload = evidence_attestation_signature_payload(unsigned)
    signature = signer(payload)
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError("evidence attestation signer returned an invalid signature")
    envelope = EvidenceAttestationEnvelope.model_validate(
        {
            **unsigned,
            "signature_base64": base64.b64encode(signature).decode("ascii"),
        }
    )
    return canonical_json_bytes(envelope)


class Ed25519EvidenceAttestationVerifier:
    """Verify detached evidence claims against deployment-owned trust identities."""

    def __init__(
        self,
        *,
        public_keys: Mapping[str, bytes],
        trust_identities: Mapping[str, ReleaseTrustIdentity],
        envelopes: Mapping[str, bytes],
    ) -> None:
        if not public_keys or set(public_keys) != set(trust_identities):
            raise ValueError("evidence trust keys and identities must be non-empty and aligned")
        parsed: dict[str, Ed25519PublicKey] = {}
        for key_id, raw in public_keys.items():
            identity = trust_identities[key_id]
            if key_id != identity.key_id or len(raw) != 32:
                raise ValueError("evidence attestation trust configuration is invalid")
            parsed[key_id] = Ed25519PublicKey.from_public_bytes(raw)
        self._public_keys = parsed
        self._trust_identities = dict(trust_identities)
        self._envelopes = dict(envelopes)

    def verify(
        self,
        *,
        result: GateResult,
        evidence: EvidenceRef,
        artifact: bytes,
        candidate_binding_sha256: str,
    ) -> VerifiedAttestationClaims | None:
        raw = self._envelopes.get(evidence.evidence_id)
        if raw is None:
            raise AttestationUnavailableError("evidence attestation is unavailable")
        try:
            reject_duplicate_json_keys(raw)
            envelope = EvidenceAttestationEnvelope.model_validate_json(raw)
            identity = self._trust_identities.get(envelope.key_id)
            public_key = self._public_keys.get(envelope.key_id)
            if identity is None or public_key is None:
                return None
            if (
                envelope.protocol_id != identity.protocol_id
                or envelope.issuer != identity.issuer
                or envelope.subject != identity.subject
                or envelope.key_id != identity.key_id
                or envelope.evidence_id != evidence.evidence_id
                or envelope.gate_id != result.gate_id
                or envelope.artifact_sha256 != sha256_hex(artifact)
                or envelope.candidate_binding_sha256 != candidate_binding_sha256
                or envelope.candidate_binding_sha256
                != result.candidate_binding_sha256
                or envelope.gate_result_sha256 != gate_result_sha256(result)
            ):
                return None
            signature = base64.b64decode(envelope.signature_base64, validate=True)
            if len(signature) != 64:
                return None
            public_key.verify(signature, evidence_attestation_signature_payload(envelope))
        except (
            ValidationError,
            ValueError,
            UnicodeDecodeError,
            binascii.Error,
            InvalidSignature,
        ):
            return None
        return VerifiedAttestationClaims(
            artifact_sha256=envelope.artifact_sha256,
            candidate_binding_sha256=envelope.candidate_binding_sha256,
            gate_result_sha256=envelope.gate_result_sha256,
        )


def load_evidence_attestation_verifier(
    *,
    trust_policy: bytes,
    attestation_root: Path,
    evidence: tuple[EvidenceRef, ...],
) -> Ed25519EvidenceAttestationVerifier:
    """Load deployment-owned public trust and detached envelopes from bounded files."""

    if len(trust_policy) > _MAX_TRUST_POLICY_BYTES:
        raise ValueError("release evidence trust policy is too large")
    reject_duplicate_json_keys(trust_policy)
    policy = EvidenceAttestationTrustPolicy.model_validate_json(trust_policy)
    public_keys: dict[str, bytes] = {}
    identities: dict[str, ReleaseTrustIdentity] = {}
    try:
        for entry in policy.identities:
            public_key = base64.b64decode(entry.public_key_base64, validate=True)
            if len(public_key) != 32:
                raise ValueError("release evidence public key must contain 32 bytes")
            public_keys[entry.key_id] = public_key
            identities[entry.key_id] = ReleaseTrustIdentity(
                protocol_id=entry.protocol_id,
                issuer=entry.issuer,
                subject=entry.subject,
                key_id=entry.key_id,
            )
    except binascii.Error as exc:
        raise ValueError("release evidence public key is not canonical base64") from exc

    if not attestation_root.is_dir():
        raise ValueError("release evidence attestation root is invalid")
    confined_root = attestation_root.resolve(strict=True)
    envelopes: dict[str, bytes] = {}
    for item in evidence:
        filename = f"{item.digest.sha256}.attestation.json"
        envelopes[item.evidence_id] = _read_confined_attestation(
            confined_root,
            filename,
        )
    return Ed25519EvidenceAttestationVerifier(
        public_keys=public_keys,
        trust_identities=identities,
        envelopes=envelopes,
    )


def _read_confined_attestation(root: Path, filename: str) -> bytes:
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        root_fd = -1
        artifact_fd = -1
        try:
            root_fd = os.open(
                root,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
            )
            artifact_fd = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=root_fd,
            )
            metadata = os.fstat(artifact_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("release evidence attestation must be a regular file")
            if metadata.st_size > _MAX_EVIDENCE_ATTESTATION_BYTES:
                raise ValueError("release evidence attestation is too large")
            content = os.read(artifact_fd, _MAX_EVIDENCE_ATTESTATION_BYTES + 1)
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError(
                "release evidence attestation is unavailable or is a symlink"
            ) from exc
        finally:
            if artifact_fd >= 0:
                os.close(artifact_fd)
            if root_fd >= 0:
                os.close(root_fd)
        return content

    path = root / filename
    if path.is_symlink():
        raise ValueError("release evidence attestation must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        metadata = path.stat()
    except (OSError, ValueError) as exc:
        raise ValueError("release evidence attestation escaped its root") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("release evidence attestation must be a regular file")
    if metadata.st_size > _MAX_EVIDENCE_ATTESTATION_BYTES:
        raise ValueError("release evidence attestation is too large")
    return path.read_bytes()


__all__ = [
    "Ed25519EvidenceAttestationVerifier",
    "EvidenceAttestationEnvelope",
    "EvidenceAttestationTrustEntry",
    "EvidenceAttestationTrustPolicy",
    "build_evidence_attestation",
    "evidence_attestation_signature_payload",
    "load_evidence_attestation_verifier",
]
