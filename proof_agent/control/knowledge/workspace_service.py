"""Focused trace-safe read and review application for Source workspaces."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataReviewV2,
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
    KnowledgeSourceMetadataProfileProjection,
    KnowledgeSourceMetadataProfileValueProjection,
    KnowledgeSourceMetadataValuesProjection,
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
    ) -> Any: ...

    def approve(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
    ) -> Any: ...

    def save_draft(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        changes: dict[str, str | int | date | None],
    ) -> Any: ...

    def reject(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
    ) -> Any: ...

    def get_bound_profile(self, source_id: str, *, production: bool = False) -> Any: ...


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
                "needs_input": page.summary.needs_input,
                "ready_for_approval": page.summary.ready_for_approval,
                "approved": page.summary.approved,
                "rejected": page.summary.rejected,
            },
        )

    def metadata_profile(
        self,
        *,
        source_id: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataProfileProjection:
        self._require_source(source_id, context=context)
        profile = self._reviews.get_bound_profile(source_id, production=False)
        return KnowledgeSourceMetadataProfileProjection(
            profile_id=profile.profile_id,
            profile_revision_id=profile.profile_revision_id,
            reference_only=profile.reference_only,
            authority_values=tuple(
                KnowledgeSourceMetadataProfileValueProjection(
                    code=value.code,
                    label=value.label,
                )
                for value in profile.authority_values
            ),
            taxonomy_id=profile.taxonomy_id,
            taxonomy_revision_id=profile.taxonomy_revision_id,
            precedence_policy_revision_id=profile.precedence_policy_revision_id,
            precedence_authority_tier_values=tuple(
                KnowledgeSourceMetadataProfileValueProjection(
                    code=value.code,
                    label=value.label,
                )
                for value in profile.precedence_authority_tier_values
            ),
        )
    def approve_review(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection:
        self._require_source(source_id, context=context)
        self._require_permission(context, Permission.KNOWLEDGE_SOURCE_REVIEW)
        result = self._reviews.approve(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
        )
        return _review_projection(result.review)

    def save_review_draft(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        changes: dict[str, str | int | date | None],
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection:
        self._require_source(source_id, context=context)
        self._require_permission(context, Permission.KNOWLEDGE_SOURCE_EDIT)
        result = self._reviews.save_draft(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
            changes=changes,
        )
        return _review_projection(result.review)

    def reject_review(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
        review_id: str,
        expected_review_version: int,
        expected_review_identity: str,
        actor: str,
        reason: str,
        context: KnowledgeSourceCommandContext,
    ) -> KnowledgeSourceMetadataReviewProjection:
        self._require_source(source_id, context=context)
        self._require_permission(context, Permission.KNOWLEDGE_SOURCE_REVIEW)
        result = self._reviews.reject(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review_id,
            expected_review_version=expected_review_version,
            expected_review_identity=expected_review_identity,
            actor=actor,
            reason=reason,
        )
        return _review_projection(result.review)

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
    review: InsuranceMetadataReviewV2,
) -> KnowledgeSourceMetadataReviewProjection:
    return KnowledgeSourceMetadataReviewProjection(
        review_id=review.review_id,
        review_identity=review.review_identity,
        review_version=review.review_version,
        document_id=review.document_id,
        revision_id=review.revision_id,
        structured_build_id=review.structured_build_id,
        profile_revision_id=review.profile_revision_id,
        scope=review.scope,
        state=review.state,
        current=review.current,
        canonical_anchor=review.canonical_anchor,
        approved_metadata_revision_id=review.approved_metadata_revision_id,
        parser_proposal=_metadata_values_projection(review.parser_proposal),
        current_draft=_metadata_values_projection(review.current_draft),
    )


def _metadata_values_projection(review: Any) -> KnowledgeSourceMetadataValuesProjection:
    applicability = review.applicability
    precedence = review.precedence
    return KnowledgeSourceMetadataValuesProjection(
        authority=review.authority,
        effective_from=(
            None if review.effective_from is None else review.effective_from.isoformat()
        ),
        effective_to=(
            None if review.effective_to is None else review.effective_to.isoformat()
        ),
        taxonomy_id=None if applicability is None else applicability.taxonomy_id,
        taxonomy_revision_id=(
            None if applicability is None else applicability.taxonomy_revision_id
        ),
        precedence_policy_revision_id=(
            None if precedence is None else precedence.policy_revision_id
        ),
        precedence_authority_tier=(
            None if precedence is None else precedence.authority_tier
        ),
        precedence_order=None if precedence is None else precedence.order,
    )


__all__ = ["KnowledgeSourceWorkspaceQuery", "KnowledgeSourceWorkspaceService"]
