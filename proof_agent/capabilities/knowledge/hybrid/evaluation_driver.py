"""Pinned-private-network driver for production Knowledge evaluation services."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from typing import Literal, Protocol, cast

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    BoundedSocketPrivateAddressResolver,
    KnowledgeModelCancellation,
    PrivateHostPolicy,
    PrivateNetworkPolicy,
    _HttpJsonTransport,
    _private_https_endpoint,
)
from proof_agent.evaluation.knowledge_capacity import (
    CapacityIngestionSample,
    CapacityRunSample,
)
from proof_agent.evaluation.knowledge_recovery import (
    RecoveryFault,
    RecoveryFaultEvidence,
    RecoveryPointers,
)
from proof_agent.evaluation.knowledge_shadow import (
    ActiveKnowledgePointers,
    ShadowObservation,
    ShadowQuestion,
)
from proof_agent.evaluation.sealed_knowledge_acceptance import (
    SealedKnowledgeAcceptanceAttestation,
    SealedKnowledgeSuiteRef,
)
from proof_agent.contracts import KnowledgeOperationsHealthSources, KnowledgeReleaseRecord


class EvaluationPost(Protocol):
    def __call__(self, path: str, payload: object) -> object: ...


class PrivateKnowledgeEvaluationDriver:
    """One deep adapter for capacity, recovery, shadow, and sealed acceptance RPCs."""

    def __init__(self, *, post: EvaluationPost) -> None:
        self._post = post

    def run_sample(
        self,
        run_id: str,
        phase: str,
        sample_index: int,
        warmup: bool,
    ) -> CapacityRunSample:
        return CapacityRunSample.model_validate(
            self._post(
                "/v1/knowledge-evaluation/capacity/sample",
                {
                    "run_id": run_id,
                    "phase": phase,
                    "sample_index": sample_index,
                    "warmup": warmup,
                },
            )
        )

    def run_ingestion(self) -> CapacityIngestionSample:
        return CapacityIngestionSample.model_validate(
            self._post("/v1/knowledge-evaluation/capacity/ingestion", {})
        )

    def prove_disposable_authority(self) -> bool:
        response = self._mapping(self._post("/v1/knowledge-evaluation/recovery/authority", {}))
        return (
            response.get("disposable_repository") is True
            and response.get("disposable_bucket") is True
        )

    def snapshot_pointers(self, *, source_id: str) -> RecoveryPointers:
        return RecoveryPointers.model_validate(
            self._post(
                "/v1/knowledge-evaluation/recovery/pointers",
                {"source_id": source_id},
            )
        )

    def run_fault(
        self,
        *,
        fault: RecoveryFault,
        source_id: str,
        generation_id: str,
    ) -> RecoveryFaultEvidence:
        return RecoveryFaultEvidence.model_validate(
            self._post(
                "/v1/knowledge-evaluation/recovery/fault",
                {
                    "fault": fault,
                    "source_id": source_id,
                    "generation_id": generation_id,
                },
            )
        )

    def snapshot_active_pointers(self) -> ActiveKnowledgePointers:
        return ActiveKnowledgePointers.model_validate(
            self._post("/v1/knowledge-evaluation/shadow/pointers", {})
        )

    def run_binding(
        self,
        *,
        binding_kind: Literal["legacy", "hybrid"],
        binding_ref: str,
        question: ShadowQuestion,
    ) -> ShadowObservation:
        return ShadowObservation.model_validate(
            self._post(
                "/v1/knowledge-evaluation/shadow/run",
                {
                    "binding_kind": binding_kind,
                    "binding_ref": binding_ref,
                    "case_id": question.case_id,
                    "question_ref": question.question_ref,
                },
            )
        )

    def run_acceptance(
        self,
        *,
        candidate_digest: str,
        suite_ref: SealedKnowledgeSuiteRef,
        gate_profile_id: str,
    ) -> SealedKnowledgeAcceptanceAttestation:
        return SealedKnowledgeAcceptanceAttestation.model_validate(
            self._post(
                "/v1/knowledge-evaluation/acceptance/run",
                {
                    "candidate_digest": candidate_digest,
                    "suite_ref": suite_ref.model_dump(mode="json"),
                    "gate_profile_id": gate_profile_id,
                },
            )
        )

    def read_operations(self, source_id: str) -> KnowledgeOperationsHealthSources:
        return KnowledgeOperationsHealthSources.model_validate(
            self._post(
                "/v1/knowledge-evaluation/operations/read",
                {"source_id": source_id},
            )
        )

    def verify_release_record(self, record: KnowledgeReleaseRecord) -> bool:
        response = self._mapping(
            self._post(
                "/v1/knowledge-evaluation/release/verify",
                {"record": record.model_dump(mode="json")},
            )
        )
        return response.get("authorized") is True

    def __call__(self, source_id: str) -> KnowledgeOperationsHealthSources:
        return self.read_operations(source_id)

    def close(self) -> None:
        close = getattr(self._post, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _mapping(value: object) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError("private Knowledge evaluation response must be a mapping")
        return cast(Mapping[str, object], value)


class HmacKnowledgeAcceptanceVerifier:
    """Independent evaluator identity/key allowlist plus detached HMAC verification."""

    def __init__(
        self,
        *,
        evaluator_ids: frozenset[str],
        key_id: str,
        secret: bytes,
    ) -> None:
        if not evaluator_ids or not key_id or not secret:
            raise ValueError("acceptance verifier trust configuration is incomplete")
        self._evaluator_ids = evaluator_ids
        self._key_id = key_id
        self._secret = secret

    def verify_attestation(self, attestation: SealedKnowledgeAcceptanceAttestation) -> bool:
        if (
            attestation.evaluator_id not in self._evaluator_ids
            or attestation.key_id != self._key_id
        ):
            return False
        expected = hmac.new(
            self._secret,
            attestation.attestation_sha256.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, attestation.signature)


class _PinnedEvaluationPost:
    def __init__(
        self,
        *,
        origin: str,
        token: str,
        timeout_seconds: float,
        transport: _HttpJsonTransport,
        resolver: BoundedSocketPrivateAddressResolver,
    ) -> None:
        self._origin = origin
        self._token = token
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._resolver = resolver

    def __call__(self, path: str, payload: object) -> object:
        if not path.startswith("/v1/knowledge-evaluation/"):
            raise ValueError("unsupported Knowledge evaluation service path")
        return self._transport._post(
            f"{self._origin}{path}",
            payload,
            timeout_seconds=self._timeout_seconds,
            headers={"Authorization": f"Bearer {self._token}"},
            cancellation=KnowledgeModelCancellation(),
        )

    def close(self) -> None:
        self._transport.close()
        self._resolver.close()


def create_private_evaluation_driver(
    environ: Mapping[str, str],
) -> PrivateKnowledgeEvaluationDriver:
    origin = _required(environ, "PA_KNOWLEDGE_EVALUATION_ENDPOINT")
    allowed_hosts = PrivateHostPolicy.from_entries(
        _csv(environ, "PA_KNOWLEDGE_EVALUATION_ALLOWED_HOSTS")
    )
    network_policy = PrivateNetworkPolicy.from_entries(
        _csv(environ, "PA_KNOWLEDGE_EVALUATION_ALLOWED_CIDRS")
    )
    normalized_origin = _private_https_endpoint(
        origin,
        field="Knowledge evaluation endpoint",
        allowed_hosts=allowed_hosts,
    )
    token = _required(environ, "PA_KNOWLEDGE_EVALUATION_TOKEN")
    timeout = float(environ.get("PA_KNOWLEDGE_EVALUATION_TIMEOUT_SECONDS", "30"))
    if not 0 < timeout <= 120:
        raise ValueError("Knowledge evaluation timeout must be between 0 and 120 seconds")
    resolver = BoundedSocketPrivateAddressResolver()
    transport = _HttpJsonTransport(
        max_response_bytes=8 * 1024 * 1024,
        network_policy=network_policy,
        resolver=resolver,
    )
    return PrivateKnowledgeEvaluationDriver(
        post=_PinnedEvaluationPost(
            origin=normalized_origin,
            token=token,
            timeout_seconds=timeout,
            transport=transport,
            resolver=resolver,
        )
    )


def create_hmac_acceptance_verifier(
    environ: Mapping[str, str],
) -> HmacKnowledgeAcceptanceVerifier:
    return HmacKnowledgeAcceptanceVerifier(
        evaluator_ids=frozenset(_csv(environ, "PA_KNOWLEDGE_ACCEPTANCE_EVALUATOR_IDS")),
        key_id=_required(environ, "PA_KNOWLEDGE_ACCEPTANCE_TRUSTED_KEY_ID"),
        secret=_required(environ, "PA_KNOWLEDGE_ACCEPTANCE_HMAC_SECRET").encode("utf-8"),
    )


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _csv(environ: Mapping[str, str], name: str) -> tuple[str, ...]:
    values = tuple(item.strip() for item in _required(environ, name).split(",") if item.strip())
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


__all__ = [
    "HmacKnowledgeAcceptanceVerifier",
    "PrivateKnowledgeEvaluationDriver",
    "create_hmac_acceptance_verifier",
    "create_private_evaluation_driver",
]
