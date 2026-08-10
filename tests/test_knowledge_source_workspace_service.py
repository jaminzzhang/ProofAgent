"""Focused tests for Source workspace projections and review authority."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataReviewV2,
)
from proof_agent.control.knowledge.application import (
    KnowledgeSourceCommandContext,
    KnowledgeSourceCommandRejectedError,
)
from proof_agent.control.knowledge.workspace_service import (
    KnowledgeSourceWorkspaceService,
)
from proof_agent.contracts import Permission
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft


class _Knowledge:
    def get_source_record(self, source_id: str) -> object | None:
        return object() if source_id == "ks_hybrid" else None


class _Query:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"query should not be called: {name}")


class _Reviews:
    def __init__(self) -> None:
        self.resolved = False
        self.saved = False
        self.rejected = False

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
                needs_input=1,
                ready_for_approval=0,
                approved=0,
                rejected=0,
            ),
        )

    def approve(self, **kwargs: Any) -> Any:
        assert kwargs["document_id"] == "doc_1"
        assert kwargs["revision_id"] == "rev_1"
        self.resolved = True
        return SimpleNamespace(review=_review(state="approved"))

    def save_draft(self, **kwargs: Any) -> Any:
        assert kwargs["changes"] == {"authority": "national"}
        self.saved = True
        return SimpleNamespace(review=_review(state="ready_for_approval"))

    def reject(self, **kwargs: Any) -> Any:
        assert kwargs["document_id"] == "doc_1"
        assert kwargs["revision_id"] == "rev_1"
        self.rejected = True
        return SimpleNamespace(review=_review(state="rejected"))

    def get_bound_profile(self, source_id: str, *, production: bool = False) -> Any:
        del source_id, production
        return SimpleNamespace(
            profile_id="insurance-authority",
            profile_revision_id="insurance-authority.v1",
            reference_only=False,
            authority_values=(
                SimpleNamespace(code="national", label="National authority"),
            ),
            taxonomy_id="insurance-product-applicability",
            taxonomy_revision_id="taxonomy-2026-01",
            precedence_policy_revision_id="precedence-2026-01",
            precedence_authority_tier_values=(
                SimpleNamespace(code="policy_terms", label="Policy terms"),
            ),
        )


def _review(
    *,
    state: str = "needs_input",
) -> InsuranceMetadataReviewV2:
    draft = InsuranceRuleMetadataDraft(
        metadata_draft_id="draft-1",
        document_id="doc_1",
        revision_id="rev_1",
    )
    return InsuranceMetadataReviewV2(
        review_id="review_1",
        review_identity="a" * 64,
        review_version=1,
        source_id="ks_hybrid",
        document_id="doc_1",
        revision_id="rev_1",
        structured_build_id="build_1",
        profile_revision_id="insurance-authority.v1",
        scope="document_default",
        canonical_anchor=None,
        state=state,
        current=True,
        parser_proposal=draft,
        current_draft=draft,
        approved_metadata_revision_id=None,
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
    assert page.data[0].scope == "document_default"
    assert page.data[0].profile_revision_id == "insurance-authority.v1"
    assert page.data[0].current is True
    assert page.data[0].state == "needs_input"
    assert page.summary["unresolved"] == 1
    assert "original_ref" not in str(page.model_dump(mode="json"))
    with pytest.raises(KnowledgeSourceCommandRejectedError, match="view"):
        service.reviews(
            source_id="ks_hybrid",
            context=_context(),
            limit=50,
            cursor=None,
        )


def test_review_approval_uses_distinct_review_permission() -> None:
    reviews = _Reviews()
    service = KnowledgeSourceWorkspaceService(
        knowledge=_Knowledge(),
        query=_Query(),
        reviews=reviews,
    )

    with pytest.raises(KnowledgeSourceCommandRejectedError, match="review"):
        service.approve_review(
            source_id="ks_hybrid",
            document_id="doc_1",
            revision_id="rev_1",
            review_id="review_1",
            expected_review_version=1,
            expected_review_identity="a" * 64,
            actor="operator-1",
            reason="Reviewed against policy.",
            context=_context(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
                Permission.KNOWLEDGE_SOURCE_PUBLISH,
            ),
        )

    projection = service.approve_review(
        source_id="ks_hybrid",
        document_id="doc_1",
        revision_id="rev_1",
        review_id="review_1",
        expected_review_version=1,
        expected_review_identity="a" * 64,
        actor="operator-1",
        reason="Reviewed against policy.",
        context=_context(
            Permission.KNOWLEDGE_SOURCE_VIEW,
            Permission.KNOWLEDGE_SOURCE_REVIEW,
        ),
    )
    assert reviews.resolved is True
    assert projection.state == "approved"


def test_save_review_draft_uses_edit_permission() -> None:
    reviews = _Reviews()
    service = KnowledgeSourceWorkspaceService(
        knowledge=_Knowledge(),
        query=_Query(),
        reviews=reviews,
    )

    with pytest.raises(KnowledgeSourceCommandRejectedError, match="edit"):
        service.save_review_draft(
            source_id="ks_hybrid",
            document_id="doc_1",
            revision_id="rev_1",
            review_id="review_1",
            expected_review_version=1,
            expected_review_identity="a" * 64,
            actor="operator-1",
            reason="Confirmed authority.",
            changes={"authority": "national"},
            context=_context(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_REVIEW,
            ),
        )

    projection = service.save_review_draft(
        source_id="ks_hybrid",
        document_id="doc_1",
        revision_id="rev_1",
        review_id="review_1",
        expected_review_version=1,
        expected_review_identity="a" * 64,
        actor="operator-1",
        reason="Confirmed authority.",
        changes={"authority": "national"},
        context=_context(
            Permission.KNOWLEDGE_SOURCE_VIEW,
            Permission.KNOWLEDGE_SOURCE_EDIT,
        ),
    )
    assert reviews.saved is True
    assert projection.state == "ready_for_approval"


def test_review_rejection_uses_distinct_review_permission_and_exact_revision() -> None:
    reviews = _Reviews()
    service = KnowledgeSourceWorkspaceService(
        knowledge=_Knowledge(),
        query=_Query(),
        reviews=reviews,
    )

    with pytest.raises(KnowledgeSourceCommandRejectedError, match="review"):
        service.reject_review(
            source_id="ks_hybrid",
            document_id="doc_1",
            revision_id="rev_1",
            review_id="review_1",
            expected_review_version=1,
            expected_review_identity="a" * 64,
            actor="operator-1",
            reason="Unsupported authority assertion.",
            context=_context(
                Permission.KNOWLEDGE_SOURCE_VIEW,
                Permission.KNOWLEDGE_SOURCE_EDIT,
            ),
        )

    projection = service.reject_review(
        source_id="ks_hybrid",
        document_id="doc_1",
        revision_id="rev_1",
        review_id="review_1",
        expected_review_version=1,
        expected_review_identity="a" * 64,
        actor="operator-1",
        reason="Unsupported authority assertion.",
        context=_context(
            Permission.KNOWLEDGE_SOURCE_VIEW,
            Permission.KNOWLEDGE_SOURCE_REVIEW,
        ),
    )

    assert reviews.rejected is True
    assert projection.state == "rejected"
