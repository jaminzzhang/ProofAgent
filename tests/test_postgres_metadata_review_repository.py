from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataProfileRevision,
    InsuranceMetadataProfileValue,
    MetadataReviewConflictError,
    create_insurance_metadata_review_set,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import KnowledgeSource, KnowledgeSourceLifecycleState
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_postgres_metadata_review_v2_profile_save_and_approval(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"ks_{uuid4().hex}"
    document_id = str(uuid4())
    revision_id = str(uuid4())
    now = datetime(2026, 8, 8, tzinfo=UTC)
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        authority_values=(
            InsuranceMetadataProfileValue(
                code="national",
                label="National authority",
            ),
        ),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
        precedence_authority_tier_values=(
            InsuranceMetadataProfileValue(
                code="policy_terms",
                label="Policy terms",
            ),
        ),
    )
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
        bundle.metadata_reviews.publish_profile(
            profile,
            display_name="Insurance authority",
            actor="profile-publisher",
            published_at=now,
        )
        bundle.metadata_reviews.bind_source_profile(
            source_id=source_id,
            profile_revision_id=profile.profile_revision_id,
            actor="source-editor",
            bound_at=now,
            production=True,
        )
        review_set = create_insurance_metadata_review_set(
            source_id=source_id,
            structured_build_id="build-1",
            profile=profile,
            document_default=InsuranceRuleMetadataDraft(
                metadata_draft_id="document-default-proposal",
                document_id=document_id,
                revision_id=revision_id,
            ),
            parser_proposals=(),
        )
        assert bundle.metadata_reviews.put_review_set(review_set) == review_set
        review = review_set.reviews[0]

        saved = bundle.metadata_reviews.save_draft(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            actor="source-editor",
            reason="Confirmed current national catalogue values.",
            changes={
                "authority": "national",
                "taxonomy_id": profile.taxonomy_id,
                "taxonomy_revision_id": profile.taxonomy_revision_id,
                "precedence_policy_revision_id": profile.precedence_policy_revision_id,
                "precedence_authority_tier": "policy_terms",
                "precedence_order": 10,
            },
        )
        approved = bundle.metadata_reviews.approve(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review.review_id,
            expected_review_version=saved.review.review_version,
            expected_review_identity=saved.review.review_identity,
            actor="reviewer-1",
            reason="Approved against the signed product catalogue.",
        )

        persisted = bundle.metadata_reviews.get_current_review_set(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        assert persisted is not None
        assert persisted.generation == 3
        assert persisted.reviews[0] == approved.review
        assert approved.review.state == "approved"
        page = bundle.metadata_reviews.list_page(
            source_id,
            limit=50,
            cursor=None,
        )
        assert page.items == (approved.review,)
        assert page.summary.total == 1
        assert page.summary.approved == 1
        assert page.summary.unresolved == 0
        assert page.summary.all_approved is True

        replacement_revision_id = str(uuid4())
        replacement_set = create_insurance_metadata_review_set(
            source_id=source_id,
            structured_build_id="build-2",
            profile=profile,
            document_default=InsuranceRuleMetadataDraft(
                metadata_draft_id="replacement-document-default-proposal",
                document_id=document_id,
                revision_id=replacement_revision_id,
            ),
            parser_proposals=(),
        )
        bundle.metadata_reviews.put_review_set(replacement_set)

        assert bundle.metadata_reviews.get_current_review_set(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        ) is None
        replacement_page = bundle.metadata_reviews.list_page(
            source_id,
            limit=50,
            cursor=None,
        )
        assert replacement_page.items == replacement_set.reviews
        assert replacement_page.summary.total == 1
        assert replacement_page.summary.needs_input == 1
    finally:
        bundle.close()


def test_postgres_metadata_review_v2_rejection_is_exact_and_terminal(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    suffix = uuid4().hex
    source_id = f"ks_{suffix}"
    document_id = str(uuid4())
    revision_id = str(uuid4())
    now = datetime(2026, 8, 8, tzinfo=UTC)
    profile = InsuranceMetadataProfileRevision(
        profile_id=f"insurance-authority-{suffix}",
        profile_revision_id=f"insurance-authority-{suffix}.v1",
        authority_codes=("national",),
        authority_values=(
            InsuranceMetadataProfileValue(
                code="national",
                label="National authority",
            ),
        ),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
        precedence_authority_tier_values=(
            InsuranceMetadataProfileValue(
                code="policy_terms",
                label="Policy terms",
            ),
        ),
    )
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Unsupported insurance terms",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=str(uuid4()),
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        bundle.metadata_reviews.publish_profile(
            profile,
            display_name="Insurance authority",
            actor="profile-publisher",
            published_at=now,
        )
        bundle.metadata_reviews.bind_source_profile(
            source_id=source_id,
            profile_revision_id=profile.profile_revision_id,
            actor="source-editor",
            bound_at=now,
            production=True,
        )
        review_set = create_insurance_metadata_review_set(
            source_id=source_id,
            structured_build_id="build-rejected",
            profile=profile,
            document_default=InsuranceRuleMetadataDraft(
                metadata_draft_id="document-default-proposal",
                document_id=document_id,
                revision_id=revision_id,
            ),
            parser_proposals=(),
        )
        bundle.metadata_reviews.put_review_set(review_set)
        review = review_set.reviews[0]

        rejected = bundle.metadata_reviews.reject(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            review_id=review.review_id,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            actor="reviewer-1",
            reason="The document does not establish a supported authority.",
        )

        persisted = bundle.metadata_reviews.get_current_review_set(
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
        )
        assert persisted is not None
        assert persisted.generation == 2
        assert persisted.reviews == (rejected.review,)
        assert rejected.review.state == "rejected"
        assert rejected.decision.action == "reject"
        page = bundle.metadata_reviews.list_page(source_id, limit=50, cursor=None)
        assert page.summary.rejected == 1
        assert page.summary.unresolved == 1
        with pytest.raises(MetadataReviewConflictError, match="terminal"):
            bundle.metadata_reviews.reject(
                source_id=source_id,
                document_id=document_id,
                revision_id=revision_id,
                review_id=review.review_id,
                expected_review_version=rejected.review.review_version,
                expected_review_identity=rejected.review.review_identity,
                actor="reviewer-1",
                reason="Attempted terminal mutation.",
            )
    finally:
        bundle.close()
