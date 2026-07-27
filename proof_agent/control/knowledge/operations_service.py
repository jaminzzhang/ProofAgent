"""Focused Knowledge Source operations application service."""

from __future__ import annotations

from typing import Protocol

from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.contracts.knowledge_source_api import (
    KnowledgeSourceCursorPage,
    KnowledgeSourceOperation,
)
from proof_agent.contracts.security import Permission


class _OperationReader(Protocol):
    def get(self, operation_id: str) -> KnowledgeSourceOperation | None: ...


class _OperationQuery(Protocol):
    def list_page(
        self,
        *,
        source_id: str,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]: ...


class KnowledgeSourceOperationsService:
    """Authorize provider-neutral durable operation reads."""

    def __init__(
        self,
        *,
        operations: _OperationReader,
        operation_query: _OperationQuery | None,
    ) -> None:
        self._operations = operations
        self._operation_query = operation_query

    def get(
        self,
        *,
        source_id: str,
        operation_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceOperation:
        self._require_view(context)
        operation = self._operations.get(operation_id)
        if operation is None or operation.source_id != source_id:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_operation_not_found",
                detail="The Knowledge Source operation was not found.",
            )
        return operation

    def list_page(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int = 50,
        cursor: str | None = None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceOperation]:
        self._require_view(context)
        if self._operation_query is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_operations_unavailable",
                detail="Knowledge Source operation history is unavailable.",
            )
        return self._operation_query.list_page(
            source_id=source_id,
            limit=limit,
            cursor=cursor,
        )

    @staticmethod
    def _require_view(context: KnowledgeSourceCommandContext) -> None:
        if Permission.KNOWLEDGE_SOURCE_VIEW not in context.permissions:
            raise KnowledgeSourceCommandRejectedError(
                code="permission_required",
                detail="The knowledge_source.view permission is required.",
            )


__all__ = ["KnowledgeSourceOperationsService"]
