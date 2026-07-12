import json
from datetime import date, datetime

import pytest
from pydantic import ValidationError

import proof_agent.contracts as contracts
from proof_agent.contracts import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    AuthorityGateCheck,
    InsuranceEvidenceSlotRequirement,
    InsuranceRuleApplicability,
    InsuranceRuleAuthorityGateResult,
    InsuranceRuleMetadataDraft,
    InsuranceRulePrecedence,
    InsuranceRuleUnitRevision,
    ProposedInsuranceKnowledgeVisibilityScope,
    ScopeDimension,
    TaxonomyCondition,
)


def applicability() -> InsuranceRuleApplicability:
    return InsuranceRuleApplicability(
        taxonomy_id="insurance-rule-scope",
        taxonomy_revision_id="taxonomy-v3",
        conditions=(
            TaxonomyCondition(key="product_code", operator="EQ", values=("P-1",)),
            TaxonomyCondition(key="region", operator="IN", values=("CN-11", "CN-31")),
        ),
    )


def precedence() -> InsuranceRulePrecedence:
    return InsuranceRulePrecedence(
        policy_revision_id="precedence-v2",
        authority_tier="institution-exception",
        order=10,
    )


def restricted_visibility() -> ApprovedInsuranceKnowledgeVisibilityScope:
    return ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="RESTRICTED",
        institutions=ScopeDimension(mode="ALLOWLIST", values=("INST-1",)),
        regions=ScopeDimension(mode="ALL"),
        channels=ScopeDimension(mode="ALL"),
        roles=ScopeDimension(mode="ALLOWLIST", values=("specialist",)),
        business_lines=ScopeDimension(mode="ALL"),
        revision_id="visibility-v1",
    )


def valid_rule_fields() -> dict[str, object]:
    return {
        "rule_unit_revision_id": "rule-rev-1",
        "logical_rule_key": "accident-age-limit",
        "document_id": "doc-1",
        "revision_id": "doc-rev-2",
        "structured_build_id": "build-3",
        "content": "Applicants must be between 18 and 60 years old.",
        "citation_uri": "proofagent://knowledge/doc-1/revisions/doc-rev-2/pages/3",
        "metadata_revision_id": "metadata-v4",
        "visibility_scope": restricted_visibility(),
        "content_sha256": "a" * 64,
        "authority_sha256": "b" * 64,
    }


def test_restricted_visibility_requires_explicit_dimension_modes() -> None:
    with pytest.raises(ValidationError):
        ApprovedInsuranceKnowledgeVisibilityScope(
            visibility="RESTRICTED",
            institutions=ScopeDimension(mode="ALLOWLIST", values=("INST-1",)),
            revision_id="visibility-v1",
        )


def test_allowlist_requires_values_and_all_rejects_values() -> None:
    with pytest.raises(ValidationError):
        ScopeDimension(mode="ALLOWLIST", values=())
    with pytest.raises(ValidationError):
        ScopeDimension(mode="ALL", values=("unexpected",))


def test_allowlist_values_are_unique_trimmed_and_canonicalized() -> None:
    first = ScopeDimension(mode="ALLOWLIST", values=(" REGION-B ", "REGION-A"))
    second = ScopeDimension(mode="ALLOWLIST", values=("REGION-A", "REGION-B"))

    assert first.values == ("REGION-A", "REGION-B")
    assert first.model_dump_json() == second.model_dump_json()
    with pytest.raises(ValidationError):
        ScopeDimension(mode="ALLOWLIST", values=("REGION-A", " REGION-A "))


def test_public_visibility_forbids_dimension_scopes() -> None:
    with pytest.raises(ValidationError):
        ApprovedInsuranceKnowledgeVisibilityScope(
            visibility="PUBLIC",
            institutions=ScopeDimension(mode="ALL"),
            revision_id="visibility-v1",
        )

    scope = ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="PUBLIC", revision_id="visibility-v1"
    )
    assert scope.institutions is None


