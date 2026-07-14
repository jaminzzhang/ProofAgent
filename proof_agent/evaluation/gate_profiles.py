from __future__ import annotations

from pydantic import Field

from proof_agent.contracts import EvaluationGateName, EvaluationGateProfile
from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


CORE_ANALYZER_GATES_V1 = EvaluationGateProfile(
    profile_id="core_analyzer_gates.v1",
    required_gates=(
        EvaluationGateName.SUBJECT_MAPPING,
        EvaluationGateName.ARTIFACT_SUFFICIENCY,
        EvaluationGateName.OUTCOME,
        EvaluationGateName.AUDIT_ARTIFACT,
        EvaluationGateName.CONTROL_ENVELOPE_COVERAGE,
        EvaluationGateName.EVIDENCE_STRUCTURAL,
        EvaluationGateName.TOOL_GOVERNANCE_STRUCTURAL,
        EvaluationGateName.TOOL_PROPOSAL_SCOPE,
        EvaluationGateName.RESPONSE_PROJECTION_SAFETY,
        EvaluationGateName.REDACTION_SAFETY,
        EvaluationGateName.RESPONSE_ASSERTION,
        EvaluationGateName.INTENT_EXECUTION_BEHAVIOR,
        EvaluationGateName.BUSINESS_FLOW_SKILL_PACK,
    ),
    diagnostic_gates=(EvaluationGateName.FORBIDDEN_CLAIM,),
)


class KnowledgeAcceptanceGateProfile(FrozenModel):
    """Pinned, non-candidate-selectable thresholds for Knowledge acceptance."""

    profile_id: str
    overall_recall_at_50_minimum: float = Field(ge=0.0, le=1.0)
    query_slice_recall_at_50_minimum: float = Field(ge=0.0, le=1.0)
    complete_evidence_top_10_minimum: float = Field(ge=0.0, le=1.0)
    human_reviewed_support_precision_minimum: float = Field(ge=0.0, le=1.0)
    hybrid_retrieval_p95_seconds_maximum: float = Field(gt=0.0)


INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1 = KnowledgeAcceptanceGateProfile(
    profile_id="insurance_knowledge_acceptance_gates.v1",
    overall_recall_at_50_minimum=0.95,
    query_slice_recall_at_50_minimum=0.90,
    complete_evidence_top_10_minimum=0.90,
    human_reviewed_support_precision_minimum=0.98,
    hybrid_retrieval_p95_seconds_maximum=5.0,
)


def get_gate_profile(profile_id: str) -> EvaluationGateProfile:
    """Return a known Evaluation Gate Profile."""

    if profile_id == CORE_ANALYZER_GATES_V1.profile_id:
        return CORE_ANALYZER_GATES_V1
    raise EvaluationInputError(f"Unknown evaluation gate profile: {profile_id}")


def get_knowledge_gate_profile(profile_id: str) -> KnowledgeAcceptanceGateProfile:
    """Return the centrally governed insurance Knowledge acceptance profile."""

    if profile_id == INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1.profile_id:
        return INSURANCE_KNOWLEDGE_ACCEPTANCE_GATES_V1
    raise EvaluationInputError(f"Unknown Knowledge acceptance gate profile: {profile_id}")
