from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value


class EvidenceStatus(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceContribution(FrozenModel):
    source_id: str | None = None
    source_version_id: str | None = None
    binding_id: str | None = None
    provider_name: str | None = None
    document_id: str | None = None
    revision_id: str | None = None
    chunk_id: str | None = None
    provider_local_rank: int | None = None
    provider_native_score: float | None = None
    fusion_weight: float | None = None
    citation: str | None = None


class EvidenceChunk(FrozenModel):
    source: str
    content: str
    status: EvidenceStatus
    evidence_id: str | None = None
    source_id: str | None = None
    source_version_id: str | None = None
    binding_id: str | None = None
    provider_name: str | None = None
    document_id: str | None = None
    revision_id: str | None = None
    chunk_id: str | None = None
    provider_native_score: float | None = None
    fusion_rank: float | None = None
    admission_score: float | None = None
    citation: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    contributions: tuple[EvidenceContribution, ...] = Field(default_factory=tuple)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)
