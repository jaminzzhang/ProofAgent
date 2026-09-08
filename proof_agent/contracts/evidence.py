from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from hashlib import sha256
from typing import Any, Literal
from urllib.parse import quote

from pydantic import Field, StrictBool, field_validator, model_validator

from proof_agent.contracts.external_source import external_evidence_source
from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.contracts.structured_evidence import StructuredEvidenceRecord, parse_structured_evidence


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
    structured_data: StructuredEvidenceRecord | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_structured_source(self) -> EvidenceChunk:
        if self.structured_data is not None:
            digest = sha256(self.content.encode()).hexdigest()
            if (
                parse_structured_evidence(self.content) != self.structured_data
                or not all((self.source, self.binding_id, self.source_id, self.chunk_id))
                or self.source != external_evidence_source(
                    provider=self.provider_name or "dify", binding_id=self.binding_id or "",
                    source_id=self.source_id or "", document_id=self.document_id,
                    chunk_id=self.chunk_id or "", tenant_id=self.metadata.get("tenant_id"))
                or self.source_version_id != f"sha256:{digest}"
                or self.citation != f"{self.source}#segment={quote(self.chunk_id or '', safe='')}&sha256={digest}"
            ):
                raise ValueError("Structured evidence content or provenance does not match")
        return self

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
