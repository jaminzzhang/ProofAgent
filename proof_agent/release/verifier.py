from __future__ import annotations

import math
import os
import re
import stat
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import AwareDatetime

from proof_agent.release.contracts import (
    EvidenceRef,
    GateResult,
    ReleaseGateManifest,
    Sha256,
    StrictFrozenModel,
)
from proof_agent.release.digests import (
    candidate_binding_sha256,
    digest_ref,
    gate_result_sha256,
    parse_content_addressed_uri,
    sha256_hex,
)
from proof_agent.release.profile import (
    INITIAL_PRIVATE_PILOT_PROFILE,
    EvidenceRule,
    GateRule,
    MetricRule,
)


_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DEPLOYMENT_WINDOW = timedelta(hours=24)


class ReleaseDecision(StrictFrozenModel):
    decision: Literal["GO", "NO-GO"]
    candidate_binding_sha256: Sha256
    checked_at: AwareDatetime
    blocker_codes: tuple[str, ...]


class VerifiedAttestationClaims(StrictFrozenModel):
    artifact_sha256: Sha256
    candidate_binding_sha256: Sha256
    gate_result_sha256: Sha256


class ArtifactUnavailableError(OSError):
    """An expected artifact lookup or read failure."""


class AttestationUnavailableError(RuntimeError):
    """The configured cryptographic attestation verifier is unavailable."""


class AttestationVerificationError(RuntimeError):
    """The attestation verifier could not verify a supplied envelope."""


class VerifierInternalError(RuntimeError):
    """An unexpected verifier or adapter defect that must not become evidence state."""


class ArtifactReader(Protocol):
    def read(self, evidence: EvidenceRef) -> bytes: ...


class AttestationVerifier(Protocol):
    def verify(
        self,
        *,
        result: GateResult,
        evidence: EvidenceRef,
        artifact: bytes,
        candidate_binding_sha256: Sha256,
    ) -> VerifiedAttestationClaims | None: ...


