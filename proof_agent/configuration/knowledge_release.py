"""Candidate binding and fail-closed verification for Knowledge Release Records."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from proof_agent.contracts import (
    ContractBundle,
    ExactArtifactRef,
    FormalProductionAgentCandidate,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.contracts.knowledge_release import (
    FormalProductionAgentPhaseFRecord,
    KnowledgeReleaseEvidenceSet,
    KnowledgeReleaseRecord,
)
from proof_agent.errors import ErrorCode, ProofAgentError


class KnowledgeReleaseEvidenceAuthority(Protocol):
    def verify_release_record(self, record: KnowledgeReleaseRecord) -> bool: ...


class FormalProductionAgentPhaseFAuthority(Protocol):
    def verify_phase_f_record(
        self,
        record: FormalProductionAgentPhaseFRecord,
    ) -> bool: ...


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


def seal_formal_production_agent_phase_f_record(
    *,
    record_id: str,
    provisional_version_id: str,
    validation_run_id: str,
    candidate: FormalProductionAgentCandidate,
    evidence: KnowledgeReleaseEvidenceSet,
    created_at: str,
    created_by: str,
) -> FormalProductionAgentPhaseFRecord:
    payload = {
        "schema_version": "formal-production-agent-phase-f-record.v1",
        "record_id": record_id,
        "provisional_version_id": provisional_version_id,
        "validation_run_id": validation_run_id,
        "formal_candidate_sha256": candidate.formal_candidate_sha256,
        "knowledge_release_candidate_sha256": (candidate.knowledge_release_candidate_sha256),
        "evidence": evidence.model_dump(mode="json"),
        "created_at": created_at,
        "created_by": created_by,
    }
    return FormalProductionAgentPhaseFRecord(
        record_id=record_id,
        provisional_version_id=provisional_version_id,
        validation_run_id=validation_run_id,
        formal_candidate_sha256=candidate.formal_candidate_sha256,
        knowledge_release_candidate_sha256=(candidate.knowledge_release_candidate_sha256),
        evidence=evidence,
        created_at=created_at,
        created_by=created_by,
        record_sha256=_sha256(payload),
    )


def require_formal_production_agent_phase_f_record(
    *,
    record: FormalProductionAgentPhaseFRecord,
    candidate: FormalProductionAgentCandidate,
) -> None:
    payload = record.model_dump(mode="json", exclude={"record_sha256"})
    if _sha256(payload) != record.record_sha256:
        raise _release_error("Formal Production Agent Phase F Record digest is invalid.")
    if record.formal_candidate_sha256 != candidate.formal_candidate_sha256:
        raise _release_error("Phase F Record does not match the Formal Candidate.")
    if record.knowledge_release_candidate_sha256 != candidate.knowledge_release_candidate_sha256:
        raise _release_error("Phase F Record does not match the Knowledge Release candidate.")
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
        raise _release_error("Formal Phase F evidence artifacts must be distinct.")


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
    "FormalProductionAgentPhaseFAuthority",
    "knowledge_release_candidate_sha256",
    "KnowledgeReleaseEvidenceAuthority",
    "require_formal_production_agent_phase_f_record",
    "require_knowledge_release_record",
    "seal_formal_production_agent_phase_f_record",
    "seal_knowledge_release_record",
]
