from proof_agent.control.knowledge.answer_validator import (
    GeneratedInsuranceAnswer,
    InsuranceAnswerClaim,
    validate_generated_insurance_answer,
)
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    EvidenceSlotEvaluation,
)


def _evidence() -> tuple[AdmittedInsuranceEvidence, ...]:
    return (
        AdmittedInsuranceEvidence(
            evidence_id="evidence-A",
            rule_unit_revision_id="rule-A",
            citation_uri="knowledge://source/A#page=1",
            supported_slot_ids=("governing-rule",),
        ),
    )


def test_successful_guidance_requires_every_answer_section() -> None:
    generated = GeneratedInsuranceAnswer.model_construct(
        recommendation="Product A may apply.",
        conditions="",
        assumptions="Shanghai agency channel.",
        rule_basis="Rule A.",
        warnings="Confirm underwriting.",
        service_reminder="Use the latest published version.",
        claims=(),
    )

    result = validate_generated_insurance_answer(
        generated,
        admitted_evidence=_evidence(),
        slot_evaluation=EvidenceSlotEvaluation(
            complete=True,
            satisfied_slot_ids=("governing-rule",),
            missing_slot_ids=(),
        ),
    )

    assert result.admitted is False
    assert result.reason == "missing_required_answer_section"


def test_post_generation_validator_rejects_unsupported_recommendation() -> None:
    generated = GeneratedInsuranceAnswer(
        recommendation="Product B accepts this occupation.",
        conditions="The occupation must be eligible.",
        assumptions="The supplied occupation is accurate.",
        rule_basis="Product B rule.",
        warnings="Terms may change.",
        service_reminder="Confirm before submission.",
        claims=(
            InsuranceAnswerClaim(
                section="recommendation",
                text="Product B accepts this occupation.",
                rule_unit_revision_ids=("rule-B",),
                citation_uris=("knowledge://source/B#page=1",),
            ),
            *tuple(
                InsuranceAnswerClaim(
                    section=section,
                    text=f"Supported {section} statement.",
                    rule_unit_revision_ids=("rule-A",),
                    citation_uris=("knowledge://source/A#page=1",),
                )
                for section in (
                    "conditions",
                    "assumptions",
                    "rule_basis",
                    "warnings",
                )
            ),
        ),
    )

    decision = validate_generated_insurance_answer(
        generated,
        admitted_evidence=_evidence(),
        slot_evaluation=EvidenceSlotEvaluation(
            complete=True,
            satisfied_slot_ids=("governing-rule",),
            missing_slot_ids=(),
        ),
    )

    assert decision.outcome == "no_recommendation"
    assert decision.deliverable_answer is None


def test_fully_supported_structured_answer_is_deliverable() -> None:
    sections = (
        "recommendation",
        "conditions",
        "assumptions",
        "rule_basis",
        "warnings",
    )
    generated = GeneratedInsuranceAnswer(
        recommendation="Product A may apply.",
        conditions="Shanghai eligibility conditions apply.",
        assumptions="The supplied region is Shanghai.",
        rule_basis="Rule A governs.",
        warnings="Underwriting remains required.",
        service_reminder="Confirm the current publication before submission.",
        claims=tuple(
            InsuranceAnswerClaim(
                section=section,  # type: ignore[arg-type]
                text=f"Supported {section} statement.",
                rule_unit_revision_ids=("rule-A",),
                citation_uris=("knowledge://source/A#page=1",),
            )
            for section in sections
        ),
    )

    decision = validate_generated_insurance_answer(
        generated,
        admitted_evidence=_evidence(),
        slot_evaluation=EvidenceSlotEvaluation(
            complete=True,
            satisfied_slot_ids=("governing-rule",),
            missing_slot_ids=(),
        ),
    )

    assert decision.admitted is True
    assert decision.deliverable_answer == generated
