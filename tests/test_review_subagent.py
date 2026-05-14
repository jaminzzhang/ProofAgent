import pytest

from proof_agent.capabilities.review import resolve_review_subagent
from proof_agent.contracts import (
    EnforcementPoint,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReviewSubagentConfig,
)
from proof_agent.errors import ProofAgentError


@pytest.fixture
def sample_action_proposal() -> ReActActionProposal:
    summary = ReasoningSummary(
        goal="Answer an enterprise policy question with evidence.",
        observations=("Question asks about the approved support policy.",),
        candidate_actions=(ReActActionType.PLAN_RETRIEVAL,),
        selected_action=ReActActionType.PLAN_RETRIEVAL,
        rationale_summary="Accepted policy evidence is required before answering.",
        risk_flags=(),
        required_evidence=("support policy",),
    )
    return ReActActionProposal(
        action_id="act_retrieve_1",
        action_type=ReActActionType.PLAN_RETRIEVAL,
        reasoning_summary=summary,
        parameters={"query": "support policy approval rules"},
        risk_level="low",
    )


def test_deterministic_reviewer_allows_safe_retrieval_plan(
    sample_action_proposal: ReActActionProposal,
) -> None:
    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(provider="deterministic", name="local-reviewer")
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        action=sample_action_proposal,
        context={"accepted_evidence_count": 0},
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW
    assert decision.enforcement_point == EnforcementPoint.BEFORE_RETRIEVAL_PLAN
    assert decision.subject_action_id == "act_retrieve_1"
    assert decision.review_id == "review.act_retrieve_1.before_retrieval_plan"
    assert 0.0 <= decision.confidence <= 1.0


def test_deterministic_reviewer_requires_approval_for_medium_risk_customer_lookup(
    sample_action_proposal: ReActActionProposal,
) -> None:
    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(provider="deterministic", name="local-reviewer")
    )
    action = sample_action_proposal.model_copy(
        update={
            "action_type": ReActActionType.PROPOSE_TOOL_CALL,
            "target_tool_name": "customer_lookup",
            "risk_level": "medium",
        }
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_TOOL_CALL,
        action=action,
        context={"tool_name": "customer_lookup", "risk_level": "medium"},
    )

    assert decision.suggested_decision == PolicyDecisionType.REQUIRE_APPROVAL
    assert decision.subject_action_id == "act_retrieve_1"
    assert "medium" in decision.reason


def test_unsupported_review_provider_raises_coherent_error() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_review_subagent(
            ReviewSubagentConfig(provider="openai", name="remote-reviewer")
        )

    assert exc.value.code == "PA_MODEL_001"
    assert "Unsupported review subagent provider" in exc.value.message
    assert "deterministic" in exc.value.fix
