"""Access-controlled, one-attempt insurance Knowledge acceptance boundary."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.evaluation import (
    InsuranceKnowledgeSliceMetrics,
    InsuranceRetrievalMetrics,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.artifact_io import write_evaluation_artifact
from proof_agent.evaluation.gate_profiles import (
    INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1,
    KnowledgeAcceptanceGateProfile,
)
from proof_agent.evaluation.knowledge_gates import (
    KnowledgeAcceptanceAggregate,
    evaluate_knowledge_release,
)


class SealedKnowledgeSuiteRef(FrozenModel):
    """Exact private artifact identity; intentionally contains no case labels."""

    suite_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    case_count: Literal[200] = 200
    artifact: ExactArtifactRef


class SealedKnowledgeAcceptanceEnvelope(FrozenModel):
    """Private evaluator request without aggregate or case payloads."""

    candidate_digest: str = Field(min_length=1)
    suite_ref: SealedKnowledgeSuiteRef
    gate_profile_id: str = INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1.profile_id


class SealedKnowledgeAcceptanceAttestation(FrozenModel):
    """Aggregate result bound to an independently verified evaluator identity."""

    evaluator_id: str = Field(min_length=1)
    key_id: str = Field(min_length=1)
    candidate_digest: str = Field(min_length=1)
    suite_ref: SealedKnowledgeSuiteRef
    gate_profile_id: str = Field(min_length=1)
    aggregate: KnowledgeAcceptanceAggregate
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature: str = Field(min_length=1)


class SealedKnowledgeAcceptanceResult(FrozenModel):
    """Tuner-safe aggregate result with no case-level feedback surface."""

    candidate_digest: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    evaluator_key_id: str = Field(min_length=1)
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_id: str
    suite_version: str
    suite_artifact: ExactArtifactRef
    profile_id: str
    status: Literal["passed", "blocked"]
    case_count: int = Field(gt=0)
    overall: InsuranceRetrievalMetrics
    slices: tuple[InsuranceKnowledgeSliceMetrics, ...]
    human_reviewed_support_precision: float = Field(ge=0.0, le=1.0)
    hybrid_retrieval_p95_seconds: float = Field(ge=0.0)
    hard_gate_failures: int = Field(ge=0)
    quality_evaluated: bool
    quality_gate_failures: int = Field(ge=0)
    performance_evaluated: bool
    performance_gate_failures: int = Field(ge=0)
    blocking_reasons: tuple[str, ...] = ()


AttestationProvider = Callable[
    [str, SealedKnowledgeSuiteRef, str],
    SealedKnowledgeAcceptanceAttestation,
]
AttestationVerifier = Callable[[SealedKnowledgeAcceptanceAttestation], bool]


def seal_knowledge_acceptance_attestation(
    *,
    evaluator_id: str,
    key_id: str,
    candidate_digest: str,
    suite_ref: SealedKnowledgeSuiteRef,
    gate_profile_id: str,
    aggregate: KnowledgeAcceptanceAggregate,
    signature: str,
) -> SealedKnowledgeAcceptanceAttestation:
    """Build the canonical payload digest that an evaluator signs externally."""

    payload = _attestation_payload(
        evaluator_id=evaluator_id,
        key_id=key_id,
        candidate_digest=candidate_digest,
        suite_ref=suite_ref,
        gate_profile_id=gate_profile_id,
        aggregate=aggregate,
    )
    return SealedKnowledgeAcceptanceAttestation(
        evaluator_id=evaluator_id,
        key_id=key_id,
        candidate_digest=candidate_digest,
        suite_ref=suite_ref,
        gate_profile_id=gate_profile_id,
        aggregate=aggregate,
        attestation_sha256=_canonical_sha256(payload),
        signature=signature,
    )


class SealedKnowledgeAcceptanceStore:
    """Claims a candidate once, delegates private execution, and projects aggregates."""

    def __init__(
        self,
        *,
        attestation_provider: AttestationProvider,
        attestation_verifier: AttestationVerifier,
        attempt_store: Path | None = None,
        gate_profile: KnowledgeAcceptanceGateProfile = INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1,
    ) -> None:
        self._attestation_provider = attestation_provider
        self._attestation_verifier = attestation_verifier
        self._attempt_store = attempt_store
        self._gate_profile = gate_profile
        self._claimed_candidates: set[str] = set()
        self._lock = Lock()

    def run(
        self,
        *,
        candidate_digest: str,
        sealed_suite_ref: SealedKnowledgeSuiteRef,
    ) -> SealedKnowledgeAcceptanceResult:
        """Consume the candidate's sole attempt before invoking private evaluation."""

        normalized_digest = candidate_digest.strip()
        if not normalized_digest:
            raise EvaluationInputError("candidate digest must be non-empty")
        self._claim_attempt(normalized_digest, sealed_suite_ref)
        attestation = self._attestation_provider(
            normalized_digest,
            sealed_suite_ref,
            self._gate_profile.profile_id,
        )
        if attestation.candidate_digest != normalized_digest:
            raise EvaluationInputError("sealed attestation candidate digest mismatch")
        if attestation.suite_ref != sealed_suite_ref:
            raise EvaluationInputError("sealed attestation suite reference mismatch")
        if attestation.gate_profile_id != self._gate_profile.profile_id:
            raise EvaluationInputError("sealed attestation gate profile mismatch")
        expected_attestation_sha256 = _canonical_sha256(
            _attestation_payload(
                evaluator_id=attestation.evaluator_id,
                key_id=attestation.key_id,
                candidate_digest=attestation.candidate_digest,
                suite_ref=attestation.suite_ref,
                gate_profile_id=attestation.gate_profile_id,
                aggregate=attestation.aggregate,
            )
        )
        if attestation.attestation_sha256 != expected_attestation_sha256:
            raise EvaluationInputError("sealed attestation digest mismatch")
        if not self._attestation_verifier(attestation):
            raise EvaluationInputError("sealed attestation signature is not trusted")
        aggregate = attestation.aggregate
        if aggregate.report.case_count != sealed_suite_ref.case_count:
            raise EvaluationInputError(
                "sealed aggregate case count does not match the exact suite reference"
            )
        gate_result = evaluate_knowledge_release(
            aggregate,
            profile=self._gate_profile,
        )
        return SealedKnowledgeAcceptanceResult(
            candidate_digest=normalized_digest,
            evaluator_id=attestation.evaluator_id,
            evaluator_key_id=attestation.key_id,
            attestation_sha256=attestation.attestation_sha256,
            suite_id=sealed_suite_ref.suite_id,
            suite_version=sealed_suite_ref.version,
            suite_artifact=sealed_suite_ref.artifact,
            profile_id=gate_result.profile_id,
            status=gate_result.status,
            case_count=aggregate.report.case_count,
            overall=aggregate.report.overall,
            slices=aggregate.report.slices,
            human_reviewed_support_precision=aggregate.human_reviewed_support_precision,
            hybrid_retrieval_p95_seconds=aggregate.hybrid_retrieval_p95_seconds,
            hard_gate_failures=gate_result.hard_gate_failures,
            quality_evaluated=gate_result.quality_evaluated,
            quality_gate_failures=gate_result.quality_gate_failures,
            performance_evaluated=gate_result.performance_evaluated,
            performance_gate_failures=gate_result.performance_gate_failures,
            blocking_reasons=gate_result.blocking_reasons,
        )

    def _claim_attempt(
        self,
        candidate_digest: str,
        sealed_suite_ref: SealedKnowledgeSuiteRef,
    ) -> None:
        with self._lock:
            if self._attempt_store is None:
                if candidate_digest in self._claimed_candidates:
                    raise _duplicate_attempt(candidate_digest)
                self._claimed_candidates.add(candidate_digest)
                return
            self._attempt_store.mkdir(parents=True, exist_ok=True)
            candidate_key = hashlib.sha256(candidate_digest.encode("utf-8")).hexdigest()
            marker = self._attempt_store / f"{candidate_key}.json"
            payload = json.dumps(
                {
                    "candidate_key": candidate_key,
                    "suite_sha256": sealed_suite_ref.artifact.sha256,
                    "profile_id": self._gate_profile.profile_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            try:
                descriptor = os.open(
                    marker,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise _duplicate_attempt(candidate_digest) from exc
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())


def _duplicate_attempt(candidate_digest: str) -> EvaluationInputError:
    return EvaluationInputError(
        f"sealed evaluator permits one acceptance attempt per candidate: {candidate_digest}"
    )


def _attestation_payload(
    *,
    evaluator_id: str,
    key_id: str,
    candidate_digest: str,
    suite_ref: SealedKnowledgeSuiteRef,
    gate_profile_id: str,
    aggregate: KnowledgeAcceptanceAggregate,
) -> dict[str, object]:
    return {
        "evaluator_id": evaluator_id,
        "key_id": key_id,
        "candidate_digest": candidate_digest,
        "suite_ref": suite_ref,
        "gate_profile_id": gate_profile_id,
        "aggregate": aggregate,
    }


def _canonical_sha256(payload: dict[str, object]) -> str:
    json_payload = {
        key: value.model_dump(mode="json") if isinstance(value, FrozenModel) else value
        for key, value in payload.items()
    }
    return hashlib.sha256(
        json.dumps(json_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def write_sealed_knowledge_acceptance_result(
    path: Path,
    result: SealedKnowledgeAcceptanceResult,
) -> None:
    """Atomically persist only the tuner-safe result projection."""

    write_evaluation_artifact(path, result)


__all__ = [
    "AttestationProvider",
    "AttestationVerifier",
    "SealedKnowledgeAcceptanceAttestation",
    "SealedKnowledgeAcceptanceEnvelope",
    "SealedKnowledgeAcceptanceResult",
    "SealedKnowledgeAcceptanceStore",
    "SealedKnowledgeSuiteRef",
    "seal_knowledge_acceptance_attestation",
    "write_sealed_knowledge_acceptance_result",
]
