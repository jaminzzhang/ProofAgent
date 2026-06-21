from proof_agent.control.workflow.business_flow_skill_packs import (
    admit_business_flow_skill_pack,
)
from proof_agent.contracts import (
    BusinessFlowCandidatePack,
    BusinessFlowSkillPackAdmissionConfig,
    BusinessFlowSkillPackAdmissionDecision,
    BusinessFlowSkillPackDefinition,
    BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType,
)


def _skill_pack(
    pack_id: str,
    *,
    min_confidence: float = 0.0,
    require_authorization_context: bool = False,
) -> BusinessFlowSkillPackDefinition:
    return BusinessFlowSkillPackDefinition(
        schema_version="business_flow_skill_pack.v1",
        id=pack_id,
        label=pack_id.replace("_", " ").title(),
        description=f"{pack_id} routing addenda.",
        stage_prompt_addenda={},
        admission=BusinessFlowSkillPackAdmissionConfig(
            min_confidence=min_confidence,
            require_authorization_context=require_authorization_context,
        ),
    )


def _recommendation(
    recommendation_type: BusinessFlowSkillPackRecommendationType,
    *,
    route_confidence: float = 0.91,
    candidates: tuple[tuple[str, float], ...] = (),
    requires_task_split: bool = False,
) -> BusinessFlowSkillPackRecommendation:
    return BusinessFlowSkillPackRecommendation(
        recommendation_id="bfsp_rec_intent_1",
        intent_resolution_id="intent_1",
        recommendation_type=recommendation_type,
        confidence=route_confidence,
        reason="LLM resolved the Business Flow Skill Pack route.",
        candidate_packs=tuple(
            BusinessFlowCandidatePack(
                pack_id=pack_id,
                confidence=confidence,
                reason=f"{pack_id} is relevant.",
            )
            for pack_id, confidence in candidates
        ),
        requires_task_split=requires_task_split,
    )


def test_admits_llm_recommended_single_business_flow_skill_pack() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        candidates=(("claims_qa", 0.86),),
    )
    skill_pack = _skill_pack("claims_qa", min_confidence=0.8)

    result = admit_business_flow_skill_pack(
        recommendation,
        (skill_pack,),
        route_min_confidence=0.6,
    )

    assert result.recommendation == recommendation
    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.ADMITTED
    assert result.admission.selected_pack_id == "claims_qa"
    assert result.admission.trace_summary["candidate_count"] == 1


def test_explicit_no_pack_recommendation_runs_without_business_flow_pack() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.NO_PACK,
        route_confidence=0.82,
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"),),
        route_min_confidence=0.6,
    )

    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.NO_PACK
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason is None
    assert result.admission.trace_summary["candidate_count"] == 0


def test_low_route_confidence_becomes_no_pack_before_clarification() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.AMBIGUOUS,
        route_confidence=0.39,
        candidates=(("claims_qa", 0.88), ("billing_qa", 0.84)),
        requires_task_split=True,
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"), _skill_pack("billing_qa")),
        route_min_confidence=0.6,
    )

    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.NO_PACK
    assert result.admission.failure_reason == "route_confidence_below_threshold"
    assert result.admission.selected_pack_id is None


def test_candidate_below_pack_confidence_gate_becomes_no_pack() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        candidates=(("claims_qa", 0.72),),
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa", min_confidence=0.9),),
        route_min_confidence=0.6,
    )

    assert result.admission.decision == BusinessFlowSkillPackAdmissionDecision.NO_PACK
    assert result.admission.failure_reason == "candidate_confidence_below_threshold"
    assert result.admission.selected_pack_id is None


def test_ambiguous_recommendation_needs_clarification() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.AMBIGUOUS,
        candidates=(("claims_qa", 0.88), ("billing_qa", 0.84)),
        requires_task_split=True,
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"), _skill_pack("billing_qa")),
        route_min_confidence=0.6,
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "ambiguous"
    assert result.admission.trace_summary["candidate_count"] == 2


def test_unknown_recommended_business_flow_skill_pack_fails_closed() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        candidates=(("missing_qa", 0.86),),
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"),),
        route_min_confidence=0.6,
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "unknown_pack"


def test_unauthorized_business_flow_skill_pack_fails_closed_without_fallback() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        candidates=(("claims_qa", 0.86),),
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa", require_authorization_context=True),),
        route_min_confidence=0.6,
        authorization_context_present=False,
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "unauthorized"


def test_not_ready_business_flow_skill_pack_fails_closed_without_fallback() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        candidates=(("claims_qa", 0.86),),
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"), _skill_pack("general_qa")),
        route_min_confidence=0.6,
        ready_pack_ids=("general_qa",),
    )

    assert (
        result.admission.decision
        == BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED
    )
    assert result.admission.selected_pack_id is None
    assert result.admission.failure_reason == "not_ready"


def test_normalizes_candidate_pack_order_by_confidence_descending() -> None:
    recommendation = _recommendation(
        BusinessFlowSkillPackRecommendationType.AMBIGUOUS,
        candidates=(("billing_qa", 0.74), ("claims_qa", 0.91)),
        requires_task_split=True,
    )

    result = admit_business_flow_skill_pack(
        recommendation,
        (_skill_pack("claims_qa"), _skill_pack("billing_qa")),
        route_min_confidence=0.6,
    )

    assert [pack.pack_id for pack in result.recommendation.candidate_packs] == [
        "claims_qa",
        "billing_qa",
    ]
    assert result.admission.trace_summary["candidate_count"] == 2
    assert result.admission.trace_summary["normalization_applied"] is True
