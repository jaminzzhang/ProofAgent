"""Focused Knowledge Source ingestion application service."""

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


class KnowledgeSourceCommandUnitOfWork(Protocol):
    knowledge: _KnowledgeAuthority
    operations: KnowledgeSourceOperationRepository

    def __enter__(self) -> "KnowledgeSourceCommandUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class _SummaryReader(Protocol):
    def summary_for_source(self, source_id: str) -> Mapping[str, int]: ...


class KnowledgeSourceAdmissionEffect(Protocol):
    """Provider work made visible inside the command authority transaction."""

    def __call__(
        self,
        unit_of_work: KnowledgeSourceCommandUnitOfWork,
        source_record: KnowledgeSourceRecord,
        operation: KnowledgeSourceOperation,
        admitted_at: datetime,
    ) -> None: ...


class KnowledgeSourceIngestionService:
    """Admit asynchronous ingestion commands with replay before Source CAS."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], KnowledgeSourceCommandUnitOfWork],
        provider_capability: KnowledgeSourceProviderCapability | None,
        summary_reader: _SummaryReader | None,
        clock: Callable[[], datetime] | None = None,
        operation_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._provider_capability = provider_capability
        self._summary_reader = summary_reader
        self._clock = clock or (lambda: datetime.now(UTC))
        self._operation_id_factory = operation_id_factory or (
            lambda: f"ksop_{uuid4().hex}"
        )

    def admit_async_command(
        self,
        *,
        source_id: str,
        action: str,
        command: str,
        expected_revision: int,
        idempotency_key: str,
        request_sha256: str,
        context: KnowledgeSourceCommandContext,
        stage: str = "queued",
        poll_after_ms: int = 1_000,
        admission_effect: KnowledgeSourceAdmissionEffect | None = None,
        advance_source_revision: bool = True,
    ) -> tuple[KnowledgeSourceOperation, bool]:
        if expected_revision < 1:
            raise ValueError("expected_revision must be positive")
        with self._unit_of_work_factory() as uow:
            replay = uow.operations.replay(
                operator_subject=context.operator_subject,
                source_id=source_id,
                command=command,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
            )
            if replay is not None:
                return replay, False
            if self._provider_capability is None or self._summary_reader is None:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_provider_unavailable",
                    detail="The Knowledge Source provider is unavailable.",
                )
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
            projected = next(
                (item for item in actions.actions if item.action == action),
                None,
            )
            if projected is None or not projected.allowed:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_action_blocked",
                    detail="The Knowledge Source action is currently blocked.",
                    blockers=() if projected is None else projected.blockers,
                )
            if record.revision != expected_revision:
                raise KnowledgeSourceRevisionConflictError(
                    expected_revision=expected_revision,
                    current_revision=record.revision,
                )
            now = self._now()
            source_revision = record.revision
            if advance_source_revision:
                updated_source = record.source.model_copy(
                    update={
                        "updated_at": _next_source_timestamp(
                            record.source.updated_at,
                            now,
                        )
                    }
                )
                source_version = uow.knowledge.save_source(
                    updated_source,
                    expected_revision=expected_revision,
                )
                source_revision = source_version.revision
            operation = KnowledgeSourceOperation(
                operation_id=self._operation_id_factory(),
                source_id=source_id,
                command=command,
                status="queued",
                stage=stage,
                source_revision=source_revision,
                poll_after_ms=poll_after_ms,
                created_at=_timestamp(now),
                updated_at=_timestamp(now),
            )
            admitted, created = uow.operations.admit(
                operation,
                operator_subject=context.operator_subject,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                expires_at=now + timedelta(hours=24),
            )
            if admission_effect is not None and created:
                admission_effect(uow, record, admitted, now)
            uow.commit()
            return admitted, created

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Knowledge Source ingestion clock must be timezone-aware")
        return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _next_source_timestamp(current: str, now: datetime) -> str:
    current_value = datetime.fromisoformat(current.replace("Z", "+00:00"))
    if current_value.tzinfo is None or current_value.utcoffset() is None:
        raise ValueError("Knowledge Source updated_at must be timezone-aware")
    advanced = max(now, current_value + timedelta(microseconds=1))
    return _timestamp(advanced)


__all__ = [
    "KnowledgeSourceAdmissionEffect",
    "KnowledgeSourceCommandUnitOfWork",
    "KnowledgeSourceIngestionService",
]
