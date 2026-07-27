"""Focused Knowledge Source publication application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Protocol
from uuid import uuid4

from proof_agent.control.knowledge.action_policy import project_source_actions
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.contracts.knowledge_operations import (
    PreparedHybridKnowledgePublication,
)
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceOperation,
    KnowledgeSourceProviderCapability,
)
from proof_agent.contracts.persistence import KnowledgeSourceRecord
from proof_agent.contracts.ports.knowledge_source_operations import (
    KnowledgeSourceOperationRepository,
)


class _KnowledgeAuthority(Protocol):
    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord | None: ...

    def save_source(self, source: Any, *, expected_revision: int) -> Any: ...


class _PreparedPublicationAuthority(Protocol):
    def consume(
        self,
        validation_id: str,
        *,
        source_id: str,
        expected_fencing_token: int,
        consumed_at: str,
    ) -> PreparedHybridKnowledgePublication: ...


class _PublicationCommitAuthority(Protocol):
    def commit_prepared(
        self,
        prepared: PreparedHybridKnowledgePublication,
        *,
        publication_id: str,
        published_by: str,
        change_note: str,
        published_at: str,
    ) -> str: ...


class KnowledgeSourcePublicationUnitOfWork(Protocol):
    knowledge: _KnowledgeAuthority
    operations: KnowledgeSourceOperationRepository
    prepared_publications: _PreparedPublicationAuthority
    publication_authority: _PublicationCommitAuthority

    def __enter__(self) -> "KnowledgeSourcePublicationUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class _SummaryReader(Protocol):
    def summary_for_source(self, source_id: str) -> Mapping[str, int]: ...


class KnowledgeSourcePublicationService:
    """Consume one prepared validation through a short PostgreSQL-only CAS."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], KnowledgeSourcePublicationUnitOfWork],
        provider_capability: KnowledgeSourceProviderCapability,
        summary_reader: _SummaryReader,
        clock: Callable[[], datetime] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
        publication_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._provider_capability = provider_capability
        self._summary_reader = summary_reader
        self._clock = clock or (lambda: datetime.now(UTC))
        self._operation_id_factory = operation_id_factory or (
            lambda: f"ksop_{uuid4().hex}"
        )
        self._publication_id_factory = publication_id_factory or (
            lambda: f"kspub_{uuid4().hex}"
        )

    def publish(
        self,
        *,
        source_id: str,
        validation_id: str,
        expected_revision: int,
        expected_fencing_token: int,
        change_note: str,
        idempotency_key: str,
        request_sha256: str,
        context: KnowledgeSourceCommandContext,
    ) -> tuple[KnowledgeSourceOperation, bool]:
        normalized_note = change_note.strip()
        if not normalized_note or len(normalized_note) > 1_000:
            raise ValueError("change_note must be non-empty and at most 1000 characters")
        with self._unit_of_work_factory() as uow:
            replay = uow.operations.replay(
                operator_subject=context.operator_subject,
                source_id=source_id,
                command="publish",
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            if replay is not None:
                return replay, False
            record = uow.knowledge.get_source_record(source_id)
            if record is None:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_not_found",
                    detail="The Knowledge Source was not found.",
                )
            actions = project_source_actions(
                source=record.source,
                source_revision=record.revision,
                context=context,
                provider=self._provider_capability,
                summary=self._summary_reader.summary_for_source(source_id),
            )
            publish_action = next(
                action for action in actions.actions if action.action == "publish"
            )
            if not publish_action.allowed:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_action_blocked",
                    detail="Knowledge Source publication is currently blocked.",
                    blockers=publish_action.blockers,
                )
            if record.revision != expected_revision:
                raise KnowledgeSourceRevisionConflictError(
                    expected_revision=expected_revision,
                    current_revision=record.revision,
                )
            now = self._now()
            timestamp = _timestamp(now)
            prepared = uow.prepared_publications.consume(
                validation_id,
                source_id=source_id,
                expected_fencing_token=expected_fencing_token,
                consumed_at=timestamp,
            )
            if prepared.source_draft_version_id != record.source.source_draft_version_id:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_publication_validation_stale",
                    detail="The publication validation no longer matches the Source Draft.",
                )
            publication_id = self._publication_id_factory()
            committed_publication_id = uow.publication_authority.commit_prepared(
                prepared,
                publication_id=publication_id,
                published_by=context.operator_subject,
                change_note=normalized_note,
                published_at=timestamp,
            )
            if committed_publication_id != publication_id:
                raise RuntimeError(
                    "publication authority returned a different publication identity"
                )
            updated_source = record.source.model_copy(
                update={
                    "published_snapshot_id": publication_id,
                    "updated_at": timestamp,
                }
            )
            source_version = uow.knowledge.save_source(
                updated_source,
                expected_revision=expected_revision,
            )
            operation = KnowledgeSourceOperation(
                operation_id=self._operation_id_factory(),
                source_id=source_id,
                command="publish",
                status="succeeded",
                stage="published",
                source_revision=source_version.revision,
                poll_after_ms=1_000,
                outcome_code="knowledge_source_published",
                outcome_detail="The prepared Knowledge Source publication was committed.",
                created_at=timestamp,
                updated_at=timestamp,
                completed_at=timestamp,
            )
            admitted, created = uow.operations.admit(
                operation,
                operator_subject=context.operator_subject,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                expires_at=now + timedelta(hours=24),
            )
            uow.commit()
            return admitted, created

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Knowledge Source publication clock must be timezone-aware")
        return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "KnowledgeSourcePublicationService",
    "KnowledgeSourcePublicationUnitOfWork",
]
