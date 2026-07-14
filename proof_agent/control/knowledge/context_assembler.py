"""Bounded prompt payload assembly from authority-admitted insurance evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, field_validator

from proof_agent.contracts._base import FrozenDict, FrozenModel, freeze_value
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    EvidenceSlotEvaluation,
)


class InsuranceEvidenceContent(FrozenModel):
    evidence: AdmittedInsuranceEvidence
    content: str = Field(min_length=1)


class InsuranceModelContext(FrozenModel):
    evidence: tuple[InsuranceEvidenceContent, ...] = Field(min_length=1)
    normalized_conditions: Mapping[str, str] = Field(default_factory=FrozenDict)
    assumptions: tuple[str, ...]
    required_answer_sections: tuple[str, ...]
    character_count: int = Field(gt=0)

    @field_validator("normalized_conditions", mode="after")
    @classmethod
    def freeze_conditions(cls, value: Any) -> Any:
        return freeze_value(value)


def assemble_insurance_model_context(
    *,
    evidence: tuple[InsuranceEvidenceContent, ...],
    slot_evaluation: EvidenceSlotEvaluation,
    normalized_conditions: Mapping[str, str],
    assumptions: tuple[str, ...] = (),
    max_characters: int = 40_000,
) -> InsuranceModelContext:
    if not slot_evaluation.complete:
        raise ValueError("model context requires complete insurance evidence slots")
    admitted_ids = {item.evidence.evidence_id for item in evidence}
    if len(admitted_ids) != len(evidence):
        raise ValueError("model context evidence identities must be unique")
    selected: list[InsuranceEvidenceContent] = []
    count = 0
    for item in evidence:
        if count + len(item.content) > max_characters:
            break
        selected.append(item)
        count += len(item.content)
    if not selected:
        raise ValueError("model context budget cannot admit any authority evidence")
    return InsuranceModelContext(
        evidence=tuple(selected),
        normalized_conditions=normalized_conditions,
        assumptions=assumptions,
        required_answer_sections=(
            "recommendation",
            "conditions",
            "assumptions",
            "rule_basis",
            "warnings",
            "service_reminder",
        ),
        character_count=count,
    )


__all__ = [
    "InsuranceEvidenceContent",
    "InsuranceModelContext",
    "assemble_insurance_model_context",
]
