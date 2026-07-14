from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

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
    authority_admitted: StrictBool = False
    authority_outcome: Literal["PASS", "FAIL"] | None = None
    supported_evidence_slot_ids: tuple[str, ...] = ()
    citation: str | None = None
    metadata: Mapping[str, Any] = Field(default_factory=FrozenDict)
    contributions: tuple[EvidenceContribution, ...] = Field(default_factory=tuple)

    @field_validator("metadata", mode="after")
    @classmethod
    def freeze_metadata(cls, value: Any) -> Any:
        return freeze_value(value)

    @model_validator(mode="after")
    def validate_authority_admission(self) -> EvidenceChunk:
        if self.authority_admitted and self.authority_outcome != "PASS":
            raise ValueError("authority-admitted evidence requires a PASS outcome")
        if self.authority_admitted and not self.supported_evidence_slot_ids:
            raise ValueError("authority-admitted evidence requires supported evidence slots")
        if not self.authority_admitted and self.authority_outcome == "PASS":
            raise ValueError("PASS authority outcome requires admitted evidence")
        if len(self.supported_evidence_slot_ids) != len(set(self.supported_evidence_slot_ids)):
            raise ValueError("supported evidence slot ids must be unique")
        return self
