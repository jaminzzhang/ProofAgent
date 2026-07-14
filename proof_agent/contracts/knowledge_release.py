"""Immutable evidence inventory authorizing one Hybrid Agent candidate."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.knowledge_index import ExactArtifactRef


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


__all__ = ["KnowledgeReleaseEvidenceSet", "KnowledgeReleaseRecord"]
