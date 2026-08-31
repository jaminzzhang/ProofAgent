"""Immutable evidence inventory authorizing one Hybrid Agent candidate."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from proof_agent.contracts._base import FrozenModel, StrictFrozenModel
from proof_agent.contracts.knowledge_candidates import KnowledgeCandidateExecutionBudget
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceIdentifier,
    KnowledgeServiceSha256Digest,
)


class KnowledgeReleaseEvidenceSet(FrozenModel):
    shadow: ExactArtifactRef
    capacity: ExactArtifactRef
    acceptance: ExactArtifactRef
    recovery: ExactArtifactRef


class KnowledgeReleaseRecord(FrozenModel):
    schema_version: Literal["knowledge-release-record.v1"] = "knowledge-release-record.v1"
    record_id: str = Field(min_length=1)
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: KnowledgeReleaseEvidenceSet
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FormalProductionAgentPhaseFRecord(StrictFrozenModel):
    """Phase F evidence bound to one exact Formal Production Agent Candidate."""

    schema_version: Literal["formal-production-agent-phase-f-record.v1"] = (
        "formal-production-agent-phase-f-record.v1"
    )
    record_id: KnowledgeServiceIdentifier
    provisional_version_id: KnowledgeServiceIdentifier
    validation_run_id: KnowledgeServiceIdentifier
    formal_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    knowledge_release_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence: KnowledgeReleaseEvidenceSet
    created_at: str = Field(strict=True, min_length=1)
    created_by: str = Field(strict=True, min_length=1, max_length=256)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProductionAgentReleaseReferenceRequest(StrictFrozenModel):
    """Exact KSS Reference request for one future Published Agent Version."""

    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    external_resource_kind: Literal["published_agent_version"] = "published_agent_version"
    external_resource_id: KnowledgeServiceIdentifier
    purpose: Literal["execution_or_rollback"] = "execution_or_rollback"


class RegisteredProductionAgentReleaseReference(ProductionAgentReleaseReferenceRequest):
    """Strict active KSS Reference receipt returned through the injected registrar."""

    schema_version: Literal["registered-production-agent-release-reference.v1"] = (
        "registered-production-agent-release-reference.v1"
    )
    release_reference_id: KnowledgeServiceIdentifier
    authenticated_client_id: KnowledgeServiceIdentifier
    registered_at: AwareDatetime
    state: Literal["active"] = "active"


class ProductionAgentKnowledgeQueryGrantRequest(StrictFrozenModel):
    """Exact KSS Release selected by a future Formal Production Agent Candidate."""

    knowledge_base_release_id: KnowledgeServiceIdentifier


class ProvisionedProductionAgentKnowledgeQueryGrant(ProductionAgentKnowledgeQueryGrantRequest):
    """Strict secret-free KSS Query Grant receipt retained by ProofAgent."""

    schema_version: Literal["knowledge-query-grant.v1"] = "knowledge-query-grant.v1"
    client_grant_id: KnowledgeServiceIdentifier
    client_id: KnowledgeServiceIdentifier
    knowledge_space_id: KnowledgeServiceIdentifier
    allowed_strategies: tuple[Literal["single_pass", "agentic"], ...] = Field(
        min_length=1,
        max_length=2,
    )
    execution_budget: KnowledgeCandidateExecutionBudget
    effective_access_scope_digest: KnowledgeServiceSha256Digest
    active: Literal[True] = True
    created_at: AwareDatetime

    @model_validator(mode="after")
    def require_distinct_strategies(self) -> Self:
        if len(set(self.allowed_strategies)) != len(self.allowed_strategies):
            raise ValueError("allowed_strategies must be distinct")
        return self


__all__ = [
    "FormalProductionAgentPhaseFRecord",
    "KnowledgeReleaseEvidenceSet",
    "KnowledgeReleaseRecord",
    "ProductionAgentReleaseReferenceRequest",
    "ProductionAgentKnowledgeQueryGrantRequest",
    "ProvisionedProductionAgentKnowledgeQueryGrant",
    "RegisteredProductionAgentReleaseReference",
]