@pytest.mark.parametrize("unit_kind", ["document", "clause", "section", "table_row", "row_group"])
def test_rule_unit_revision_accepts_coherent_granularity(unit_kind: str) -> None:
    revision = InsuranceRuleUnitRevision(unit_kind=unit_kind, **valid_rule_fields())
    assert revision.unit_kind == unit_kind


def test_isolated_cell_cannot_be_rule_unit_kind() -> None:
    with pytest.raises(ValidationError):
        InsuranceRuleUnitRevision(unit_kind="cell", **valid_rule_fields())


def test_metadata_draft_is_explicitly_non_authoritative() -> None:
    draft = InsuranceRuleMetadataDraft(
        metadata_draft_id="draft-1",
        document_id="doc-1",
        revision_id="doc-rev-2",
        applicability=applicability(),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        authority="institution-underwriting-manual",
        precedence=precedence(),
        supersedes_rule_unit_revision_ids=("rule-rev-0",),
        proposed_visibility=ProposedInsuranceKnowledgeVisibilityScope(
            visibility="RESTRICTED",
            institutions=ScopeDimension(mode="ALLOWLIST", values=("INST-1",)),
            regions=ScopeDimension(mode="ALL"),
            channels=ScopeDimension(mode="ALL"),
            roles=ScopeDimension(mode="ALL"),
            business_lines=ScopeDimension(mode="ALL"),
        ),
    )

    assert draft.authoritative is False
    with pytest.raises(ValidationError):
        InsuranceRuleMetadataDraft(
            metadata_draft_id="draft-1",
            document_id="doc-1",
            revision_id="doc-rev-2",
            authoritative=True,
        )


def test_approved_metadata_revision_preserves_business_authority_distinctions() -> None:
    metadata = ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id="metadata-v4",
        applicability=applicability(),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        authority="institution-underwriting-manual",
        precedence=precedence(),
        supersedes_rule_unit_revision_ids=("rule-rev-0",),
    )

    assert metadata.precedence.policy_revision_id == "precedence-v2"
    assert metadata.effective_from == date(2026, 1, 1)
    with pytest.raises(ValidationError):
        ApprovedInsuranceRuleMetadataRevision(
            metadata_revision_id="metadata-v4",
            applicability=applicability(),
            effective_from=date(2027, 1, 1),
            effective_to=date(2026, 1, 1),
            authority="institution-underwriting-manual",
            precedence=precedence(),
        )


def test_business_dates_reject_datetimes_and_round_trip_iso_dates() -> None:
    metadata = ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id="metadata-v4",
        applicability=applicability(),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        authority="institution-underwriting-manual",
        precedence=precedence(),
    )

    restored = ApprovedInsuranceRuleMetadataRevision.model_validate_json(metadata.model_dump_json())
    assert restored.effective_from == date(2026, 1, 1)
    assert json.loads(metadata.model_dump_json())["effective_from"] == "2026-01-01"

    for field in ("effective_from", "effective_to"):
        values = metadata.model_dump()
        values[field] = datetime(2026, 1, 1, 0, 0, 0)
        with pytest.raises(ValidationError):
            ApprovedInsuranceRuleMetadataRevision(**values)

        json_values = metadata.model_dump(mode="json")
        json_values[field] = "2026-01-01T00:00:00"
        with pytest.raises(ValidationError):
            ApprovedInsuranceRuleMetadataRevision.model_validate_json(json.dumps(json_values))


@pytest.mark.parametrize("value", ["text", 7, True, 2.5])
def test_taxonomy_scalar_types_round_trip_without_coercion(value: object) -> None:
    condition = TaxonomyCondition(key="typed", operator="EQ", values=(value,))
    restored = TaxonomyCondition.model_validate_json(condition.model_dump_json())

    assert restored.values == (value,)
    assert type(restored.values[0]) is type(value)


