from __future__ import annotations

from datetime import date

from proof_agent.contracts import InstitutionAuthorizationContext
from proof_agent.control.knowledge.context_expansion import (
    ExpansionCandidateMetadata,
    ExpansionSeed,
    expand_context,
)
from proof_agent.control.knowledge.context_assembler import (
    InsuranceEvidenceContent,
    assemble_insurance_model_context,
)
from proof_agent.control.knowledge.evidence_slots import (
    AdmittedInsuranceEvidence,
    EvidenceSlotEvaluation,
)
import pytest


class _RecordingRuleStore:
    unauthorized_content_reads = 0

    def expansion_metadata(self, seed: ExpansionSeed) -> tuple[ExpansionCandidateMetadata, ...]:
        _ = seed
        return (
            ExpansionCandidateMetadata(
                rule_unit_revision_id="definition-inst-2",
                source_id="source-1",
                source_publication_seq_from=1,
                source_publication_seq_to=None,
                visibility="RESTRICTED",
                allowed_institutions=("INST-2",),
                effective_from=date(2026, 1, 1),
                effective_to=None,
                applicability_conditions={},
                expansion_kind="definition",
            ),
        )

    def load_content(self, rule_unit_revision_ids: tuple[str, ...]) -> dict[str, str]:
        if "definition-inst-2" in rule_unit_revision_ids:
            self.unauthorized_content_reads += 1
        return {item: "restricted" for item in rule_unit_revision_ids}


def test_context_expansion_does_not_read_unauthorized_definition() -> None:
    store = _RecordingRuleStore()
    expanded = expand_context(
        ExpansionSeed(
            rule_unit_revision_id="selected-rule",
            source_id="source-1",
            source_publication_seq=7,
            as_of_date=date(2026, 7, 14),
            authorization=InstitutionAuthorizationContext(institutions=("INST-1",)),
            normalized_conditions={},
            allowed_expansion_kinds=("definition",),
        ),
        store=store,
    )

    assert "definition-inst-2" not in expanded.unit_ids
    assert store.unauthorized_content_reads == 0


def test_model_context_rejects_incomplete_slots_before_exposing_evidence() -> None:
    with pytest.raises(ValueError, match="complete insurance evidence slots"):
        assemble_insurance_model_context(
            evidence=(
                InsuranceEvidenceContent(
                    evidence=AdmittedInsuranceEvidence(
                        evidence_id="evidence-1",
                        rule_unit_revision_id="rule-1",
                        supported_slot_ids=("governing-rule",),
                    ),
                    content="Rule content",
                ),
            ),
            slot_evaluation=EvidenceSlotEvaluation(
                complete=False,
                satisfied_slot_ids=("governing-rule",),
                missing_slot_ids=("precedence-source",),
            ),
            normalized_conditions={"region": "SHANGHAI"},
        )