class EvidenceRootArtifactReader:
    """Read immutable evidence artifacts from a confined content-addressed root."""

    def __init__(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            raise ValueError("evidence root must be an existing directory")
        self._root = root.resolve(strict=True)

    def read(self, evidence: EvidenceRef) -> bytes:
        artifact_sha256 = parse_content_addressed_uri(evidence.uri)
        if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
            return self._read_posix(artifact_sha256)
        return self._read_fallback(artifact_sha256)

    def _read_posix(self, artifact_sha256: Sha256) -> bytes:
        root_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0)
        )
        artifact_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        root_fd = -1
        artifact_fd = -1
        try:
            root_fd = os.open(self._root, root_flags)
            artifact_fd = os.open(artifact_sha256, artifact_flags, dir_fd=root_fd)
            if not stat.S_ISREG(os.fstat(artifact_fd).st_mode):
                raise ArtifactUnavailableError("evidence artifact must be a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(artifact_fd, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        except ArtifactUnavailableError:
            raise
        except OSError as exc:
            raise ArtifactUnavailableError(
                "evidence artifact is unavailable or is a symlink"
            ) from exc
        finally:
            if artifact_fd >= 0:
                os.close(artifact_fd)
            if root_fd >= 0:
                os.close(root_fd)

    def _read_fallback(self, artifact_sha256: Sha256) -> bytes:
        artifact_path = self._root / artifact_sha256
        if artifact_path.is_symlink():
            raise ArtifactUnavailableError("evidence artifact must not be a symlink")
        try:
            resolved = artifact_path.resolve(strict=True)
            resolved.relative_to(self._root)
        except (OSError, ValueError) as exc:
            raise ArtifactUnavailableError(
                "evidence artifact is unavailable or escapes its root"
            ) from exc
        if not stat.S_ISREG(artifact_path.lstat().st_mode):
            raise ArtifactUnavailableError("evidence artifact must be a regular file")
        try:
            return artifact_path.read_bytes()
        except OSError as exc:
            raise ArtifactUnavailableError("evidence artifact is unavailable") from exc


class UnavailableAttestationVerifier:
    """S0 fail-closed adapter until DSSE and trust-policy verification exists."""

    def verify(
        self,
        *,
        result: GateResult,
        evidence: EvidenceRef,
        artifact: bytes,
        candidate_binding_sha256: Sha256,
    ) -> VerifiedAttestationClaims | None:
        del result, evidence, artifact, candidate_binding_sha256
        raise AttestationUnavailableError(
            "release evidence attestation verification is unavailable"
        )


def verify_release_manifest(
    manifest: ReleaseGateManifest,
    *,
    checked_at: datetime,
    artifact_reader: ArtifactReader,
    attestation_verifier: AttestationVerifier,
) -> ReleaseDecision:
    """Verify a release manifest deterministically without clocks or network access."""

    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("checked_at must be timezone-aware")

    profile = INITIAL_PRIVATE_PILOT_PROFILE
    binding = candidate_binding_sha256(manifest.candidate)
    blockers: list[str] = []

    packaged_digest = digest_ref(profile.binding_bytes)
    if manifest.candidate.gate_profile.sha256 != packaged_digest.sha256:
        blockers.append("profile.sha256_mismatch")
    if manifest.candidate.gate_profile.length != packaged_digest.length:
        blockers.append("profile.length_mismatch")

    if manifest.generated_at > checked_at:
        blockers.append("manifest.generated_in_future")
    elif checked_at - manifest.generated_at > _DEPLOYMENT_WINDOW:
        blockers.append("deployment.window_expired")

    results_by_gate: dict[str, GateResult] = {}
    gate_counts = Counter(result.gate_id for result in manifest.results)
    for gate_id, count in gate_counts.items():
        if count > 1:
            blockers.append(f"gate.duplicate:{gate_id}")
    for result in manifest.results:
        results_by_gate.setdefault(result.gate_id, result)

    required_gate_ids = set(profile.gate_ids)
    for gate_id in profile.gate_ids:
        if gate_id not in results_by_gate:
            blockers.append(f"gate.missing:{gate_id}")
    for gate_id in results_by_gate:
        if gate_id not in required_gate_ids:
            blockers.append(f"gate.unknown:{gate_id}")

    all_evidence = tuple(evidence for result in manifest.results for evidence in result.evidence)
    _verify_evidence_identity(all_evidence, blockers)

    required_expiries: list[datetime] = []
    for result in manifest.results:
        if result.status != "passed":
            blockers.append(f"gate.status:{result.gate_id}:{result.status}")
        result_binding_valid = result.candidate_binding_sha256 == binding
        if not result_binding_valid:
            blockers.append(f"gate.binding_mismatch:{result.gate_id}")
        for reported_blocker in result.blocker_codes:
            blockers.append(f"gate.reported_blocker:{result.gate_id}:{reported_blocker}")

        gate_rule = _gate_rule(result.gate_id)
        if gate_rule is not None:
            _verify_evidence_kinds(result, gate_rule, blockers)
            _verify_metrics(result, gate_rule, manifest, blockers)

        for evidence in result.evidence:
            evidence_rule = _evidence_rule(gate_rule, evidence.kind)
            _verify_evidence_time(
                evidence,
                evidence_rule=evidence_rule,
                generated_at=manifest.generated_at,
                checked_at=checked_at,
                blockers=blockers,
                required_expiries=required_expiries,
            )
            evidence_binding_valid = evidence.candidate_binding_sha256 == binding
            if not evidence_binding_valid:
                blockers.append(f"evidence.binding_mismatch:{evidence.evidence_id}")
            _verify_evidence_artifact(
                result,
                evidence,
                binding=binding,
                bindings_valid=result_binding_valid and evidence_binding_valid,
                artifact_reader=artifact_reader,
                attestation_verifier=attestation_verifier,
                blockers=blockers,
            )

    if required_expiries and checked_at >= min(required_expiries):
        blockers.append("deployment.evidence_window_expired")

    _verify_recovery_deployment_bindings(results_by_gate, blockers)

    blocker_codes = tuple(sorted(set(blockers)))
    return ReleaseDecision(
        decision="GO" if not blocker_codes else "NO-GO",
        candidate_binding_sha256=binding,
        checked_at=checked_at,
        blocker_codes=blocker_codes,
    )


def _gate_rule(gate_id: str) -> GateRule | None:
    return next(
        (rule for rule in INITIAL_PRIVATE_PILOT_PROFILE.gates if rule.gate_id == gate_id),
        None,
    )


def _evidence_rule(gate_rule: GateRule | None, kind: str) -> EvidenceRule | None:
    if gate_rule is None:
        return None
    return next((rule for rule in gate_rule.evidence if rule.kind == kind), None)


def _verify_evidence_identity(
    evidence_items: tuple[EvidenceRef, ...],
    blockers: list[str],
) -> None:
    identities = (
        ("duplicate_id", (evidence.evidence_id for evidence in evidence_items)),
        ("duplicate_uri", (evidence.uri for evidence in evidence_items)),
        ("duplicate_digest", (evidence.digest.sha256 for evidence in evidence_items)),
    )
    for category, values in identities:
        for value, count in Counter(values).items():
            if count > 1:
                blockers.append(f"evidence.{category}:{value}")


def _verify_evidence_kinds(
    result: GateResult,
    gate_rule: GateRule,
    blockers: list[str],
) -> None:
    actual_kinds = tuple(evidence.kind for evidence in result.evidence)
    allowed_kinds = tuple(rule.kind for rule in gate_rule.evidence)
    for kind in allowed_kinds:
        count = actual_kinds.count(kind)
        if count == 0:
            blockers.append(f"evidence.missing:{result.gate_id}:{kind}")
        elif count != 1:
            blockers.append(f"evidence.cardinality:{result.gate_id}:{kind}")
    for kind in actual_kinds:
        if kind not in allowed_kinds:
            blockers.append(f"evidence.kind_unknown:{result.gate_id}:{kind}")


def _verify_evidence_time(
    evidence: EvidenceRef,
    *,
    evidence_rule: EvidenceRule | None,
    generated_at: datetime,
    checked_at: datetime,
    blockers: list[str],
    required_expiries: list[datetime],
) -> None:
    if evidence.produced_at > generated_at:
        blockers.append(f"evidence.produced_in_future:{evidence.evidence_id}")

    expires_at = evidence.expires_at
    if expires_at is not None:
        if expires_at <= evidence.produced_at:
            blockers.append(f"evidence.expiry_not_after_production:{evidence.evidence_id}")
        if checked_at >= expires_at:
            blockers.append(f"evidence.expired:{evidence.evidence_id}")

    if evidence_rule is None:
        return
    if evidence_rule.expiry_required:
        if expires_at is None:
            blockers.append(f"evidence.expiry_missing:{evidence.evidence_id}")
        else:
            required_expiries.append(expires_at)
    if evidence_rule.max_age is None:
        return

    if (
        expires_at is not None
        and expires_at > evidence.produced_at
        and expires_at - evidence.produced_at > evidence_rule.max_age
    ):
        blockers.append(f"evidence.expiry_exceeds_policy:{evidence.evidence_id}")
    if (
        checked_at >= evidence.produced_at
        and checked_at - evidence.produced_at >= evidence_rule.max_age
    ):
        blockers.append(f"evidence.policy_stale:{evidence.evidence_id}")


def _verify_evidence_artifact(
    result: GateResult,
    evidence: EvidenceRef,
    *,
    binding: Sha256,
    bindings_valid: bool,
    artifact_reader: ArtifactReader,
    attestation_verifier: AttestationVerifier,
    blockers: list[str],
) -> None:
    try:
        uri_digest = parse_content_addressed_uri(evidence.uri)
    except ValueError:
        blockers.append(f"evidence.uri_invalid:{evidence.evidence_id}")
        return
    if uri_digest != evidence.digest.sha256:
        blockers.append(f"evidence.uri_digest_mismatch:{evidence.evidence_id}")
        return

    try:
        artifact = artifact_reader.read(evidence)
    except (ArtifactUnavailableError, OSError):
        blockers.append(f"evidence.unavailable:{evidence.evidence_id}")
        return
    except Exception as exc:
        raise VerifierInternalError("unexpected artifact reader failure") from exc

    if type(artifact) is not bytes:
        raise VerifierInternalError("artifact reader returned non-bytes data")

    artifact_valid = True
    if len(artifact) != evidence.digest.length:
        blockers.append(f"evidence.length_mismatch:{evidence.evidence_id}")
        artifact_valid = False
    if sha256_hex(artifact) != evidence.digest.sha256:
        blockers.append(f"evidence.digest_mismatch:{evidence.evidence_id}")
        artifact_valid = False
    if not artifact_valid or not bindings_valid:
        return
    try:
        claims = attestation_verifier.verify(
            result=result,
            evidence=evidence,
            artifact=artifact,
            candidate_binding_sha256=binding,
        )
    except AttestationUnavailableError:
        blockers.append(f"evidence.attestation_unavailable:{evidence.evidence_id}")
        return
    except AttestationVerificationError:
        blockers.append(f"evidence.attestation_error:{evidence.evidence_id}")
        return
    except Exception as exc:
        raise VerifierInternalError("unexpected attestation verifier failure") from exc
    if claims is None:
        blockers.append(f"evidence.attestation_invalid:{evidence.evidence_id}")
        return
    expected_claims = VerifiedAttestationClaims(
        artifact_sha256=sha256_hex(artifact),
        candidate_binding_sha256=binding,
        gate_result_sha256=gate_result_sha256(result),
    )
    if claims != expected_claims:
        blockers.append(f"evidence.attestation_claim_mismatch:{evidence.evidence_id}")


def _verify_metrics(
    result: GateResult,
    gate_rule: GateRule,
    manifest: ReleaseGateManifest,
    blockers: list[str],
) -> None:
    allowed_keys = {rule.key for rule in gate_rule.metrics}
    for key in result.metrics:
        if key not in allowed_keys:
            blockers.append(f"metric.unknown:{result.gate_id}:{key}")
    for rule in gate_rule.metrics:
        if rule.key not in result.metrics:
            blockers.append(f"metric.missing:{result.gate_id}:{rule.key}")
            continue
        value = result.metrics[rule.key]
        if not _metric_type_matches(value, rule):
            blockers.append(f"metric.type_mismatch:{result.gate_id}:{rule.key}")
            continue
        if not _metric_satisfies(value, rule, manifest):
            blockers.append(f"metric.{rule.failure}:{result.gate_id}:{rule.key}")


def _metric_type_matches(value: object, rule: MetricRule) -> bool:
    if rule.kind == "bool":
        return type(value) is bool
    if rule.kind == "int":
        return type(value) is int
    if rule.kind == "number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    return type(value) is str and _LOWER_SHA256.fullmatch(value) is not None


def _metric_satisfies(
    value: object,
    rule: MetricRule,
    manifest: ReleaseGateManifest,
) -> bool:
    if rule.comparison == "format":
        return True
    if rule.comparison == "binding":
        expected = (
            manifest.candidate.migration_set.sha256
            if rule.binding_target == "migration_set"
            else manifest.candidate.deployment_compatibility_manifest.sha256
        )
        return value == expected
    numeric_value = cast("int | float", value)
    if rule.minimum_allowed is not None and numeric_value < rule.minimum_allowed:
        return False
    if rule.maximum_allowed is not None and numeric_value > rule.maximum_allowed:
        return False
    if rule.comparison == "equal":
        return value == rule.expected
    numeric_expected = cast("int | float", rule.expected)
    if rule.comparison == "minimum":
        return numeric_value >= numeric_expected
    return numeric_value <= numeric_expected


def _verify_recovery_deployment_bindings(
    results_by_gate: dict[str, GateResult],
    blockers: list[str],
) -> None:
    recovery = results_by_gate.get("resilience_recovery")
    deployment = results_by_gate.get("deployment")
    if recovery is None or deployment is None:
        return
    for key in ("topology_sha256", "backup_policy_sha256", "migration_set_sha256"):
        recovery_value = recovery.metrics.get(key)
        deployment_value = deployment.metrics.get(key)
        if type(recovery_value) is str and type(deployment_value) is str:
            if recovery_value != deployment_value:
                blockers.append(f"metric.binding_mismatch:resilience_recovery:{key}")
