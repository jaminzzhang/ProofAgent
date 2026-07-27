"""Focused Knowledge Source configuration application service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Literal, Protocol
from uuid import uuid4

from proof_agent.control.knowledge.action_policy import project_source_actions
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.contracts.agent_configuration import KnowledgeSourceLifecycleState
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceCapabilityProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceDetailProjection,
    KnowledgeSourceListItemProjection,
)
from proof_agent.contracts.persistence import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    KnowledgeSourceRecord,
)
from proof_agent.contracts.security import Permission


class KnowledgeSourceRecordReader(Protocol):
    def get_source_record(self, source_id: str) -> KnowledgeSourceRecord | None: ...


class KnowledgeSourceSummaryReader(Protocol):
    def summary_for_source(self, source_id: str) -> Mapping[str, int]: ...


class KnowledgeSourceListQuery(Protocol):
    def list_page(
        self,
        *,
        limit: int,
        cursor: str | None,
        lifecycle_state: Literal["active", "archived"] | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]: ...


class KnowledgeSourceCreator(Protocol):
    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        params: Mapping[str, object],
        actor: AuditActorFacts,
    ) -> Any: ...


class KnowledgeSourceLifecycleAuthority(KnowledgeSourceRecordReader, Protocol):
    def save_source(self, source: Any, *, expected_revision: int) -> Any: ...


class KnowledgeSourceAuditAppender(Protocol):
    def append(self, event: AuditMetadataRecord) -> None: ...


class KnowledgeSourceLifecycleUnitOfWork(Protocol):
    knowledge: KnowledgeSourceLifecycleAuthority
    audit: KnowledgeSourceAuditAppender

    def __enter__(self) -> "KnowledgeSourceLifecycleUnitOfWork": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class KnowledgeSourceConfigurationService:
    """Read Source authority and evaluate commands through one action policy."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeSourceRecordReader,
        summaries: KnowledgeSourceSummaryReader,
        capabilities: KnowledgeSourceCapabilityProjection,
        source_query: KnowledgeSourceListQuery | None = None,
        creator: KnowledgeSourceCreator | None = None,
        unit_of_work_factory: (
            Callable[[], KnowledgeSourceLifecycleUnitOfWork] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._summaries = summaries
        self._capabilities = capabilities
        self._source_query = source_query
        self._creator = creator
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def capabilities(self) -> KnowledgeSourceCapabilityProjection:
        return self._capabilities

    def list_page(
        self,
        *,
        context: KnowledgeSourceCommandContext,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceListItemProjection]:
        if Permission.KNOWLEDGE_SOURCE_VIEW not in context.permissions:
            raise KnowledgeSourceCommandRejectedError(
                code="permission_required",
                detail="The knowledge_source.view permission is required.",
            )
        if self._source_query is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_configuration_unavailable",
                detail="Knowledge Source collection queries are unavailable.",
            )
        return self._source_query.list_page(
            limit=limit,
            cursor=cursor,
            lifecycle_state=None,
        )

    def create_source(
        self,
        *,
        source_id: str,
        name: str,
        provider: str,
        params: Mapping[str, object],
        actor: AuditActorFacts,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        if Permission.KNOWLEDGE_SOURCE_EDIT not in context.permissions:
            raise KnowledgeSourceCommandRejectedError(
                code="permission_required",
                detail="The knowledge_source.edit permission is required.",
            )
        selected = next(
            (
                item
                for item in self._capabilities.providers
                if item.provider == provider
            ),
            None,
        )
        if (
            selected is None
            or not selected.creation_supported
            or selected.readiness.state != "ready"
            or self._creator is None
        ):
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_provider_unavailable",
                detail="The requested Knowledge Source provider cannot create a Source.",
            )
        self._creator.create_source(
            source_id=source_id,
            name=name,
            params=params,
            actor=actor,
        )
        return self.detail(source_id, context=context)

    def detail(
        self,
        source_id: str,
        *,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        if Permission.KNOWLEDGE_SOURCE_VIEW not in context.permissions:
            raise KnowledgeSourceCommandRejectedError(
                code="permission_required",
                detail="The knowledge_source.view permission is required.",
            )
        record = self._knowledge.get_source_record(source_id)
        if record is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_not_found",
                detail="The Knowledge Source was not found.",
            )
        provider = next(
            (
                item
                for item in self._capabilities.providers
                if item.provider == record.source.provider
            ),
            None,
        )
        if provider is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_provider_unavailable",
                detail="The Knowledge Source provider is unavailable.",
            )
        summary = self._summaries.summary_for_source(source_id)
        actions = project_source_actions(
            source=record.source,
            source_revision=record.revision,
            context=context,
            provider=provider,
            summary=summary,
        )
        return KnowledgeSourceDetailProjection(
            source=record.source,
            revision=record.revision,
            summary=summary,
            action_capabilities=actions,
        )

    def require_action(
        self,
        source_id: str,
        *,
        action: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        detail = self.detail(source_id, context=context)
        capability = next(
            (
                item
                for item in detail.action_capabilities.actions
                if item.action == action
            ),
            None,
        )
        if capability is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_action_unknown",
                detail="The Knowledge Source action is not supported.",
            )
        if not capability.allowed:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_action_blocked",
                detail="The Knowledge Source action is currently blocked.",
                blockers=capability.blockers,
            )
        return detail

    def change_lifecycle(
        self,
        source_id: str,
        *,
        action: Literal["archive", "restore"],
        expected_revision: int,
        reason: str,
        actor: AuditActorFacts,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceDetailProjection:
        """Apply one lifecycle CAS and its trace-safe audit in one transaction."""

        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("A lifecycle decision reason is required.")
        if self._unit_of_work_factory is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_lifecycle_unavailable",
                detail="Knowledge Source lifecycle commands are unavailable.",
            )
        target_state = (
            KnowledgeSourceLifecycleState.ARCHIVED
            if action == "archive"
            else KnowledgeSourceLifecycleState.ACTIVE
        )
        with self._unit_of_work_factory() as uow:
            record = uow.knowledge.get_source_record(source_id)
            if record is None:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_not_found",
                    detail="The Knowledge Source was not found.",
                )
            provider = next(
                (
                    item
                    for item in self._capabilities.providers
                    if item.provider == record.source.provider
                ),
                None,
            )
            if provider is None:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_provider_unavailable",
                    detail="The Knowledge Source provider is unavailable.",
                )
            projected = project_source_actions(
                source=record.source,
                source_revision=record.revision,
                context=context,
                provider=provider,
                summary=self._summaries.summary_for_source(source_id),
            )
            capability = next(
                (item for item in projected.actions if item.action == action),
                None,
            )
            if capability is None or not capability.allowed:
                raise KnowledgeSourceCommandRejectedError(
                    code="knowledge_source_action_blocked",
                    detail="The Knowledge Source lifecycle command is blocked.",
                    blockers=() if capability is None else capability.blockers,
                )
            if record.revision != expected_revision:
                raise KnowledgeSourceRevisionConflictError(
                    expected_revision=expected_revision,
                    current_revision=record.revision,
                )
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("Knowledge Source lifecycle clock must be timezone-aware")
            current_updated_at = datetime.fromisoformat(
                record.source.updated_at.replace("Z", "+00:00")
            )
            advanced = max(now, current_updated_at + timedelta(microseconds=1))
            occurred_at = advanced.astimezone(UTC).isoformat().replace("+00:00", "Z")
            uow.knowledge.save_source(
                record.source.model_copy(
                    update={
                        "lifecycle_state": target_state,
                        "updated_at": occurred_at,
                    }
                ),
                expected_revision=expected_revision,
            )
            uow.audit.append(
                AuditMetadataRecord(
                    audit_id=str(uuid4()),
                    category=AuditCategory.CONFIGURATION,
                    event_type=f"knowledge_source.{action}d",
                    outcome=AuditOutcome.SUCCEEDED,
                    actor=actor,
                    occurred_at=occurred_at,
                    target_type="knowledge_source",
                    target_id=source_id,
                    metadata={
                        "source_id": source_id,
                        "reason": normalized_reason,
                        "previous_revision": expected_revision,
                    },
                )
            )
            uow.commit()
        return self.detail(source_id, context=context)


__all__ = [
    "KnowledgeSourceConfigurationService",
    "KnowledgeSourceCreator",
    "KnowledgeSourceLifecycleUnitOfWork",
    "KnowledgeSourceListQuery",
    "KnowledgeSourceRecordReader",
    "KnowledgeSourceSummaryReader",
]
