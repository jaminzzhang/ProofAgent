"""Required insurance evidence-slot completeness checks."""

from __future__ import annotations

from pydantic import Field, model_validator

from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.insurance_rules import InsuranceEvidenceSlotRequirement


class AdmittedInsuranceEvidence(FrozenModel):
    evidence_id: str = Field(min_length=1)
    rule_unit_revision_id: str = Field(min_length=1)
    citation_uri: str | None = None
    supported_slot_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_slots(self) -> AdmittedInsuranceEvidence:
        if len(self.supported_slot_ids) != len(set(self.supported_slot_ids)):
            raise ValueError("supported evidence slot ids must be unique")
        return self


class EvidenceSlotEvaluation(FrozenModel):
    complete: bool
    satisfied_slot_ids: tuple[str, ...]
    missing_slot_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_partition(self) -> EvidenceSlotEvaluation:
        if set(self.satisfied_slot_ids).intersection(self.missing_slot_ids):
            raise ValueError("satisfied and missing evidence slots must be disjoint")
        if self.complete != (not self.missing_slot_ids):
            raise ValueError("slot completeness must match missing slots")
        return self


def evaluate_required_slots(
    requirements: tuple[InsuranceEvidenceSlotRequirement, ...],
    evidence: tuple[AdmittedInsuranceEvidence, ...],
) -> EvidenceSlotEvaluation:
    satisfied: list[str] = []
    missing: list[str] = []
    for requirement in requirements:
        matching = tuple(
            item for item in evidence if requirement.slot_id in item.supported_slot_ids
        )
        exact = set(requirement.required_rule_unit_revision_ids)
        if matching and (
            not exact or exact.issubset({item.rule_unit_revision_id for item in matching})
        ):
            satisfied.append(requirement.slot_id)
        else:
            missing.append(requirement.slot_id)
    return EvidenceSlotEvaluation(
        complete=not missing,
        satisfied_slot_ids=tuple(satisfied),
        missing_slot_ids=tuple(missing),
    )


__all__ = [
    "AdmittedInsuranceEvidence",
    "EvidenceSlotEvaluation",
    "evaluate_required_slots",
]
