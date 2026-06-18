import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    EnforcementPoint,
    IntentResolution,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalQueryItem,
    ReviewDecision,
)


def test_react_action_proposal_is_frozen_and_structured() -> None:
    summary = ReasoningSummary(
        goal="Answer an enterprise policy question with evidence.",
        observations=("Question asks about travel meals.",),
        candidate_actions=(ReActActionType.PLAN_RETRIEVAL,),
        selected_action=ReActActionType.PLAN_RETRIEVAL,
        rationale_summary="Need accepted travel policy evidence before answer.",
        risk_flags=(),
        required_evidence=("travel meal policy",),
    )
    proposal = ReActActionProposal(
        action_id="act_1",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        reasoning_summary=summary,
        parameters={"query": "travel meal reimbursement rule"},
        target_tool_name=None,
        risk_level="low",
    )

    assert proposal.action_type == ReActActionType.PLAN_RETRIEVAL
    assert proposal.parameters["query"] == "travel meal reimbursement rule"


def test_intent_resolution_is_frozen_and_structured() -> None:
    query_item = RetrievalQueryItem(
        query="inpatient reimbursement required documents",
        intent_angle="required_documents",
        required=True,
        reason="The user asks which documents are required.",
    )
    resolution = IntentResolution(
        resolution_id="intent_1",
        user_goal="Understand inpatient reimbursement requirements.",
        domain_intent="insurance_claim_reimbursement_requirements",
        known_facts=("The user asks about inpatient reimbursement.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.86,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        retrieval_query_set=(query_item,),
    )

    assert resolution.domain_intent == "insurance_claim_reimbursement_requirements"
    assert resolution.recommended_next_action == ReActActionType.PLAN_RETRIEVAL
    assert resolution.retrieval_query_set == (query_item,)

    with pytest.raises(ValidationError):
        resolution.known_facts = ("changed",)  # type: ignore[misc]


def test_intent_resolution_defaults_retrieval_query_set_to_empty() -> None:
    resolution = IntentResolution(
        resolution_id="intent_1",
        user_goal="Clarify a customer-specific claim question.",
        domain_intent="customer_claim_question",
        known_facts=("The user refers to a claim without identifiers.",),
        missing_fields=("customer_id",),
        ambiguities=(),
        risk_flags=(),
        confidence=0.6,
        recommended_next_action=ReActActionType.ASK_CLARIFICATION,
    )

    assert resolution.retrieval_query_set == ()


def test_retrieval_query_item_rejects_empty_audit_fields() -> None:
    with pytest.raises(ValidationError):
        RetrievalQueryItem(
            query=" ",
            intent_angle="required_documents",
            required=True,
            reason="The user asks which documents are required.",
        )
    with pytest.raises(ValidationError):
        RetrievalQueryItem(
            query="inpatient reimbursement required documents",
            intent_angle=" ",
            required=True,
            reason="The user asks which documents are required.",
        )
    with pytest.raises(ValidationError):
        RetrievalQueryItem(
            query="inpatient reimbursement required documents",
            intent_angle="required_documents",
            required=True,
            reason=" ",
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_intent_resolution_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        IntentResolution(
            resolution_id="intent_1",
            user_goal="Understand inpatient reimbursement requirements.",
            domain_intent="insurance_claim_reimbursement_requirements",
            known_facts=("The user asks about inpatient reimbursement.",),
            missing_fields=(),
            ambiguities=(),
            risk_flags=(),
            confidence=confidence,
            recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        )


def test_review_decision_is_advisory_policy_shape() -> None:
    decision = ReviewDecision(
        review_id="rev_1",
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        suggested_decision=PolicyDecisionType.ALLOW,
        reason="The plan stays inside the enterprise QA scope.",
        confidence=0.8,
        risk_flags=(),
        subject_action_id="act_1",
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW
    assert decision.subject_action_id == "act_1"


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_review_decision_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValidationError):
        ReviewDecision(
            review_id="rev_1",
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            suggested_decision=PolicyDecisionType.ALLOW,
            reason="The plan stays inside the enterprise QA scope.",
            confidence=confidence,
            risk_flags=(),
            subject_action_id="act_1",
        )
