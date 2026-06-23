import json

import pytest

from proof_agent.capabilities.react import (
    DeterministicIntentResolver,
    LLMIntentResolver,
    resolve_intent_resolver,
)
from proof_agent.capabilities.models.normalization import ModelOutputNormalizationError
from proof_agent.contracts import (
    BusinessFlowSkillPackAdmissionConfig,
    BusinessFlowSkillPackDefinition,
    BusinessFlowSkillPackRecommendationType,
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

    result = resolver.resolve(
        question="Can this customer claim it?",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )
    resolution = result.intent_resolution

    assert resolution.recommended_next_action == ReActActionType.ASK_CLARIFICATION
    assert resolution.missing_fields == ("customer_id", "policy_id", "claim_type")
    assert resolution.confidence < 0.8


def test_deterministic_intent_resolver_recommends_retrieval_for_policy_question() -> None:
    resolver = DeterministicIntentResolver()

    result = resolver.resolve(
        question="What documents are required for inpatient reimbursement?",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )
    resolution = result.intent_resolution

    assert resolution.recommended_next_action == ReActActionType.PLAN_RETRIEVAL
    assert resolution.domain_intent == "enterprise_policy_question"
    assert resolution.missing_fields == ()
    assert [item.intent_angle for item in resolution.retrieval_query_set] == [
        "primary_policy_question"
    ]
    assert resolution.retrieval_query_set[0].required is True


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
          "recommended_next_action": "plan_retrieval",
          "retrieval_query_set": [
            {
              "query": "inpatient reimbursement required documents",
              "intent_angle": "required_documents",
              "required": true,
              "reason": "The user asks which documents are required."
            }
          ]
        }
        """
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )

    result = resolver.resolve(
        question="What documents are required for inpatient reimbursement?",
        system_prompt="Resolve intent safely.",
        context_summary="Recent turn summary.",
    )
    resolution = result.intent_resolution

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
        "retrieval_query_set",
    ]
    assert user_payload["retrieval_query_set_budget"]["max_queries"] == 3
    assert resolution.retrieval_query_set[0].query == (
        "inpatient reimbursement required documents"
    )


def test_llm_intent_resolver_exposes_public_query_expansion_policy() -> None:
    provider = FakeIntentProvider(
        """
        {
          "resolution_id": "intent_llm_1",
          "user_goal": "Identify top-selling Ping An insurance products for 2025.",
          "domain_intent": "public_insurance_knowledge_query",
          "known_facts": ["The user asks which products sold well in 2025."],
          "missing_fields": [],
          "ambiguities": [],
          "risk_flags": [],
          "confidence": 0.86,
          "recommended_next_action": "plan_retrieval",
          "retrieval_query_set": [
            {
              "query": "平安保险2025年热销产品",
              "intent_angle": "original_business_terms",
              "required": true,
              "reason": "Uses the user's original entity, year, and business wording."
            }
          ]
        }
        """
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )

    resolver.resolve(
        question="平安2025年卖得好的产品有哪些？",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )

    assert provider.last_request is not None
    user_payload = json.loads(provider.last_request.messages[1].content)
    expansion_policy = user_payload["retrieval_query_set_budget"][
        "query_expansion_policy"
    ]
    assert expansion_policy["name"] == "knowledge_query_expansion"
    assert expansion_policy["domain_specific_query_types_allowed"] is False
    assert "original wording" in expansion_policy["required_angles"]
    assert "business terminology or synonyms" in expansion_policy["required_angles"]
    assert "time/entity/metric qualifiers" in expansion_policy["required_angles"]


def test_llm_intent_resolver_includes_business_flow_pack_summaries() -> None:
    provider = FakeIntentProvider(
        """
        {
          "intent_resolution": {
            "resolution_id": "intent_llm_1",
            "user_goal": "Understand product pros and cons.",
            "domain_intent": "insurance_product_explanation",
            "known_facts": ["The user asks about an insurance product."],
            "missing_fields": [],
            "ambiguities": [],
            "risk_flags": [],
            "confidence": 0.91,
            "recommended_next_action": "plan_retrieval",
            "retrieval_query_set": [
              {
                "query": "Ping An Yu Xiang pros cons",
                "intent_angle": "product_explanation",
                "required": true,
                "reason": "The user asks for product pros and cons."
              }
            ]
          },
          "business_flow_skill_pack_recommendation": {
            "recommendation_id": "bfsp_rec_intent_llm_1",
            "intent_resolution_id": "intent_llm_1",
            "recommendation_type": "single_pack",
            "confidence": 0.88,
            "reason": "The request is about insurance product clause consultation.",
            "candidate_packs": [
              {
                "pack_id": "product_clause_consultation",
                "confidence": 0.86,
                "reason": "Product pros and cons require clause consultation flow."
              }
            ],
            "requires_task_split": false
          }
        }
        """
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )
    skill_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="product_clause_consultation",
        label="Product Clause Consultation",
        description="Answer product clause questions with governed evidence.",
        intent_patterns=("产品咨询", "优缺点"),
        intent_taxonomy_refs=("insurance.product_clause",),
        stage_prompt_addenda={
            "plan": {
                "business_context": "This must never be exposed during intent resolution."
            }
        },
        tool_contract_refs=("internal_tool",),
        policy_rule_refs=("internal_policy",),
        validator_refs=("evidence",),
        admission=BusinessFlowSkillPackAdmissionConfig(min_confidence=0.75),
    )

    result = resolver.resolve(
        question="介绍平安御享的主要优缺点",
        system_prompt="Resolve intent safely.",
        context_summary="Recent turn summary.",
        business_flow_skill_packs=(skill_pack,),
    )

    assert result.intent_resolution.resolution_id == "intent_llm_1"
    assert result.business_flow_skill_pack_recommendation is not None
    assert (
        result.business_flow_skill_pack_recommendation.recommendation_type
        == BusinessFlowSkillPackRecommendationType.SINGLE_PACK
    )
    user_payload = json.loads(provider.last_request.messages[1].content)
    routing = user_payload["business_flow_skill_pack_routing"]
    assert routing["required"] is True
    assert routing["candidate_packs"] == [
        {
            "pack_id": "product_clause_consultation",
            "label": "Product Clause Consultation",
            "description": "Answer product clause questions with governed evidence.",
            "intent_patterns": ["产品咨询", "优缺点"],
            "intent_taxonomy_refs": ["insurance.product_clause"],
            "admission": {
                "min_confidence": 0.75,
                "require_authorization_context": False,
            },
        }
    ]
    serialized_payload = provider.last_request.messages[1].content
    assert "stage_prompt_addenda" not in serialized_payload
    assert "internal_tool" not in serialized_payload
    assert "internal_policy" not in serialized_payload


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
              "recommended_next_action": "plan_retrieval",
              "retrieval_query_set": [
                {
                  "query": "insurance product advantages disadvantages",
                  "intent_angle": "product_explanation",
                  "required": true,
                  "reason": "The user asks for product pros and cons."
                }
              ]
            }
            """,
        ]
    )
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=provider,
    )

    result = resolver.resolve(
        question="简单介绍下平安御享的主要优缺点",
        system_prompt="Resolve intent safely.",
        context_summary="",
    )
    resolution = result.intent_resolution

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


