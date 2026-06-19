from proof_agent.control.workflow.business_flow_skill_packs import (
    admit_business_flow_skill_pack,
)
from proof_agent.contracts import (
    BusinessFlowSkillPackAdmissionConfig,
    BusinessFlowSkillPackAdmissionDecision,
    BusinessFlowSkillPackDefinition,
    IntentResolution,
    ReActActionType,
    RetrievalQueryItem,
)


def test_admits_single_matching_business_flow_skill_pack() -> None:
    skill_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
        knowledge_binding_refs=("kb_claims",),
        tool_contract_refs=(),
        policy_rule_refs=("answering.require_retrieval",),
        validator_refs=(),
    )
    resolution = IntentResolution(
        resolution_id="intent_1",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.84,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(resolution, (skill_pack,))

    assert result.recommendation.intent_resolution_id == "intent_1"
    assert result.recommendation.recommended_pack_id == "claims_qa"
    assert result.recommendation.candidate_pack_ids == ("claims_qa",)
    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.ADMITTED
    assert result.admission.selected_pack_id == "claims_qa"


def test_ambiguous_business_flow_skill_pack_match_needs_clarification() -> None:
    claims_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
    )
    specialist_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="specialist_claims",
        label="Specialist Claims",
        description="Specialist claim routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_ambiguous",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.82,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(
        resolution,
        (claims_pack, specialist_pack),
    )

    assert result.recommendation.recommended_pack_id is None
    assert result.recommendation.candidate_pack_ids == (
        "claims_qa",
        "specialist_claims",
    )
    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "ambiguous"


def test_missing_business_flow_skill_pack_match_needs_clarification() -> None:
    skill_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_missing",
        user_goal="Answer a billing question.",
        domain_intent="billing_question",
        known_facts=("The user asks about billing.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.82,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(resolution, (skill_pack,))

    assert result.recommendation.recommended_pack_id is None
    assert result.recommendation.candidate_pack_ids == ()
    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "missing"


def test_admits_business_flow_skill_pack_from_retrieval_query_set() -> None:
    skill_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="product_clause_consultation",
        label="Product Clause Consultation",
        description="Product clause routing addenda.",
        intent_patterns=("优缺点",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_product",
        user_goal="Answer an enterprise policy question.",
        domain_intent="enterprise_policy_question",
        known_facts=("The user asks a question that should be grounded in knowledge.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.84,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
        retrieval_query_set=(
            RetrievalQueryItem(
                query="介绍平安御享的主要优缺点",
                intent_angle="primary_policy_question",
                required=True,
                reason="The user asks a knowledge-backed enterprise policy question.",
            ),
        ),
    )

    result = admit_business_flow_skill_pack(resolution, (skill_pack,))

    assert result.recommendation.recommended_pack_id == "product_clause_consultation"
    assert result.recommendation.candidate_pack_ids == ("product_clause_consultation",)
    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.ADMITTED
    assert result.admission.selected_pack_id == "product_clause_consultation"


def test_not_admissible_business_flow_skill_pack_uses_safe_default() -> None:
    claims_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
        admission=BusinessFlowSkillPackAdmissionConfig(min_confidence=0.9),
    )
    default_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="general_qa",
        label="General QA",
        description="Safe default routing addenda.",
        intent_patterns=("general_question",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_low_confidence",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.72,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(
        resolution,
        (claims_pack, default_pack),
        default_pack_id="general_qa",
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.SAFE_DEFAULT
    )
    assert result.admission.selected_pack_id == "general_qa"
    assert result.admission.failure_reason == "not_admissible"


def test_not_admissible_business_flow_skill_pack_refuses_without_default() -> None:
    claims_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
        admission=BusinessFlowSkillPackAdmissionConfig(min_confidence=0.9),
    )
    resolution = IntentResolution(
        resolution_id="intent_low_confidence_no_default",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.72,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(resolution, (claims_pack,))

    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.REFUSED
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "not_admissible"


def test_unauthorized_business_flow_skill_pack_fails_closed_without_fallback() -> None:
    claims_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
        admission=BusinessFlowSkillPackAdmissionConfig(
            min_confidence=0.5,
            require_authorization_context=True,
        ),
    )
    default_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="general_qa",
        label="General QA",
        description="Safe default routing addenda.",
        intent_patterns=("general_question",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_unauthorized",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.82,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(
        resolution,
        (claims_pack, default_pack),
        default_pack_id="general_qa",
        authorization_context_present=False,
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "unauthorized"


def test_not_ready_business_flow_skill_pack_fails_closed_without_fallback() -> None:
    claims_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="claims_qa",
        label="Claims QA",
        description="Claims question routing addenda.",
        intent_patterns=("claims_question",),
        stage_prompt_addenda={},
    )
    default_pack = BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id="general_qa",
        label="General QA",
        description="Safe default routing addenda.",
        intent_patterns=("general_question",),
        stage_prompt_addenda={},
    )
    resolution = IntentResolution(
        resolution_id="intent_not_ready",
        user_goal="Answer a claims question.",
        domain_intent="claims_question",
        known_facts=("The user asks about a claims process.",),
        missing_fields=(),
        ambiguities=(),
        risk_flags=(),
        confidence=0.82,
        recommended_next_action=ReActActionType.PLAN_RETRIEVAL,
    )

    result = admit_business_flow_skill_pack(
        resolution,
        (claims_pack, default_pack),
        default_pack_id="general_qa",
        ready_pack_ids=("general_qa",),
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "not_ready"
