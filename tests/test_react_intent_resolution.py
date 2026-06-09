import pytest

from proof_agent.capabilities.react import (
    DeterministicIntentResolver,
    LLMIntentResolver,
    resolve_intent_resolver,
)
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.contracts import (
    ModelRequest,
    ModelResponse,
    ReActActionType,
    ReActPlannerConfig,
)


class FakeIntentProvider:
    provider_name = "openai_compatible"
    model_name = "intent-test"

    def __init__(self, content: str) -> None:
        self.content = content
        self.last_request: ModelRequest | None = None

    def estimate_tokens(self, request: ModelRequest) -> int:
        _ = request
        return 42

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.last_request = request
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def test_deterministic_intent_resolver_recommends_clarification_for_missing_fields() -> None:
    resolver = DeterministicIntentResolver()

    resolution = resolver.resolve(
        question="Can this customer claim it?",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )

    assert resolution.recommended_next_action == ReActActionType.ASK_CLARIFICATION
    assert resolution.missing_fields == ("customer_id", "policy_id", "claim_type")
    assert resolution.confidence < 0.8


def test_deterministic_intent_resolver_recommends_retrieval_for_policy_question() -> None:
    resolver = DeterministicIntentResolver()

    resolution = resolver.resolve(
        question="What documents are required for inpatient reimbursement?",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )

    assert resolution.recommended_next_action == ReActActionType.PLAN_RETRIEVAL
    assert resolution.domain_intent == "enterprise_policy_question"
    assert resolution.missing_fields == ()


def test_llm_intent_resolver_uses_planner_config_and_json_contract() -> None:
    provider = FakeIntentProvider(
        """
        {
          "resolution_id": "intent_llm_1",
          "user_goal": "Understand reimbursement documents.",
          "domain_intent": "insurance_claim_reimbursement_requirements",
          "known_facts": ["The user asks about reimbursement documents."],
          "missing_fields": [],
          "ambiguities": [],
          "risk_flags": [],
          "confidence": 0.91,
          "recommended_next_action": "plan_retrieval"
        }
        """
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )

    resolution = resolver.resolve(
        question="What documents are required for inpatient reimbursement?",
        system_prompt="Resolve intent safely.",
        context_summary="Recent turn summary.",
    )

    assert resolution.recommended_next_action == ReActActionType.PLAN_RETRIEVAL
    assert provider.last_request is not None
    assert provider.last_request.response_format == "json"
    assert provider.last_request.metadata["role"] == "intent_resolution"


def test_llm_intent_resolver_rejects_executable_final_answer_action() -> None:
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=FakeIntentProvider(
            """
            {
              "resolution_id": "intent_llm_1",
              "user_goal": "Answer directly.",
              "domain_intent": "direct_answer",
              "known_facts": [],
              "missing_fields": [],
              "ambiguities": [],
              "risk_flags": [],
              "confidence": 0.91,
              "recommended_next_action": "generate_final_answer"
            }
            """
        ),
    )

    with pytest.raises(ModelOutputNormalizationError):
        resolver.resolve(
            question="What documents are required for inpatient reimbursement?",
            system_prompt="Resolve intent safely.",
            context_summary="",
        )


def test_resolve_intent_resolver_uses_deterministic_provider() -> None:
    resolver = resolve_intent_resolver(ReActPlannerConfig(provider="deterministic"))

    assert isinstance(resolver, DeterministicIntentResolver)
