"""Focused trace-safe read and review application for Source workspaces."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from proof_agent.capabilities.knowledge.hybrid.workbook import (
    InsuranceMetadataReview,
    InsuranceMetadataReviewPage,
)
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.contracts import (
    KnowledgeSourceAuditProjection,
    KnowledgeSourceCursorPage,
    KnowledgeSourceCursorPageInfo,
    KnowledgeSourceDocumentProjection,
    KnowledgeSourceMetadataReviewProjection,
    KnowledgeSourcePublicationProjection,
    KnowledgeSourcePublicationValidationProjection,
    Permission,
)


class KnowledgeSourceWorkspaceQuery(Protocol):
    def list_documents(
        self,
        *,
        source_id: str,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]: ...

    def list_publication_validations(
        self,
        *,
        source_id: str,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]: ...

    def list_publications(
        self,
        *,
        source_id: str,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]: ...

    def list_audit(
        self,
        *,
        source_id: str,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]: ...


class KnowledgeSourceRecordReader(Protocol):
    def get_source_record(self, source_id: str) -> Any | None: ...


class MetadataReviewAuthority(Protocol):
    def list_page(
        self,
        source_id: str,
        *,
        limit: int,
        cursor: str | None,
        state: str | None = None,
        import_id: str | None = None,
    ) -> InsuranceMetadataReviewPage: ...

    def resolve(
        self,
        *,
        source_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        action: Literal["approve", "correct", "reject"],
        actor: str,
        reason: str,
        corrections: dict[str, str | int | None] | None = None,
    ) -> InsuranceMetadataReview: ...


class KnowledgeSourceWorkspaceService:
    """Serve bounded projections and independent business-review decisions."""

    def __init__(
        self,
        *,
        knowledge: KnowledgeSourceRecordReader,
        query: KnowledgeSourceWorkspaceQuery,
        reviews: MetadataReviewAuthority,
    ) -> None:
        self._knowledge = knowledge
        self._query = query
        self._reviews = reviews

    def documents(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceDocumentProjection]:
        self._require_source(source_id, context=context)
        return self._query.list_documents(
            source_id=source_id,
            limit=limit,
            cursor=cursor,
        )

    def reviews(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection]:
        self._require_source(source_id, context=context)
        page = self._reviews.list_page(
            source_id,
            limit=limit,
            cursor=cursor,
        )
        data = tuple(_review_projection(review) for review in page.items)
        return KnowledgeSourceCursorPage[KnowledgeSourceMetadataReviewProjection](
            data=data,
            page=KnowledgeSourceCursorPageInfo(
                limit=limit,
                next_cursor=page.next_cursor,
                has_more=page.next_cursor is not None,
            ),
            summary={
                "total": page.summary.total,
                "unresolved": page.summary.unresolved,
                "review_required": page.summary.review_required,
                "ready_for_review": page.summary.ready_for_review,
                "approved": page.summary.approved,
                "corrected": page.summary.corrected,
                "rejected": page.summary.rejected,
            },
        )

    def resolve_review(
        self,
        *,
        source_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        action: Literal["approve", "correct", "reject"],
        actor: str,
        reason: str,
        corrections: dict[str, str | int | None],
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection:
        self._require_source(source_id, context=context)
        self._require_permission(context, Permission.KNOWLEDGE_SOURCE_REVIEW)
        review = self._reviews.resolve(
            source_id=source_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            action=action,
            actor=actor,
            reason=reason,
            corrections=corrections,
        )
        return _review_projection(review)

    def publication_validations(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationValidationProjection]:
        self._require_source(source_id, context=context)
        return self._query.list_publication_validations(
            source_id=source_id,
            limit=limit,
            cursor=cursor,
        )

    def publications(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourcePublicationProjection]:
        self._require_source(source_id, context=context)
        return self._query.list_publications(
            source_id=source_id,
            limit=limit,
            cursor=cursor,
        )

    def audit(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
        limit: int,
        cursor: str | None,
    ) -> KnowledgeSourceCursorPage[KnowledgeSourceAuditProjection]:
        self._require_source(source_id, context=context)
        self._require_permission(context, Permission.AUDIT_VIEW)
        return self._query.list_audit(
            source_id=source_id,
            limit=limit,
            cursor=cursor,
        )

    def _require_source(
        self,
        source_id: str,
        *,
        context: KnowledgeSourceCommandContext,
    ) -> None:
        self._require_permission(context, Permission.KNOWLEDGE_SOURCE_VIEW)
        if self._knowledge.get_source_record(source_id) is None:
            raise KnowledgeSourceCommandRejectedError(
                code="knowledge_source_not_found",
                detail="The Knowledge Source was not found.",
            )

    @staticmethod
    def _require_permission(
        context: KnowledgeSourceCommandContext,
        permission: Permission,
    ) -> None:
        if permission not in context.permissions:
            raise KnowledgeSourceCommandRejectedError(
                code="permission_required",
                detail=f"The {permission.value} permission is required.",
            )


def _review_projection(
    review: InsuranceMetadataReview,
) -> KnowledgeSourceMetadataReviewProjection:
    return KnowledgeSourceMetadataReviewProjection(
        review_id=review.review_id,
        review_identity=review.review_identity,
        review_version=review.review_version,
        document_id=review.document_id,
        revision_id=review.revision_id,
        state=review.state,
        publication_blocked=review.publication_blocked,
        canonical_anchor=review.canonical_anchor,
        citation_uri=review.citation_uri,
        conflict_count=len(review.conflicts),
        resolution_reason=review.resolution_reason,
        resolved_by=review.resolved_by,
    )


__all__ = ["KnowledgeSourceWorkspaceQuery", "KnowledgeSourceWorkspaceService"]
