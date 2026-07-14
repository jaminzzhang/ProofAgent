"""Fail-closed evidence contract for disposable Hybrid recovery drills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


RecoveryFault = Literal[
    "fail_after_opensearch_refresh",
    "drop_generation_index",
    "corrupt_test_prefix_artifact",
    "cutover_then_rollback_agent_version",
]
SUPPORTED_RECOVERY_FAULTS: tuple[RecoveryFault, ...] = (
    "fail_after_opensearch_refresh",
    "drop_generation_index",
    "corrupt_test_prefix_artifact",
    "cutover_then_rollback_agent_version",
)


class RecoveryPointers(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_publication_id: str = Field(min_length=1)
    agent_version_id: str = Field(min_length=1)


class RecoveryFaultEvidence(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    prior_publication_visible: bool
    expected_manifest_root: str = Field(min_length=1)
    rebuilt_manifest_root: str = Field(min_length=1)
    attestation_reproduced: bool
    cleanup_idempotent: bool
    rollback_pointer_restored: bool


class KnowledgeRecoveryDriver(Protocol):
    """Integration-only adapter that owns test-scoped mutation and recovery APIs."""

    def prove_disposable_authority(self) -> bool: ...

    def snapshot_pointers(self, *, source_id: str) -> RecoveryPointers: ...

    def run_fault(
        self,
        *,
        fault: RecoveryFault,
        source_id: str,
        generation_id: str,
    ) -> RecoveryFaultEvidence: ...


class KnowledgeRecoveryResult(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    fault: RecoveryFault
    passed: bool
    failed_gate: str | None
    prior_publication_visible: bool
    manifest_root_reproduced: bool
    attestation_reproduced: bool
    cleanup_idempotent: bool
    production_pointers_unchanged_before_cutover: bool
    rollback_pointer_restored: bool
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeRecoveryDrillArtifact(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    results: tuple[KnowledgeRecoveryResult, ...] = Field(min_length=1)
    passed: bool
    failed_faults: tuple[RecoveryFault, ...]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeRecoveryEvidenceEnvelope(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["insurance-knowledge-recovery-evidence.v1"]
    source_id: str = Field(min_length=1)
    generation_id: str = Field(min_length=1)
    disposable_repository_marker: Literal[True]
    disposable_bucket_marker: Literal[True]
    results: tuple[KnowledgeRecoveryResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_result_digests(self) -> Self:
        for result in self.results:
            if _result_digest(result) != result.artifact_sha256:
                raise ValueError("recovery evidence result digest mismatch")
        return self


def run_recovery_drill(
    *,
    fault: RecoveryFault,
    disposable_test_marker: bool,
    expected_manifest_root: str,
    rebuilt_manifest_root: str,
    prior_publication_visible: bool = True,
    attestation_reproduced: bool = True,
    cleanup_idempotent: bool = True,
    production_pointers_unchanged_before_cutover: bool = True,
    rollback_pointer_restored: bool = True,
) -> KnowledgeRecoveryResult:
    """Evaluate evidence from a guarded fault run without hiding the first failed gate."""

    if not disposable_test_marker:
        raise EvaluationInputError("recovery fault injection requires a disposable-test marker")
    gates = (
        ("prior_publication_visibility", prior_publication_visible),
        ("manifest_root_reproduction", rebuilt_manifest_root == expected_manifest_root),
        ("attestation_reproduction", attestation_reproduced),
        ("cleanup_idempotence", cleanup_idempotent),
        ("pre_cutover_pointer_stability", production_pointers_unchanged_before_cutover),
        ("rollback_pointer_restoration", rollback_pointer_restored),
    )
    failed_gate = next((name for name, passed in gates if not passed), None)
    payload = {
        "fault": fault,
        "passed": failed_gate is None,
        "failed_gate": failed_gate,
        "prior_publication_visible": prior_publication_visible,
        "manifest_root_reproduced": rebuilt_manifest_root == expected_manifest_root,
        "attestation_reproduced": attestation_reproduced,
        "cleanup_idempotent": cleanup_idempotent,
        "production_pointers_unchanged_before_cutover": production_pointers_unchanged_before_cutover,
        "rollback_pointer_restored": rollback_pointer_restored,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeRecoveryResult(
        fault=fault,
        passed=failed_gate is None,
        failed_gate=failed_gate,
        prior_publication_visible=prior_publication_visible,
        manifest_root_reproduced=rebuilt_manifest_root == expected_manifest_root,
        attestation_reproduced=attestation_reproduced,
        cleanup_idempotent=cleanup_idempotent,
        production_pointers_unchanged_before_cutover=(production_pointers_unchanged_before_cutover),
        rollback_pointer_restored=rollback_pointer_restored,
        artifact_sha256=digest,
    )


def seal_recovery_drill(
    *,
    source_id: str,
    generation_id: str,
    results: tuple[KnowledgeRecoveryResult, ...],
) -> KnowledgeRecoveryDrillArtifact:
    if not source_id or not generation_id or not results:
        raise EvaluationInputError("recovery drill requires Source, Generation, and results")
    faults = tuple(item.fault for item in results)
    if len(faults) != len(set(faults)):
        raise EvaluationInputError("recovery drill fault results must be unique")
    failed_faults = tuple(item.fault for item in results if not item.passed)
    payload = {
        "source_id": source_id,
        "generation_id": generation_id,
        "results": [item.model_dump(mode="json") for item in results],
        "passed": not failed_faults,
        "failed_faults": list(failed_faults),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeRecoveryDrillArtifact(
        source_id=source_id,
        generation_id=generation_id,
        results=results,
        passed=not failed_faults,
        failed_faults=failed_faults,
        artifact_sha256=digest,
    )


def execute_recovery_drill(
    *,
    source_id: str,
    generation_id: str,
    driver: KnowledgeRecoveryDriver,
) -> KnowledgeRecoveryDrillArtifact:
    """Run every supported fault sequentially and prove pointer restoration."""

    if not driver.prove_disposable_authority():
        raise EvaluationInputError(
            "recovery driver did not prove disposable repository and bucket authority"
        )
    original = driver.snapshot_pointers(source_id=source_id)
    results: list[KnowledgeRecoveryResult] = []
    for fault in SUPPORTED_RECOVERY_FAULTS:
        before = driver.snapshot_pointers(source_id=source_id)
        evidence = driver.run_fault(
            fault=fault,
            source_id=source_id,
            generation_id=generation_id,
        )
        after = driver.snapshot_pointers(source_id=source_id)
        results.append(
            run_recovery_drill(
                fault=fault,
                disposable_test_marker=True,
                expected_manifest_root=evidence.expected_manifest_root,
                rebuilt_manifest_root=evidence.rebuilt_manifest_root,
                prior_publication_visible=evidence.prior_publication_visible,
                attestation_reproduced=evidence.attestation_reproduced,
                cleanup_idempotent=evidence.cleanup_idempotent,
                production_pointers_unchanged_before_cutover=(before == original),
                rollback_pointer_restored=(
                    evidence.rollback_pointer_restored and after == original
                ),
            )
        )
    return seal_recovery_drill(
        source_id=source_id,
        generation_id=generation_id,
        results=tuple(results),
    )


def load_recovery_evidence_from_environment(
    source_id: str,
    generation_id: str,
    environ: Mapping[str, str],
) -> KnowledgeRecoveryDrillArtifact:
    """Seal evidence emitted by the disposable fault-injection harness."""

    if environ.get("HYBRID_TEST_DISPOSABLE_MARKER") != "1":
        raise EvaluationInputError(
            "recovery fault injection requires HYBRID_TEST_DISPOSABLE_MARKER=1"
        )
    if environ.get("HYBRID_TEST_REPOSITORY_MARKER") != "disposable-test":
        raise EvaluationInputError("recovery repository lacks the disposable-test marker")
    if environ.get("HYBRID_TEST_BUCKET_MARKER") != "disposable-test":
        raise EvaluationInputError("recovery bucket lacks the disposable-test marker")
    evidence_path = environ.get("HYBRID_TEST_RECOVERY_EVIDENCE")
    if not evidence_path:
        raise EvaluationInputError("HYBRID_TEST_RECOVERY_EVIDENCE is required")
    try:
        raw = yaml.safe_load(Path(evidence_path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationInputError(f"Unable to read recovery evidence: {evidence_path}") from exc
    except yaml.YAMLError as exc:
        raise EvaluationInputError("recovery evidence contains invalid YAML") from exc
    try:
        envelope = KnowledgeRecoveryEvidenceEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationInputError(f"Invalid recovery evidence: {exc}") from exc
    if envelope.source_id != source_id or envelope.generation_id != generation_id:
        raise EvaluationInputError("recovery evidence Source or Generation mismatch")
    return seal_recovery_drill(
        source_id=source_id,
        generation_id=generation_id,
        results=envelope.results,
    )


def _result_digest(result: KnowledgeRecoveryResult) -> str:
    payload = result.model_dump(mode="json")
    payload.pop("artifact_sha256")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


__all__ = [
    "KnowledgeRecoveryDriver",
    "KnowledgeRecoveryDrillArtifact",
    "KnowledgeRecoveryEvidenceEnvelope",
    "KnowledgeRecoveryResult",
    "RecoveryFault",
    "RecoveryFaultEvidence",
    "RecoveryPointers",
    "SUPPORTED_RECOVERY_FAULTS",
    "execute_recovery_drill",
    "load_recovery_evidence_from_environment",
    "run_recovery_drill",
    "seal_recovery_drill",
]
