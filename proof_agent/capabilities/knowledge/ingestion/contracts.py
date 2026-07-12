"""Typed document parser contracts for asynchronous knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, StrictInt

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.agent_configuration import (
    KnowledgeIngestionJob,
    QuarantinedKnowledgeUpload,
)


@dataclass(frozen=True)
class ParserMetadata:
    """Structured parser provenance persisted with normalized text derivatives."""

    adapter: str
    adapter_contract_version: str
    library_version: str | None
    fingerprint_identity: str
    parsed_text_sha256: str | None = None


@dataclass(frozen=True)
class ParsedKnowledgeDocument:
    """Normalized parser output retained for artifact construction and reingestion."""

    text: str
    page_count: int | None
    parser_metadata: ParserMetadata


class HybridIntakeLimits(FrozenModel):
    """Independent bounded intake envelope for the Hybrid Index provider.

    The initial ceilings deliberately match the proven Local upload envelope. They can be
    raised independently after deployment capacity evidence exists.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_file_bytes: StrictInt = Field(default=50 * 1024 * 1024, gt=0, le=50 * 1024 * 1024)
    max_pdf_pages: StrictInt = Field(default=500, gt=0, le=500)
    max_batch_files: StrictInt = Field(default=50, gt=0, le=50)
    max_source_documents: StrictInt = Field(default=10_000, gt=0, le=10_000)


class HybridPdfPageProfile(FrozenModel):
    """Content-free page signals used to choose later structured parsing and OCR."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    page_number: StrictInt = Field(gt=0)
    width_points: float = Field(gt=0, allow_inf_nan=False)
    height_points: float = Field(gt=0, allow_inf_nan=False)
    native_extracted_character_count: StrictInt = Field(ge=0)
    native_text_quality_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    requires_ocr: bool


class HybridPdfPreflight(FrozenModel):
    """Provider-specific PDF safety and page-profile result without document text."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_size_bytes: StrictInt = Field(gt=0)
    page_count: StrictInt = Field(gt=0)
    page_profiles: tuple[HybridPdfPageProfile, ...]


class KnowledgeDocumentParser(Protocol):
    """Adapter boundary for one accepted quarantine upload type."""

    @property
    def parser_metadata(self) -> ParserMetadata: ...

    def parse(self, path: Path, content_type: str) -> ParsedKnowledgeDocument: ...


@dataclass(frozen=True)
class KnowledgeWorkerDiagnostic:
    """Value-safe warning emitted while selecting one worker task."""

    source_id: str
    code: str
    message: str


@dataclass(frozen=True)
class KnowledgeWorkerTaskClaim:
    """One token-owned quarantine-validation or artifact-build task."""

    kind: Literal["quarantine_validation", "artifact_build"]
    upload: QuarantinedKnowledgeUpload | None = None
    ingestion_job: KnowledgeIngestionJob | None = None


@dataclass(frozen=True)
class KnowledgeWorkerClaimSelection:
    """Atomic unified-queue selector output with non-blocking diagnostics."""

    task: KnowledgeWorkerTaskClaim | None
    diagnostics: tuple[KnowledgeWorkerDiagnostic, ...] = ()