@pytest.mark.parametrize(
    "values",
    [
        (float("nan"),),
        (float("inf"),),
        (float("-inf"),),
        (True, 1),
        (1, 1.0),
        ("duplicate", "duplicate"),
        (2, 2),
    ],
)
def test_taxonomy_values_reject_non_finite_mixed_or_duplicate_values(
    values: tuple[object, ...],
) -> None:
    with pytest.raises(ValidationError):
        TaxonomyCondition(key="typed", operator="IN", values=values)


def test_applicability_conditions_are_taxonomy_bound_and_deterministic() -> None:
    assert applicability().conditions[0].values == ("P-1",)
    with pytest.raises(ValidationError):
        TaxonomyCondition(key="product_code", operator="EQ", values=("P-1", "P-2"))
    with pytest.raises(ValidationError):
        TaxonomyCondition(key="product_code", operator="IN", values=())


@pytest.mark.parametrize("invalid_order", [True, "10", 10.0, 1.5])
def test_precedence_order_is_a_strict_non_negative_integer(invalid_order: object) -> None:
    with pytest.raises(ValidationError):
        InsuranceRulePrecedence(
            policy_revision_id="precedence-v2",
            authority_tier="institution-exception",
            order=invalid_order,
        )

    with pytest.raises(ValidationError):
        InsuranceRulePrecedence(
            policy_revision_id="precedence-v2",
            authority_tier="institution-exception",
            order=-1,
        )


def test_evidence_slot_supports_pre_retrieval_and_exact_rule_constraints() -> None:
    planned = InsuranceEvidenceSlotRequirement(
        slot_id="slot-product-a",
        requirement_kind="comparison_basis",
        subject_id="product-a:benefit-limit",
        scope=applicability(),
    )
    exact = InsuranceEvidenceSlotRequirement(
        slot_id="slot-clause",
        requirement_kind="requested_clause",
        subject_id="clause-4.2",
        required_rule_unit_revision_ids=("rule-rev-1",),
    )

    assert planned.required_rule_unit_revision_ids == ()
    assert exact.required_rule_unit_revision_ids == ("rule-rev-1",)


def test_identity_collections_are_unique_trimmed_and_canonicalized() -> None:
    metadata_a = InsuranceRuleMetadataDraft(
        metadata_draft_id="draft-1",
        document_id="doc-1",
        revision_id="doc-rev-2",
        supersedes_rule_unit_revision_ids=(" rule-rev-2 ", "rule-rev-1"),
    )
    metadata_b = InsuranceRuleMetadataDraft(
        metadata_draft_id="draft-1",
        document_id="doc-1",
        revision_id="doc-rev-2",
        supersedes_rule_unit_revision_ids=("rule-rev-1", "rule-rev-2"),
    )
    evidence_a = InsuranceEvidenceSlotRequirement(
        slot_id="slot-clause",
        requirement_kind="requested_clause",
        subject_id="clause-4.2",
        required_rule_unit_revision_ids=(" rule-rev-2 ", "rule-rev-1"),
    )
    evidence_b = InsuranceEvidenceSlotRequirement(
        slot_id="slot-clause",
        requirement_kind="requested_clause",
        subject_id="clause-4.2",
        required_rule_unit_revision_ids=("rule-rev-1", "rule-rev-2"),
    )

    assert metadata_a.supersedes_rule_unit_revision_ids == ("rule-rev-1", "rule-rev-2")
    assert metadata_a.model_dump_json() == metadata_b.model_dump_json()
    assert evidence_a.required_rule_unit_revision_ids == ("rule-rev-1", "rule-rev-2")
    assert evidence_a.model_dump_json() == evidence_b.model_dump_json()

    with pytest.raises(ValidationError):
        InsuranceRuleMetadataDraft(
            metadata_draft_id="draft-1",
            document_id="doc-1",
            revision_id="doc-rev-2",
            supersedes_rule_unit_revision_ids=("rule-rev-1", " rule-rev-1 "),
        )
    with pytest.raises(ValidationError):
        InsuranceEvidenceSlotRequirement(
            slot_id="slot-clause",
            requirement_kind="requested_clause",
            subject_id="clause-4.2",
            required_rule_unit_revision_ids=("rule-rev-1", " rule-rev-1 "),
        )


