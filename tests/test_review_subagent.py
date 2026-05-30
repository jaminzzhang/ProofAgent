import json
from typing import Self

import pytest

from proof_agent.capabilities.review import (
    LLMHarnessReviewSubagent,
    resolve_review_subagent,
)
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.contracts import (
    EnforcementPoint,
    ModelConfig,
    ModelRequest,
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
        self.requests: list[ModelRequest] = []

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self:
        return cls(VALID_REVIEW_OUTPUT)

    def estimate_tokens(self, request: ModelRequest) -> int:
        return 21

    def generate(self, request: ModelRequest) -> ModelResponse:
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


VALID_MODEL_CALL_REVIEW_OUTPUT = """
{
  "review_id": "review.act_retrieve_1.before_model_call",
  "enforcement_point": "before_model_call",
  "suggested_decision": "allow",
  "reason": "Accepted evidence is available for final answer generation.",
  "confidence": 0.82,
  "risk_flags": [],
  "subject_action_id": "act_retrieve_1",
  "metadata": {"provider": "openai_compatible"}
}
"""


MISMATCHED_ACTION_REVIEW_OUTPUT = """
{
  "review_id": "review.other_action.before_retrieval_plan",
  "enforcement_point": "before_retrieval_plan",
  "suggested_decision": "allow",
  "reason": "The action proposes a low-risk retrieval plan.",
  "confidence": 0.86,
  "risk_flags": [],
  "subject_action_id": "other_action",
  "metadata": {"provider": "openai_compatible"}
}
"""


MISMATCHED_ENFORCEMENT_POINT_REVIEW_OUTPUT = """
{
  "review_id": "review.act_retrieve_1.before_tool_call",
  "enforcement_point": "before_tool_call",
  "suggested_decision": "allow",
  "reason": "The action proposes a low-risk retrieval plan.",
  "confidence": 0.86,
  "risk_flags": [],
  "subject_action_id": "act_retrieve_1",
  "metadata": {"provider": "openai_compatible"}
}
"""


INVALID_MODEL_CALL_DECISION_OUTPUT = """
{
  "review_id": "review.act_retrieve_1.before_model_call",
  "enforcement_point": "before_model_call",
  "suggested_decision": "require_approval",
  "reason": "Ask a human before invoking the model.",
  "confidence": 0.82,
  "risk_flags": [],
  "subject_action_id": "act_retrieve_1",
  "metadata": {"provider": "openai_compatible"}
}
"""


RAW_REVIEW_ID_OUTPUT = """
{
  "review_id": "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE",
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
    request = provider.requests[0]
    assert request.metadata["role"] == "harness_review"
    assert request.metadata["enforcement_point"] == "before_retrieval_plan"
    assert request.metadata["subject_action_id"] == "act_retrieve_1"
    assert request.max_output_tokens == 500
    assert request.timeout_seconds == 5
    assert request.response_format == "json"
    assert request.stream is False
    user_payload = json.loads(request.messages[1].content)
    assert user_payload["enforcement_point"] == "before_retrieval_plan"
    assert user_payload["action"]["action_id"] == "act_retrieve_1"
    assert user_payload["action"]["action_type"] == "plan_retrieval"
    assert user_payload["context"] == {"accepted_evidence_count": 0}
    assert user_payload["allowed_decisions"] == ["allow", "deny", "escalate"]


def test_llm_review_canonicalizes_review_id_before_returning(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(RAW_REVIEW_ID_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
        ),
        model_provider=provider,
    )

    decision = reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
        action=sample_action_proposal,
        context={"accepted_evidence_count": 0},
    )

    assert decision.review_id == "review.act_retrieve_1.before_retrieval_plan"
    assert "RAW_MODEL_OUTPUT_SHOULD_NOT_TRACE" not in decision.review_id


def test_llm_review_accepts_compact_deepseek_style_decision(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider('{"decision": "allow"}')
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(provider="deepseek", name="deepseek-v4-flash"),
        model_provider=provider,
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


def test_llm_review_prompt_uses_enforcement_point_allowed_decisions(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(VALID_MODEL_CALL_REVIEW_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
        ),
        model_provider=provider,
    )

    reviewer.review(
        enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
        action=sample_action_proposal,
        context={"accepted_evidence_count": 1},
    )

    user_payload = json.loads(provider.requests[0].messages[1].content)
    assert user_payload["allowed_decisions"] == ["allow", "deny", "escalate"]
    assert "require_approval" not in user_payload["allowed_decisions"]


def test_llm_review_rejects_mismatched_subject_action_id(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(MISMATCHED_ACTION_REVIEW_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
        ),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        reviewer.review(
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            action=sample_action_proposal,
            context={"accepted_evidence_count": 0},
        )

    assert exc.value.role == "harness_review"
    assert exc.value.error_code == "model_output_contract_validation_failed"


def test_llm_review_rejects_mismatched_enforcement_point(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(MISMATCHED_ENFORCEMENT_POINT_REVIEW_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
        ),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        reviewer.review(
            enforcement_point=EnforcementPoint.BEFORE_RETRIEVAL_PLAN,
            action=sample_action_proposal,
            context={"accepted_evidence_count": 0},
        )

    assert exc.value.role == "harness_review"
    assert exc.value.error_code == "model_output_contract_validation_failed"


def test_llm_review_rejects_decision_outside_enforcement_point_allowlist(
    sample_action_proposal: ReActActionProposal,
) -> None:
    provider = FakeReviewProvider(INVALID_MODEL_CALL_DECISION_OUTPUT)
    reviewer = LLMHarnessReviewSubagent(
        config=ReviewSubagentConfig(
            provider="openai_compatible",
            name="reviewer-test",
        ),
        model_provider=provider,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        reviewer.review(
            enforcement_point=EnforcementPoint.BEFORE_MODEL_CALL,
            action=sample_action_proposal,
            context={"accepted_evidence_count": 1},
        )

    assert exc.value.role == "harness_review"
    assert exc.value.error_code == "model_output_contract_validation_failed"
    assert "suggested_decision is not allowed" in str(exc.value)


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
