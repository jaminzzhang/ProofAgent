"""Asynchronous Knowledge Source publication-preparation admission."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Protocol
from uuid import uuid4

from proof_agent.capabilities.knowledge.hybrid.publication_jobs import (
    PublicationPreparationJob,
)
from proof_agent.control.knowledge.application import KnowledgeSourceCommandContext
from proof_agent.control.knowledge.ingestion_service import (
    KnowledgeSourceAdmissionEffect,
    KnowledgeSourceCommandUnitOfWork,
    KnowledgeSourceIngestionService,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
    Permission,
)


class _SummaryReader(Protocol):
    def summary_for_source(self, source_id: str) -> Mapping[str, int]: ...


class KnowledgeSourcePublicationPreparationService:
    """Queue expensive publication preparation behind one Source CAS."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], KnowledgeSourceCommandUnitOfWork],
        provider_capability: KnowledgeSourceProviderCapability,
        summary_reader: _SummaryReader,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._commands = KnowledgeSourceIngestionService(
            unit_of_work_factory=unit_of_work_factory,
            provider_capability=provider_capability,
            summary_reader=summary_reader,
            clock=self._clock,
        )

    def prepare_publication(
        self,
        *,
        source_id: str,
        smoke_query: str,
        expected_revision: int,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> KnowledgeSourceOperation:
        normalized_query = smoke_query.strip()
        if not normalized_query or len(normalized_query) > 4_096:
            raise ValueError(
                "smoke_query must be non-empty and at most 4096 characters"
            )
        normalized_key = idempotency_key.strip()
        if not normalized_key or len(normalized_key) > 255:
            raise ValueError("idempotency_key is invalid")
        validation_id = f"kspubval_{uuid4().hex}"
        preparation_job_id = str(uuid4())
        request_sha256 = hashlib.sha256(
            _canonical_json(
                {
                    "schema_version": "publication-preparation-command.v1",
                    "source_id": source_id,
                    "smoke_query": normalized_query,
                    "expected_revision": expected_revision,
                }
            )
        ).hexdigest()

        def persist_preparation(
            unit_of_work: Any,
            source_record: Any,
            operation: KnowledgeSourceOperation,
            admitted_at: datetime,
        ) -> None:
            draft_id = source_record.source.source_draft_version_id
            if draft_id is None:
                raise ValueError(
                    "Knowledge Source publication requires a Source Draft"
                )
            now = admitted_at.astimezone(UTC)
            unit_of_work.publication_preparations.enqueue(
                PublicationPreparationJob(
                    preparation_job_id=preparation_job_id,
                    operation_id=operation.operation_id,
                    validation_id=validation_id,
                    source_id=source_id,
                    source_revision=operation.source_revision,
                    source_draft_version_id=draft_id,
                    smoke_query=normalized_query,
                    state="READY",
                    fencing_token=0,
                    created_by=actor.subject,
                    created_at=now,
                    updated_at=now,
                )
            )
            unit_of_work.audit.append(
                AuditMetadataRecord(
                    audit_id=str(uuid4()),
                    category=AuditCategory.CONFIGURATION,
                    event_type="hybrid_publication.preparation_admitted",
                    outcome=AuditOutcome.SUCCEEDED,
                    actor=actor,
                    occurred_at=_timestamp(now),
                    target_type="publication_preparation_job",
                    target_id=preparation_job_id,
                    metadata={
                        "source_id": source_id,
                        "operation_id": operation.operation_id,
                        "validation_id": validation_id,
                        "source_draft_version_id": draft_id,
                    },
                )
            )

        effect: KnowledgeSourceAdmissionEffect = persist_preparation
        operation, _created = self._commands.admit_async_command(
            source_id=source_id,
            action="prepare_publication",
            command="prepare_publication",
            expected_revision=expected_revision,
            idempotency_key=normalized_key,
            request_sha256=request_sha256,
            context=KnowledgeSourceCommandContext(
                operator_subject=actor.subject,
                permissions=tuple(Permission(value) for value in actor.permissions),
            ),
            stage="publication_preparation_queued",
            admission_effect=effect,
        )
        return operation


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["KnowledgeSourcePublicationPreparationService"]
