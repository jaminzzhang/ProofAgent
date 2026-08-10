from __future__ import annotations

import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    FilesystemInsuranceMetadataReviewV2Repository,
    InsuranceMetadataProfileRevision,
    InsuranceMetadataProfileValue,
    MetadataReviewConflictError,
    MetadataReviewValidationError,
    advance_insurance_metadata_review_set,
    approved_insurance_metadata_for_anchor,
    approve_metadata_review,
    create_insurance_metadata_review_set,
    proofagent_insurance_reference_profile,
    reject_metadata_review,
    require_production_metadata_profile,
    save_metadata_review_draft,
)
from proof_agent.capabilities.knowledge.hybrid.workbook import InsuranceMetadataDraftInput
from proof_agent.contracts.insurance_rules import (
    InsuranceRuleApplicability,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
)


def test_completed_build_creates_default_and_missing_override_reviews() -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="proofagent-insurance-reference",
        profile_revision_id="proofagent-insurance-reference.v1",
        reference_only=True,
        authority_codes=("institution", "national", "provincial"),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=(
            "institution_exception",
            "policy_terms",
            "sales_rules",
            "underwriting_rules",
        ),
    )
    document_default = InsuranceRuleMetadataDraft(
        metadata_draft_id="document-default-proposal",
        document_id="document-1",
        revision_id="revision-1",
    )
    proposals = tuple(
        InsuranceMetadataDraftInput(
            metadata_draft_id=f"parser-{anchor}",
            origin="pdf",
            source_id="source-1",
            document_id="document-1",
            revision_id="revision-1",
            canonical_anchor=anchor,
        )
        for anchor in ("heading-1", "paragraph-1")
    )

    review_set = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=document_default,
        parser_proposals=proposals,
    )

    assert review_set.profile_revision_id == profile.profile_revision_id
    assert tuple(review.scope for review in review_set.reviews) == (
        "document_default",
        "rule_unit_override",
        "rule_unit_override",
    )
    assert tuple(review.canonical_anchor for review in review_set.reviews) == (
        None,
        "heading-1",
        "paragraph-1",
    )
    assert {review.state for review in review_set.reviews} == {"needs_input"}
    assert all(review.current for review in review_set.reviews)


def test_matching_rule_units_inherit_one_ready_document_default() -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )
    applicability = InsuranceRuleApplicability(
        taxonomy_id=profile.taxonomy_id,
        taxonomy_revision_id=profile.taxonomy_revision_id,
    )
    precedence = InsuranceRulePrecedence(
        policy_revision_id=profile.precedence_policy_revision_id,
        authority_tier="policy_terms",
        order=10,
    )
    document_default = InsuranceRuleMetadataDraft(
        metadata_draft_id="document-default-proposal",
        document_id="document-1",
        revision_id="revision-1",
        authority="national",
        applicability=applicability,
        precedence=precedence,
    )
    proposals = tuple(
        InsuranceMetadataDraftInput(
            metadata_draft_id=f"parser-{anchor}",
            origin="pdf",
            source_id="source-1",
            document_id="document-1",
            revision_id="revision-1",
            canonical_anchor=anchor,
            authority="national",
            taxonomy_id=applicability.taxonomy_id,
            taxonomy_revision_id=applicability.taxonomy_revision_id,
            precedence_policy_revision_id=precedence.policy_revision_id,
            precedence_authority_tier=precedence.authority_tier,
            precedence_order=precedence.order,
        )
        for anchor in ("heading-1", "paragraph-1")
    )

    review_set = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=document_default,
        parser_proposals=proposals,
    )

    assert len(review_set.reviews) == 1
    assert review_set.reviews[0].scope == "document_default"
    assert review_set.reviews[0].state == "ready_for_approval"


