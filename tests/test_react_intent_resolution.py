import json

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

    def __init__(self, content: str | list[str]) -> None:
        self.contents = [content] if isinstance(content, str) else list(content)
        self.requests: list[ModelRequest] = []

    def estimate_tokens(self, request: ModelRequest) -> int:
        _ = request
        return 42

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        content = self.contents[min(len(self.requests) - 1, len(self.contents) - 1)]
        return ModelResponse(
            content=content,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )

    @property
    def last_request(self) -> ModelRequest | None:
        return self.requests[-1] if self.requests else None


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
    user_payload = json.loads(provider.last_request.messages[1].content)
    assert user_payload["required_output_contract"]["required_fields"] == [
        "resolution_id",
        "user_goal",
        "domain_intent",
        "known_facts",
        "missing_fields",
        "ambiguities",
        "risk_flags",
        "confidence",
        "recommended_next_action",
    ]


def test_llm_intent_resolver_repairs_missing_contract_fields_once() -> None:
    provider = FakeIntentProvider(
        [
            """
            {
              "known_facts": ["The user asks about an insurance product."],
              "missing_fields": [],
              "ambiguities": [],
              "risk_flags": [],
              "confidence": 0.64,
              "recommended_next_action": "plan_retrieval"
            }
            """,
            """
            {
              "resolution_id": "intent_repaired_1",
              "user_goal": "Understand an insurance product's advantages and disadvantages.",
              "domain_intent": "public_insurance_product_explanation",
              "known_facts": ["The user asks about an insurance product."],
              "missing_fields": [],
              "ambiguities": [],
              "risk_flags": [],
              "confidence": 0.76,
              "recommended_next_action": "plan_retrieval"
            }
            """,
        ]
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )

    resolution = resolver.resolve(
        question="简单介绍下平安御享的主要优缺点",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )

    assert resolution.resolution_id == "intent_repaired_1"
    assert len(provider.requests) == 2
    repair_payload = json.loads(provider.requests[1].messages[1].content)
    assert repair_payload["validation_error"]["field_paths"] == [
        "resolution_id",
        "user_goal",
        "domain_intent",
    ]
    assert repair_payload["previous_response_json"]["recommended_next_action"] == (
        "plan_retrieval"
    )


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
