from __future__ import annotations

from proof_agent.contracts import EvaluationGateName, EvaluationGateProfile
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
        EvaluationGateName.RESPONSE_PROJECTION_SAFETY,
        EvaluationGateName.REDACTION_SAFETY,
        EvaluationGateName.RESPONSE_ASSERTION,
        EvaluationGateName.INTENT_EXECUTION_BEHAVIOR,
        EvaluationGateName.BUSINESS_FLOW_SKILL_PACK,
    ),
    diagnostic_gates=(
        EvaluationGateName.FORBIDDEN_CLAIM,
    ),
)


def get_gate_profile(profile_id: str) -> EvaluationGateProfile:
    """Return a known Evaluation Gate Profile."""

    if profile_id == CORE_ANALYZER_GATES_V1.profile_id:
        return CORE_ANALYZER_GATES_V1
    raise EvaluationInputError(f"Unknown evaluation gate profile: {profile_id}")
