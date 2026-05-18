import pytest

from proof_agent.capabilities.review import (
    LLMHarnessReviewSubagent,
    resolve_review_subagent,
)
from proof_agent.contracts import (
    EnforcementPoint,
    ModelResponse,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    ReviewSubagentConfig,
)
from proof_agent.errors import ProofAgentError


class FakeReviewProvider:
    provider_name = "openai_compatible"
    model_name = "reviewer-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def estimate_tokens(self, request):
        return 21

    def generate(self, request):
        self.requests.append(request)
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


VALID_REVIEW_OUTPUT = """
{
  "review_id": "review.act_retrieve_1.before_retrieval_plan",
  "enforcement_point": "before_retrieval_plan",
  "suggested_decision": "allow",
  "reason": "The action proposes a low-risk retrieval plan.",
  "confidence": 0.86,
  "risk_flags": [],
  "subject_action_id": "act_retrieve_1",
  "metadata": {"provider": "openai_compatible"}
}
"""


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


def test_llm_harness_review_subagent_uses_json_contract(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(VALID_REVIEW_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
            timeout_seconds=5,
            max_output_tokens=500,
            fail_closed=True,
        ),
        model_provider=provider,
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        action=sample_action_proposal,
        context={"accepted_evidence_count": 0},
    )

    assert decision.suggested_decision == PolicyDecisionType.ALLOW
    assert provider.requests[0].response_format == "json"
    assert provider.requests[0].stream is False


def test_resolve_review_subagent_uses_llm_adapter_for_registered_model_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeReviewProvider(VALID_REVIEW_OUTPUT)
    monkeypatch.setattr(
        "proof_agent.capabilities.review.subagent.resolve_provider",
        lambda config: provider,
    )

    reviewer = resolve_review_subagent(
        ReviewSubagentConfig(provider="openai_compatible", name="reviewer-test")
    )

    assert isinstance(reviewer, LLMHarnessReviewSubagent)


def test_unsupported_review_provider_raises_coherent_error() -> None:
    with pytest.raises(ProofAgentError) as exc:
        resolve_review_subagent(
            ReviewSubagentConfig(provider="missing_provider", name="remote-reviewer")
        )

    assert exc.value.code == "PA_MODEL_001"
    assert "unsupported model provider" in exc.value.message