def test_publication_materializes_only_current_approved_v2_metadata() -> None:
    profile = proofagent_insurance_reference_profile()
    default = InsuranceRuleMetadataDraft(
        metadata_draft_id="document-default-proposal",
        document_id="document-1",
        revision_id="revision-1",
        authority="national",
        applicability=InsuranceRuleApplicability(
            taxonomy_id=profile.taxonomy_id,
            taxonomy_revision_id=profile.taxonomy_revision_id,
        ),
        precedence=InsuranceRulePrecedence(
            policy_revision_id=profile.precedence_policy_revision_id,
            authority_tier="policy_terms",
            order=10,
        ),
    )
    review_set = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=default,
        parser_proposals=(
            InsuranceMetadataDraftInput(
                metadata_draft_id="matching-heading",
                origin="pdf",
                source_id="source-1",
                document_id="document-1",
                revision_id="revision-1",
                canonical_anchor="heading-1",
                authority="national",
                taxonomy_id=profile.taxonomy_id,
                taxonomy_revision_id=profile.taxonomy_revision_id,
                precedence_policy_revision_id=(
                    profile.precedence_policy_revision_id
                ),
                precedence_authority_tier="policy_terms",
                precedence_order=10,
            ),
        ),
        canonical_anchors=("heading-1",),
    )
    with pytest.raises(MetadataReviewConflictError, match="approved"):
        approved_insurance_metadata_for_anchor(review_set, "heading-1")
    review = review_set.reviews[0]
    approved = approve_metadata_review(
        review,
        profile=profile,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        actor="reviewer-1",
        reason="Verified against signed authority.",
    )
    approved_set = advance_insurance_metadata_review_set(
        review_set,
        approved.review,
    )

    materialized = approved_insurance_metadata_for_anchor(
        approved_set,
        "heading-1",
    )

    assert materialized.metadata_revision_id == (
        approved.review.approved_metadata_revision_id
    )
    assert materialized.authority == "national"
    assert materialized.precedence.authority_tier == "policy_terms"


def test_save_draft_explicitly_advances_missing_default_to_ready() -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )
    review = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=InsuranceRuleMetadataDraft(
            metadata_draft_id="document-default-proposal",
            document_id="document-1",
            revision_id="revision-1",
        ),
        parser_proposals=(),
    ).reviews[0]

    result = save_metadata_review_draft(
        review,
        profile=profile,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        actor="operator-1",
        reason="Confirmed the national policy default.",
        changes={
            "authority": "national",
            "taxonomy_id": profile.taxonomy_id,
            "taxonomy_revision_id": profile.taxonomy_revision_id,
            "precedence_policy_revision_id": profile.precedence_policy_revision_id,
            "precedence_authority_tier": "policy_terms",
            "precedence_order": 10,
        },
    )

    assert result.review.state == "ready_for_approval"
    assert result.review.review_version == 2
    assert result.review.parser_proposal == review.parser_proposal
    assert result.review.current_draft.authority == "national"
    assert result.decision.action == "save_draft"
    assert result.decision.reason == "Confirmed the national policy default."
    assert review.state == "needs_input"


def test_ready_review_can_be_approved_against_exact_identity() -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )
    ready = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=InsuranceRuleMetadataDraft(
            metadata_draft_id="document-default-proposal",
            document_id="document-1",
            revision_id="revision-1",
            authority="national",
            applicability=InsuranceRuleApplicability(
                taxonomy_id=profile.taxonomy_id,
                taxonomy_revision_id=profile.taxonomy_revision_id,
            ),
            precedence=InsuranceRulePrecedence(
                policy_revision_id=profile.precedence_policy_revision_id,
                authority_tier="policy_terms",
                order=10,
            ),
        ),
        parser_proposals=(),
    ).reviews[0]

    result = approve_metadata_review(
        ready,
        profile=profile,
        expected_review_version=ready.review_version,
        expected_review_identity=ready.review_identity,
        actor="reviewer-1",
        reason="Approved against the current policy catalogue.",
    )

    assert result.review.state == "approved"
    assert result.review.review_version == 2
    assert result.review.approved_metadata_revision_id is not None
    assert result.decision.action == "approve"
    assert result.decision.changed_fields == ()
    assert ready.state == "ready_for_approval"


def test_current_review_can_be_rejected_with_an_immutable_exact_decision() -> None:
    profile = proofagent_insurance_reference_profile()
    current = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=InsuranceRuleMetadataDraft(
            metadata_draft_id="document-default-proposal",
            document_id="document-1",
            revision_id="revision-1",
        ),
        parser_proposals=(),
    ).reviews[0]

    result = reject_metadata_review(
        current,
        expected_review_version=current.review_version,
        expected_review_identity=current.review_identity,
        actor="reviewer-1",
        reason="The source document does not establish a governing authority.",
    )

    assert result.review.state == "rejected"
    assert result.review.review_version == current.review_version + 1
    assert result.review.approved_metadata_revision_id is None
    assert result.decision.action == "reject"
    assert result.decision.prior_review_identity == current.review_identity
    assert result.decision.resulting_review_identity == result.review.review_identity
    assert result.decision.changed_fields == ()
    with pytest.raises(MetadataReviewConflictError, match="terminal"):
        reject_metadata_review(
            result.review,
            expected_review_version=result.review.review_version,
            expected_review_identity=result.review.review_identity,
            actor="reviewer-1",
            reason="Attempted terminal mutation.",
        )