def test_llm_intent_resolver_rejects_retrieval_intent_without_query_set() -> None:
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=FakeIntentProvider(
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
              "recommended_next_action": "plan_retrieval",
              "retrieval_query_set": []
            }
            """
        ),
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        resolver.resolve(
            question="What documents are required for inpatient reimbursement?",
            system_prompt="Resolve intent safely.",
            context_summary="",
        )

    assert "retrieval_query_set" in exc.value.field_paths


def test_llm_intent_resolver_rejects_over_budget_query_set() -> None:
    resolver = LLMIntentResolver(
        config=ReActPlannerConfig(provider="openai_compatible", name="intent-test"),
        model_provider=FakeIntentProvider(
            json.dumps(
                {
                    "resolution_id": "intent_llm_1",
                    "user_goal": "Understand reimbursement documents.",
                    "domain_intent": "insurance_claim_reimbursement_requirements",
                    "known_facts": ["The user asks about reimbursement documents."],
                    "missing_fields": [],
                    "ambiguities": [],
                    "risk_flags": [],
                    "confidence": 0.91,
                    "recommended_next_action": "plan_retrieval",
                    "retrieval_query_set": [
                        {
                            "query": f"query {index}",
                            "intent_angle": f"angle_{index}",
                            "required": index == 0,
                            "reason": f"Reason {index}",
                        }
                        for index in range(4)
                    ],
                }
            )
        ),
        max_queries=3,
    )

    with pytest.raises(ModelOutputNormalizationError) as exc:
        resolver.resolve(
            question="What documents are required for inpatient reimbursement?",
            system_prompt="Resolve intent safely.",
            context_summary="",
        )

    assert "retrieval_query_set" in exc.value.field_paths


def test_resolve_intent_resolver_uses_deterministic_provider() -> None:
    resolver = resolve_intent_resolver(ReActPlannerConfig(provider="deterministic"))

    assert isinstance(resolver, DeterministicIntentResolver)
