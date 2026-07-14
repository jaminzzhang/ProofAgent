"""Candidate binding and fail-closed verification for Knowledge Release Records."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from proof_agent.contracts import ContractBundle, ExactArtifactRef, ResolvedKnowledgeBindingSet
from proof_agent.contracts.knowledge_release import (
    KnowledgeReleaseEvidenceSet,
    KnowledgeReleaseRecord,
)
from proof_agent.errors import ErrorCode, ProofAgentError


class KnowledgeReleaseEvidenceAuthority(Protocol):
    def verify_release_record(self, record: KnowledgeReleaseRecord) -> bool: ...


def knowledge_release_candidate_sha256(
    contract_bundle: ContractBundle,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
) -> str:
    return _sha256(
        {
            "contract_bundle": contract_bundle.model_dump(mode="json"),
            "resolved_knowledge_bindings": resolved_knowledge_bindings.model_dump(mode="json"),
        }
    )


def seal_knowledge_release_record(
    *,
    record_id: str,
    contract_bundle: ContractBundle,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
    shadow_artifact: ExactArtifactRef,
    capacity_artifact: ExactArtifactRef,
    acceptance_artifact: ExactArtifactRef,
    recovery_artifact: ExactArtifactRef,
    created_at: str,
    created_by: str,
) -> KnowledgeReleaseRecord:
    evidence = KnowledgeReleaseEvidenceSet(
        shadow=shadow_artifact,
        capacity=capacity_artifact,
        acceptance=acceptance_artifact,
        recovery=recovery_artifact,
    )
    payload = {
        "schema_version": "knowledge-release-record.v1",
        "record_id": record_id,
        "candidate_sha256": knowledge_release_candidate_sha256(
            contract_bundle, resolved_knowledge_bindings
        ),
        "evidence": evidence.model_dump(mode="json"),
        "created_at": created_at,
        "created_by": created_by,
    }
    return KnowledgeReleaseRecord(
        record_id=record_id,
        candidate_sha256=str(payload["candidate_sha256"]),
        evidence=evidence,
        created_at=created_at,
        created_by=created_by,
        record_sha256=_sha256(payload),
    )


def require_knowledge_release_record(
    *,
    record: KnowledgeReleaseRecord,
    contract_bundle: ContractBundle,
    resolved_knowledge_bindings: ResolvedKnowledgeBindingSet,
) -> None:
    payload = record.model_dump(mode="json", exclude={"record_sha256"})
    if _sha256(payload) != record.record_sha256:
        raise _release_error("Knowledge Release Record digest is invalid.")
    expected_candidate = knowledge_release_candidate_sha256(
        contract_bundle, resolved_knowledge_bindings
    )
    if record.candidate_sha256 != expected_candidate:
        raise _release_error("Knowledge Release Record does not match the publication candidate.")
    digests = tuple(
        artifact.sha256
        for artifact in (
            record.evidence.shadow,
            record.evidence.capacity,
            record.evidence.acceptance,
            record.evidence.recovery,
        )
    )
    if len(set(digests)) != 4:
        raise _release_error("Knowledge Release Record evidence artifacts must be distinct.")


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _release_error(message: str) -> ProofAgentError:
    return ProofAgentError(
        ErrorCode.PA_CONFIG_002,
        message,
        "Create a new candidate-bound Knowledge Release Record from passing shadow, "
        "capacity, sealed acceptance, and recovery artifacts.",
    )


__all__ = [
    "knowledge_release_candidate_sha256",
    "KnowledgeReleaseEvidenceAuthority",
    "require_knowledge_release_record",
    "seal_knowledge_release_record",
]
