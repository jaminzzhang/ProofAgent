"""Post-generation contract and support validation for insurance answers."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, model_validator

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.evidence import EvidenceChunk
from proof_agent.contracts.insurance_rules import InsuranceEvidenceSlotRequirement
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    EvidenceSlotEvaluation,
)


class InsuranceAnswerClaim(FrozenModel):
    section: Literal[
        "recommendation",
        "conditions",
        "assumptions",
        "rule_basis",
        "warnings",
        "service_reminder",
    ]
    text: str = Field(min_length=1)
    rule_unit_revision_ids: tuple[str, ...] = Field(min_length=1)
    citation_uris: tuple[str, ...] = Field(min_length=1)


class GeneratedInsuranceAnswer(FrozenModel):
    recommendation: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    assumptions: str = Field(min_length=1)
    rule_basis: str = Field(min_length=1)
    warnings: str = Field(min_length=1)
    service_reminder: str = Field(min_length=1)
    claims: tuple[InsuranceAnswerClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_normative_section_claims(self) -> GeneratedInsuranceAnswer:
        claimed_sections = {claim.section for claim in self.claims}
        required = {
            "recommendation",
            "conditions",
            "assumptions",
            "rule_basis",
            "warnings",
        }
        if not required.issubset(claimed_sections):
            raise ValueError("every substantive answer section requires a support claim")
        return self


class InsuranceAnswerValidationDecision(FrozenModel):
    admitted: bool
    outcome: Literal["deliver", "clarify", "conflict", "no_recommendation"]
    reason: str
    deliverable_answer: GeneratedInsuranceAnswer | None = None


def validate_generated_insurance_answer(
    generated: GeneratedInsuranceAnswer,
    *,
    admitted_evidence: tuple[AdmittedInsuranceEvidence, ...],
    slot_evaluation: EvidenceSlotEvaluation,
) -> InsuranceAnswerValidationDecision:
    sections = (
        generated.recommendation,
        generated.conditions,
        generated.assumptions,
        generated.rule_basis,
        generated.warnings,
        generated.service_reminder,
    )
    if any(not isinstance(section, str) or not section.strip() for section in sections):
        return _reject("missing_required_answer_section")
    if not slot_evaluation.complete:
        return InsuranceAnswerValidationDecision(
            admitted=False,
            outcome="clarify",
            reason="required_evidence_slots_incomplete",
        )
    admitted_rule_ids = {item.rule_unit_revision_id for item in admitted_evidence}
    admitted_citations = {
        item.citation_uri for item in admitted_evidence if item.citation_uri is not None
    }
    for claim in generated.claims:
        if not set(claim.rule_unit_revision_ids).issubset(admitted_rule_ids):
            return _reject("unsupported_rule_claim")
        if not set(claim.citation_uris).issubset(admitted_citations):
            return _reject("unsupported_citation")
    return InsuranceAnswerValidationDecision(
        admitted=True,
        outcome="deliver",
        reason="admitted",
        deliverable_answer=generated,
    )


def _reject(reason: str) -> InsuranceAnswerValidationDecision:
    return InsuranceAnswerValidationDecision(
        admitted=False,
        outcome="no_recommendation",
        reason=reason,
    )


def validate_serialized_insurance_answer(
    content: str,
    *,
    evidence: tuple[EvidenceChunk, ...],
    requirements: tuple[InsuranceEvidenceSlotRequirement, ...],
) -> InsuranceAnswerValidationDecision:
    """Parse one model output and prove claims against admitted evidence and slots."""

    try:
        payload = json.loads(content)
        generated = GeneratedInsuranceAnswer.model_validate(payload)
    except (json.JSONDecodeError, ValueError, TypeError):
        return _reject("invalid_structured_insurance_answer")
    admitted = tuple(
        AdmittedInsuranceEvidence(
            evidence_id=item.evidence_id or item.source,
            rule_unit_revision_id=item.chunk_id or item.evidence_id or item.source,
            citation_uri=item.citation,
            supported_slot_ids=item.supported_evidence_slot_ids,
        )
        for item in evidence
        if item.authority_admitted and item.supported_evidence_slot_ids
    )
    from proof_agent.control.knowledge.evidence_slots import evaluate_required_slots

    return validate_generated_insurance_answer(
        generated,
        admitted_evidence=admitted,
        slot_evaluation=evaluate_required_slots(requirements, admitted),
    )


def render_insurance_answer(answer: GeneratedInsuranceAnswer) -> str:
    return "\n\n".join(
        (
            f"Recommendation: {answer.recommendation}",
            f"Conditions: {answer.conditions}",
            f"Assumptions: {answer.assumptions}",
            f"Rule basis: {answer.rule_basis}",
            f"Warnings: {answer.warnings}",
            f"Service reminder: {answer.service_reminder}",
        )
    )


__all__ = [
    "GeneratedInsuranceAnswer",
    "InsuranceAnswerClaim",
    "InsuranceAnswerValidationDecision",
    "render_insurance_answer",
    "validate_generated_insurance_answer",
    "validate_serialized_insurance_answer",
]
