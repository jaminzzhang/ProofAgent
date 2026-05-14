from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
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