def test_review_set_materializes_parser_omissions_from_canonical_anchors() -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )
    proposal = InsuranceMetadataDraftInput(
        metadata_draft_id="parser-heading-1",
        origin="pdf",
        source_id="source-1",
        document_id="document-1",
        revision_id="revision-1",
        canonical_anchor="heading-1",
        authority="national",
        taxonomy_id=profile.taxonomy_id,
        taxonomy_revision_id=profile.taxonomy_revision_id,
        precedence_policy_revision_id=profile.precedence_policy_revision_id,
        precedence_authority_tier="policy_terms",
        precedence_order=10,
    )

    review_set = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=InsuranceRuleMetadataDraft(
            metadata_draft_id="document-default-proposal",
            document_id="document-1",
            revision_id="revision-1",
        ),
        parser_proposals=(proposal,),
        canonical_anchors=("heading-1", "paragraph-1"),
    )

    overrides = review_set.reviews[1:]
    assert tuple(review.canonical_anchor for review in overrides) == (
        "heading-1",
        "paragraph-1",
    )
    assert overrides[1].parser_proposal.authority is None
    assert overrides[1].state == "needs_input"


def test_filesystem_authority_saves_once_and_rejects_stale_replay(tmp_path) -> None:
    profile = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )
    review_set = create_insurance_metadata_review_set(
        source_id="source-1",
        structured_build_id="build-1",
        profile=profile,
        document_default=InsuranceRuleMetadataDraft(
            metadata_draft_id="document-default-proposal",
            document_id="document-1",
            revision_id="revision-1",
        ),
        parser_proposals=(),
    )
    review = review_set.reviews[0]
    changes = {
        "authority": "national",
        "taxonomy_id": profile.taxonomy_id,
        "taxonomy_revision_id": profile.taxonomy_revision_id,
        "precedence_policy_revision_id": profile.precedence_policy_revision_id,
        "precedence_authority_tier": "policy_terms",
        "precedence_order": 10,
    }
    repository = FilesystemInsuranceMetadataReviewV2Repository(tmp_path)
    repository.put_current(review_set)

    saved = repository.save_draft(
        source_id="source-1",
        document_id="document-1",
        revision_id="revision-1",
        review_id=review.review_id,
        profile=profile,
        expected_review_version=review.review_version,
        expected_review_identity=review.review_identity,
        actor="operator-1",
        reason="Confirmed the current catalogue.",
        changes=changes,
    )

    persisted = repository.get_current(
        source_id="source-1",
        document_id="document-1",
        revision_id="revision-1",
    )
    assert persisted is not None
    assert persisted.generation == 2
    assert persisted.reviews[0] == saved.review
    with pytest.raises(MetadataReviewConflictError, match="changed"):
        repository.save_draft(
            source_id="source-1",
            document_id="document-1",
            revision_id="revision-1",
            review_id=review.review_id,
            profile=profile,
            expected_review_version=review.review_version,
            expected_review_identity=review.review_identity,
            actor="operator-2",
            reason="Stale offline save.",
            changes=changes,
        )


def test_production_rejects_the_local_reference_profile() -> None:
    with pytest.raises(MetadataReviewValidationError, match="reference-only"):
        require_production_metadata_profile(proofagent_insurance_reference_profile())


def test_production_profile_requires_labels_for_every_governed_code() -> None:
    unlabeled = InsuranceMetadataProfileRevision(
        profile_id="insurance-authority",
        profile_revision_id="insurance-authority.v1",
        authority_codes=("national",),
        taxonomy_id="insurance-product-applicability",
        taxonomy_revision_id="taxonomy-2026-01",
        precedence_policy_revision_id="precedence-2026-01",
        precedence_authority_tiers=("policy_terms",),
    )

    with pytest.raises(MetadataReviewValidationError, match="labels"):
        require_production_metadata_profile(unlabeled)

    labeled = unlabeled.model_copy(
        update={
            "authority_values": (
                InsuranceMetadataProfileValue(
                    code="national",
                    label="National authority",
                ),
            ),
            "precedence_authority_tier_values": (
                InsuranceMetadataProfileValue(
                    code="policy_terms",
                    label="Policy terms",
                ),
            ),
        }
    )
    assert require_production_metadata_profile(labeled) == labeled
