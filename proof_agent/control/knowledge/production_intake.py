"""Production Hybrid PDF admission behind exact storage and transactional authorities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Any, Protocol
from uuid import uuid4

from proof_agent.capabilities.knowledge.hybrid.intake import preflight_hybrid_pdf
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.ingestion.contracts import HybridIntakeLimits
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridPrivateParserBuildConfig,
    hybrid_build_request_sha256,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
)


class HybridIntakeKnowledgeRepository(Protocol):
    def get_knowledge_source(self, source_id: str) -> KnowledgeSource | None: ...

    def resolve_version(self, asset_id: str, *, version_id: str | None = None) -> Any: ...


class HybridIntakeIngestionRepository(Protocol):
    def enqueue(
        self,
        request: HybridArtifactBuildRequest,
        *,
        filename: str = "document.pdf",
        uploaded_by: str = "system",
    ) -> Any: ...


class HybridIntakeUnitOfWork(Protocol):
    knowledge: Any
    hybrid_ingestion: Any
    audit: Any

    def __enter__(self) -> "HybridIntakeUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


@dataclass(frozen=True)
class HybridPdfAdmission:
    source: KnowledgeSource
    request: HybridArtifactBuildRequest
    filename: str
    page_count: int
    uploaded_by: str
    created_at: str


class ProductionHybridKnowledgeIntakeService:
    """Admit safe PDFs without making local files or environment secrets authoritative."""

    def __init__(
        self,
        *,
        knowledge: HybridIntakeKnowledgeRepository,
        ingestion: HybridIntakeIngestionRepository,
        unit_of_work_factory: Callable[[], HybridIntakeUnitOfWork],
        artifact_store: KnowledgeArtifactStore,
        build_config: HybridPrivateParserBuildConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._knowledge = knowledge
        self._ingestion = ingestion
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_store = artifact_store
        self._build_config = build_config
        self._clock = clock

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        params: Mapping[str, object],
        actor: AuditActorFacts,
    ) -> KnowledgeSource:
        normalized_name = _nonblank(name, "name", maximum=255)
        limits = HybridIntakeLimits.model_validate(dict(params), strict=True)
        now = _timestamp(self._clock())
        source = KnowledgeSource(
            source_id=_safe_source_id(source_id),
            name=normalized_name,
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params=limits.model_dump(mode="json"),
            source_draft_version_id=str(uuid4()),
            created_at=now,
            updated_at=now,
        )
        with self._unit_of_work_factory() as uow:
            uow.knowledge.save_source(source, expected_revision=0)
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="knowledge_source.created",
                    target_type="knowledge_source",
                    target_id=source.source_id,
                    occurred_at=now,
                    metadata={"provider": "hybrid_index"},
                )
            )
            uow.commit()
        return source

    def admit_pdf(
        self,
        *,
        source_id: str,
        filename: str,
        content_type: str,
        content: bytes,
        actor: AuditActorFacts,
    ) -> HybridPdfAdmission:
        source = self._knowledge.get_knowledge_source(source_id)
        if (
            source is None
            or source.provider != "hybrid_index"
            or source.lifecycle_state is not KnowledgeSourceLifecycleState.ACTIVE
        ):
            raise KeyError(source_id)
        limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
        normalized_filename = _pdf_filename(filename)
        normalized_content_type = content_type.partition(";")[0].strip().lower()
        if normalized_content_type != "application/pdf":
            raise ValueError("Hybrid Index uploads require application/pdf")
        if type(content) is not bytes or not content or len(content) > limits.max_file_bytes:
            raise ValueError("Hybrid Index PDF is empty or outside the configured byte limit")

        with TemporaryDirectory(prefix="proof-agent-hybrid-intake-") as directory:
            path = Path(directory) / "upload.pdf"
            path.write_bytes(content)
            preflight = preflight_hybrid_pdf(path, limits=limits)
        if (
            preflight.source_size_bytes != len(content)
            or preflight.source_sha256 != hashlib.sha256(content).hexdigest()
        ):
            raise ValueError("Hybrid PDF preflight identity diverged from uploaded bytes")

        job_id = str(uuid4())
        document_id = str(uuid4())
        revision_id = str(uuid4())
        request_identity = f"{source.source_id}:{document_id}:{revision_id}"
        intake_identity = hashlib.sha256(
            _canonical_json(
                {
                    "source_id": source.source_id,
                    "document_id": document_id,
                    "revision_id": revision_id,
                    "source_sha256": preflight.source_sha256,
                    "parser_revision": self._build_config.parser_revision,
                    "model_digests": self._build_config.model_digests,
                    "configuration_sha256": self._build_config.configuration_sha256,
                }
            )
        ).hexdigest()
        original_ref = self._artifact_store.put_immutable(
            key=f"hybrid/{preflight.source_sha256}/{intake_identity}/original.pdf",
            content=content,
            media_type="application/pdf",
        )
        if self._artifact_store.get_exact(original_ref) != content:
            raise ValueError("Hybrid PDF exact storage read-back failed")
        request = HybridArtifactBuildRequest(
            job_id=job_id,
            request_identity=request_identity,
            source_id=source.source_id,
            document_id=document_id,
            revision_id=revision_id,
            original_ref=original_ref,
            page_numbers=tuple(range(1, preflight.page_count + 1)),
            parser_revision=self._build_config.parser_revision,
            model_digests=self._build_config.model_digests,
            configuration_sha256=self._build_config.configuration_sha256,
        )
        request = request.model_copy(
            update={"request_sha256": hybrid_build_request_sha256(request)}
        )

        current_version = self._knowledge.resolve_version(source.source_id)
        if current_version is None:
            raise KeyError(source.source_id)
        now = _timestamp(self._clock())
        updated_source = source.model_copy(
            update={
                "source_draft_version_id": str(uuid4()),
                "updated_at": now,
            }
        )
        with self._unit_of_work_factory() as uow:
            uow.knowledge.save_source(
                updated_source,
                expected_revision=current_version.revision,
            )
            uow.hybrid_ingestion.enqueue(
                request,
                filename=normalized_filename,
                uploaded_by=actor.subject,
            )
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="hybrid_pdf.admitted",
                    target_type="hybrid_ingestion_job",
                    target_id=job_id,
                    occurred_at=now,
                    metadata={
                        "source_id": source.source_id,
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "page_count": preflight.page_count,
                        "size_bytes": preflight.source_size_bytes,
                        "content_sha256": preflight.source_sha256,
                    },
                )
            )
            uow.commit()
        return HybridPdfAdmission(
            source=updated_source,
            request=request,
            filename=normalized_filename,
            page_count=preflight.page_count,
            uploaded_by=actor.subject,
            created_at=now,
        )


def _audit_event(
    *,
    actor: AuditActorFacts,
    event_type: str,
    target_type: str,
    target_id: str,
    occurred_at: str,
    metadata: Mapping[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=actor,
        occurred_at=occurred_at,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )


def _safe_source_id(value: str) -> str:
    normalized = _nonblank(value, "source_id", maximum=128)
    if not normalized[0].isalnum() or any(
        not (character.isalnum() or character in "_-") for character in normalized
    ):
        raise ValueError("source_id contains unsupported characters")
    return normalized


def _pdf_filename(value: str) -> str:
    normalized = _nonblank(value, "filename", maximum=255)
    if Path(normalized).name != normalized or not normalized.lower().endswith(".pdf"):
        raise ValueError("Hybrid Index uploads require one safe .pdf filename")
    return normalized


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value.strip()) > maximum:
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _timestamp(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("Hybrid intake clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


__all__ = ["HybridPdfAdmission", "ProductionHybridKnowledgeIntakeService"]
