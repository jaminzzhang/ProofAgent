from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.workbook import (
    InsuranceMetadataDraftInput,
    WorkbookImportRecord,
    WorkbookImportRowIdentity,
    WorkbookMetadataRow,
    WorkbookReviewConflictError,
    reconcile_metadata_drafts,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import KnowledgeSource, KnowledgeSourceLifecycleState
from proof_agent.contracts.insurance_rules import (
    InsuranceRuleApplicability,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _ref(name: str, media_type: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/{name}",
        version_id=f"opaque-{name}",
        sha256="a" * 64,
        size_bytes=100,
        media_type=media_type,
    )


def test_postgres_metadata_review_pagination_and_optimistic_decision(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"ks_{uuid4().hex}"
    document_id = str(uuid4())
    revision_id = str(uuid4())
    now = datetime(2026, 7, 15, tzinfo=UTC)
    metadata = {
        "authority": "national",
        "taxonomy_id": "insurance-product",
        "taxonomy_revision_id": "taxonomy-v1",
        "precedence_policy_revision_id": "precedence-v1",
        "precedence_authority_tier": "terms",
        "precedence_order": 10,
    }
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Insurance terms",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=str(uuid4()),
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        pdf = InsuranceMetadataDraftInput(
            metadata_draft_id="pdf-draft-1",
            origin="pdf",
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            canonical_anchor="section:eligibility",
            **metadata,
        )
        workbook = InsuranceMetadataDraftInput(
            metadata_draft_id="workbook-draft-1",
            origin="workbook",
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            canonical_anchor="section:eligibility",
            **metadata,
        )
        import_record = WorkbookImportRecord(
            import_id="metadata-import-1",
            template_revision="insurance-rule-metadata.v1",
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            created_by="operator-1",
            created_at=now,
            original_ref=_ref(
                "workbook.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            normalized_ref=_ref("workbook.json", "application/json"),
            rows=(
                WorkbookImportRowIdentity(
                    row_number=2,
                    source_id=source_id,
                    document_id=document_id,
                    revision_id=revision_id,
                    canonical_anchor="section:eligibility",
                    metadata_draft_id=workbook.metadata_draft_id,
                ),
            ),
        )
        row = WorkbookMetadataRow(
            row_number=2,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            canonical_anchor="section:eligibility",
            metadata=InsuranceRuleMetadataDraft(
                metadata_draft_id=workbook.metadata_draft_id,
                document_id=document_id,
                revision_id=revision_id,
                authority="national",
                applicability=InsuranceRuleApplicability(
                    taxonomy_id="insurance-product",
                    taxonomy_revision_id="taxonomy-v1",
                ),
                precedence=InsuranceRulePrecedence(
                    policy_revision_id="precedence-v1",
                    authority_tier="terms",
                    order=10,
                ),
            ),
        )
        review = reconcile_metadata_drafts(
            pdf,
            workbook,
            import_record=import_record,
            row=row,
        )

        assert bundle.metadata_reviews.put(review) == review
        assert bundle.metadata_reviews.put(review) == review
        page = bundle.metadata_reviews.list_page(source_id, limit=1)
        assert page.items == (review,)
        assert page.summary.ready_for_review == 1
        approved = bundle.metadata_reviews.resolve(
            source_id=source_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            action="approve",
            actor="approver-1",
            reason="Checked against the signed product filing.",
        )
        assert approved.state == "approved"
        assert approved.publication_blocked is False
        assert bundle.metadata_reviews.list_page(source_id).summary.all_approved is True
        with pytest.raises(WorkbookReviewConflictError):
            bundle.metadata_reviews.resolve(
                source_id=source_id,
                review_id=review.review_id,
                expected_review_version=review.review_version,
                expected_review_identity=review.review_identity,
                action="reject",
                actor="stale-operator",
                reason="Stale command.",
            )
    finally:
        bundle.close()
