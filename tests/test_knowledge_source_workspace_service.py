"""Focused tests for Source workspace projections and review authority."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.hybrid.workbook import InsuranceMetadataReview
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.control.knowledge.workspace_service import (
    KnowledgeSourceWorkspaceService,
)
from proof_agent.contracts import Permission


class _Knowledge:
    def get_source_record(self, source_id: str) -> object | None:
        return object() if source_id == "ks_hybrid" else None


class _Query:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"query should not be called: {name}")


class _Reviews:
    def __init__(self) -> None:
        self.resolved = False

    def list_page(
        self,
        source_id: str,
        *,
        limit: int,
        cursor: str | None,
        state: str | None = None,
        import_id: str | None = None,
    ) -> Any:
        del source_id, limit, cursor, state, import_id
        return SimpleNamespace(
            items=(_review(),),
            next_cursor=None,
            summary=SimpleNamespace(
                total=1,
                unresolved=1,
                review_required=1,
                ready_for_review=0,
                approved=0,
                corrected=0,
                rejected=0,
            ),
        )

    def resolve(self, **kwargs: Any) -> InsuranceMetadataReview:
        assert kwargs["action"] == "approve"
        self.resolved = True
        return _review(state="approved", publication_blocked=False)


def _review(
    *,
    state: str = "review_required",
    publication_blocked: bool = True,
) -> InsuranceMetadataReview:
    return InsuranceMetadataReview.model_construct(
        review_id="review_1",
        review_identity="a" * 64,
        review_version=1,
        import_id="import_1",
        workbook_row_number=2,
        workbook_draft_id="draft_1",
        source_id="ks_hybrid",
        document_id="doc_1",
        revision_id="rev_1",
        canonical_anchor="anchor_1",
        citation_uri="proof://knowledge/ks_hybrid/doc_1",
        state=state,
        publication_blocked=publication_blocked,
        conflicts=(),
        resolved_values={},
        resolution_reason=None,
        resolved_by=None,
        approved_metadata_revision_id=None,
        decision_history=(),
    )


def _context(*permissions: Permission) -> KnowledgeSourceCommandContext:
    return KnowledgeSourceCommandContext(
        operator_subject="operator-1",
        permissions=permissions,
    )


def test_review_page_is_safe_and_requires_source_view() -> None:
    service = KnowledgeSourceWorkspaceService(
        knowledge=_Knowledge(),
        query=_Query(),
        reviews=_Reviews(),
    )

    page = service.reviews(
        source_id="ks_hybrid",
        context=_context(Permission.KNOWLEDGE_SOURCE_VIEW),
        limit=50,
        cursor=None,
    )

    assert page.data[0].review_id == "review_1"
    assert page.summary["unresolved"] == 1
    assert "original_ref" not in str(page.model_dump(mode="json"))
    with pytest.raises(KnowledgeSourceCommandRejectedError, match="view"):
        service.reviews(
            source_id="ks_hybrid",
            context=_context(),
            limit=50,
            cursor=None,
        )


def test_review_resolution_uses_distinct_review_permission() -> None:
    reviews = _Reviews()
    service = KnowledgeSourceWorkspaceService(
        knowledge=_Knowledge(),
        query=_Query(),
        reviews=reviews,
    )

    with pytest.raises(KnowledgeSourceCommandRejectedError, match="review"):
        service.resolve_review(
            source_id="ks_hybrid",
            review_id="review_1",
            expected_review_version=1,
            expected_review_identity="a" * 64,
            action="approve",
            actor="operator-1",
            reason="Reviewed against policy.",
            corrections={},
            context=_context(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
                Permission.KNOWLEDGE_SOURCE_PUBLISH,
            ),
        )

    projection = service.resolve_review(
        source_id="ks_hybrid",
        review_id="review_1",
        expected_review_version=1,
        expected_review_identity="a" * 64,
        action="approve",
        actor="operator-1",
        reason="Reviewed against policy.",
        corrections={},
        context=_context(
            Permission.KNOWLEDGE_SOURCE_VIEW,
            Permission.KNOWLEDGE_SOURCE_REVIEW,
        ),
    )
    assert reviews.resolved is True
    assert projection.state == "approved"