def passing_checks() -> tuple[AuthorityGateCheck, ...]:
    return tuple(
        AuthorityGateCheck(check=check, passed=True)
        for check in (
            "published_version",
            "visibility",
            "publication_membership",
            "effective_period",
            "applicability",
            "precedence",
            "authorization",
            "citation",
            "metadata_digest",
            "visibility_digest",
        )
    )


def test_authority_gate_pass_requires_every_required_check_to_pass() -> None:
    result = InsuranceRuleAuthorityGateResult(
        outcome="PASS",
        rule_unit_revision_id="rule-rev-1",
        checks=passing_checks(),
    )
    assert result.failure_handling is None

    failed_checks = list(passing_checks())
    failed_checks[4] = AuthorityGateCheck(
        check="applicability", passed=False, reason_code="CONDITIONS_DO_NOT_MATCH"
    )
    with pytest.raises(ValidationError):
        InsuranceRuleAuthorityGateResult(
            outcome="PASS",
            rule_unit_revision_id="rule-rev-1",
            checks=tuple(failed_checks),
        )


def test_authority_gate_failure_requires_terminal_handling_and_reason() -> None:
    failed_checks = list(passing_checks())
    failed_checks[7] = AuthorityGateCheck(
        check="citation", passed=False, reason_code="CITATION_NOT_IN_MANIFEST"
    )
    result = InsuranceRuleAuthorityGateResult(
        outcome="FAIL",
        rule_unit_revision_id="rule-rev-1",
        checks=tuple(failed_checks),
        failure_handling="no_recommendation",
    )
    assert result.checks[7].reason_code == "CITATION_NOT_IN_MANIFEST"

    with pytest.raises(ValidationError):
        AuthorityGateCheck(check="citation", passed=False)


def test_contracts_round_trip_are_frozen_and_exported() -> None:
    revision = InsuranceRuleUnitRevision(unit_kind="table_row", **valid_rule_fields())
    restored = InsuranceRuleUnitRevision.model_validate_json(revision.model_dump_json())
    payload = json.loads(revision.model_dump_json())

    assert restored == revision
    assert payload["visibility_scope"]["roles"]["mode"] == "ALLOWLIST"
    with pytest.raises(ValidationError):
        revision.content = "changed"

    expected = {
        "ApprovedInsuranceKnowledgeVisibilityScope",
        "ApprovedInsuranceRuleMetadataRevision",
        "AuthorityGateCheck",
        "InsuranceEvidenceSlotRequirement",
        "InsuranceRuleApplicability",
        "InsuranceRuleAuthorityGateResult",
        "InsuranceRuleMetadataDraft",
        "InsuranceRulePrecedence",
        "InsuranceRuleUnitRevision",
        "ProposedInsuranceKnowledgeVisibilityScope",
        "ScopeDimension",
        "TaxonomyCondition",
    }
    assert expected <= set(contracts.__all__)
    assert all(hasattr(contracts, name) for name in expected)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("rule_unit_revision_id", " "),
        ("logical_rule_key", ""),
        ("document_id", "\t"),
        ("structured_build_id", " "),
        ("citation_uri", ""),
        ("content_sha256", "A" * 64),
        ("authority_sha256", "not-a-digest"),
    ],
)
def test_rule_unit_revision_rejects_invalid_authority_identity(field: str, invalid: object) -> None:
    values = valid_rule_fields()
    values[field] = invalid
    with pytest.raises(ValidationError):
        InsuranceRuleUnitRevision(unit_kind="document", **values)
