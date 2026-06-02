"""Typed document parser contracts for asynchronous knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

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
