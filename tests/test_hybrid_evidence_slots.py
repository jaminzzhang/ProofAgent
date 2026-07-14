from proof_agent.contracts import InsuranceEvidenceSlotRequirement
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    evaluate_required_slots,
)


def test_comparison_requires_both_product_evidence_slots() -> None:
    requirements = (
        InsuranceEvidenceSlotRequirement(
            slot_id="product:A", requirement_kind="comparison_basis", subject_id="A"
        ),
        InsuranceEvidenceSlotRequirement(
            slot_id="product:B", requirement_kind="comparison_basis", subject_id="B"
        ),
    )
    evidence = (
        AdmittedInsuranceEvidence(
            evidence_id="evidence-A",
            rule_unit_revision_id="rule-A",
            supported_slot_ids=("product:A",),
        ),
    )

    result = evaluate_required_slots(requirements, evidence)

    assert result.complete is False
    assert result.missing_slot_ids == ("product:B",)


def test_exact_rule_requirement_cannot_be_satisfied_by_another_rule() -> None:
    requirement = InsuranceEvidenceSlotRequirement(
        slot_id="clause:4.2",
        requirement_kind="requested_clause",
        subject_id="4.2",
        required_rule_unit_revision_ids=("rule-exact",),
    )

    result = evaluate_required_slots(
        (requirement,),
        (
            AdmittedInsuranceEvidence(
                evidence_id="evidence-other",
                rule_unit_revision_id="rule-other",
                supported_slot_ids=("clause:4.2",),
            ),
        ),
    )

    assert result.complete is False
