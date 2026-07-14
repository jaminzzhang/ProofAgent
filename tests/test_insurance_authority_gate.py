from __future__ import annotations

from datetime import date

import pytest

from proof_agent.contracts import InstitutionAuthorizationContext
from proof_agent.control.knowledge.insurance_authority import (
    InsuranceAuthorityCandidate,
    InsuranceAuthorityContext,
    evaluate_insurance_authority,
)


def _context() -> InsuranceAuthorityContext:
    return InsuranceAuthorityContext(
        source_id="source-1",
        index_generation_id="generation-1",
        index_uuid="uuid-1",
        source_publication_seq=7,
        as_of_date=date(2026, 7, 14),
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("SHANGHAI",),
        ),
        normalized_conditions={"region": "SHANGHAI", "product": "PRODUCT-A"},
    )


def _candidate(**updates: object) -> InsuranceAuthorityCandidate:
    values: dict[str, object] = {
        "rule_unit_revision_id": "rule-1",
        "source_id": "source-1",
        "index_generation_id": "generation-1",
        "index_uuid": "uuid-1",
        "publication_seq_from": 1,
        "publication_seq_to": None,
        "visibility": "RESTRICTED",
        "allowed_institutions": ("INST-1",),
        "allowed_regions": ("SHANGHAI",),
        "allowed_channels": (),
        "allowed_roles": (),
        "allowed_business_lines": (),
        "effective_from": date(2026, 1, 1),
        "effective_to": date(2026, 12, 31),
        "applicability_conditions": {"region": "SHANGHAI", "product": "PRODUCT-A"},
        "precedence_conflict": False,
        "citation_uri": "knowledge://source/source-1/document/doc-1/revision/rev-1#page=1",
        "manifest_citation_uri": (
            "knowledge://source/source-1/document/doc-1/revision/rev-1#page=1"
        ),
        "metadata_digest_valid": True,
        "visibility_digest_valid": True,
        "manifest_digest_valid": True,
    }
    values.update(updates)
    return InsuranceAuthorityCandidate.model_validate(values)


@pytest.mark.parametrize(
    ("failure", "updates", "outcome"),
    (
        ("wrong_version", {"index_generation_id": "generation-old"}, "no_recommendation"),
        (
            "outside_effective_period",
            {"effective_from": date(2027, 1, 1), "effective_to": None},
            "no_recommendation",
        ),
        ("acl_mismatch", {"allowed_institutions": ("INST-2",)}, "no_recommendation"),
        ("precedence_conflict", {"precedence_conflict": True}, "conflict"),
        ("bad_citation", {"manifest_citation_uri": "knowledge://wrong"}, "no_recommendation"),
    ),
)
def test_authority_failure_never_returns_advisory_answer(
    failure: str,
    updates: dict[str, object],
    outcome: str,
) -> None:
    _ = failure
    decision = evaluate_insurance_authority(_candidate(**updates), _context())

    assert decision.admitted is False
    assert decision.outcome == outcome


def test_authority_gate_passes_only_after_all_checks_in_fixed_order() -> None:
    decision = evaluate_insurance_authority(_candidate(), _context())

    assert decision.admitted is True
    assert tuple(check.check for check in decision.gate_result.checks) == (
        "published_version",
        "metadata_digest",
        "visibility_digest",
        "publication_membership",
        "visibility",
        "authorization",
        "effective_period",
        "applicability",
        "precedence",
        "citation",
    )
