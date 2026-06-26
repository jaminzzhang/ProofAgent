import pytest
from pydantic import ValidationError

from proof_agent.contracts import (
    AnswerEvidenceContext,
    BusinessFlowCandidatePack,
    BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType,
    EvidenceChunk,
    EvidenceStatus,
    EnforcementPoint,
    IntentResolution,
    ObservationTruthKind,
    PolicyDecisionType,
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    RetrievalObservationTruth,
    RetrievalQueryItem,
    ReviewDecision,
    ToolObservationTruth,
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


def test_retrieval_observation_truth_is_frozen_and_structured() -> None:
    evidence = EvidenceChunk(
        source="Travel Policy",
        content="Meals are reimbursed with receipts.",
        status=EvidenceStatus.ACCEPTED,
        evidence_id="ev_1",
        admission_score=0.92,
        citation="travel-policy.md#meals:L10-L18",
    )
    truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_001/truth",
        observation_id="obs_001",
        action_id="act_001",
        accepted_evidence=(evidence,),
        rejected_evidence_summary={"count": 0},
        admission_metadata={"min_score": 0.8},
        citation_refs=("travel-policy.md#meals:L10-L18",),
    )

    assert truth.kind is ObservationTruthKind.RETRIEVAL
    assert truth.accepted_evidence == (evidence,)
    assert truth.citation_refs == ("travel-policy.md#meals:L10-L18",)
    with pytest.raises(ValidationError):
        truth.accepted_evidence = ()  # type: ignore[misc]


def test_tool_observation_truth_is_frozen_and_structured() -> None:
    truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"status": "pending", "policy_id": "POL-001"},
        result_schema_id="customer_lookup.status.v1",
        approval_ref="approval://appr_001",
        redaction_metadata={"redacted_field_count": 1},
    )

    assert truth.kind is ObservationTruthKind.TOOL
    assert truth.authorized_result["status"] == "pending"
    assert truth.approval_ref == "approval://appr_001"
    with pytest.raises(TypeError):
        truth.authorized_result["raw_payload"] = {"secret": "blocked"}


def test_observation_truth_variants_reject_wrong_kind() -> None:
    with pytest.raises(ValidationError):
        RetrievalObservationTruth(
            truth_ref="observation://run_001/obs_bad/truth",
            observation_id="obs_bad",
            action_id="act_bad",
            kind=ObservationTruthKind.TOOL,
        )

    with pytest.raises(ValidationError):
        ToolObservationTruth(
            truth_ref="observation://run_001/obs_bad/truth",
            observation_id="obs_bad",
            action_id="act_bad",
            kind=ObservationTruthKind.RETRIEVAL,
            tool_name="customer_lookup",
        )


def test_answer_evidence_context_carries_resolved_truth() -> None:
    evidence = EvidenceChunk(
        source="Travel Policy",
        content="Meals are reimbursed with receipts.",
        status=EvidenceStatus.ACCEPTED,
        evidence_id="ev_1",
        citation="travel-policy.md#meals:L10-L18",
    )
    retrieval_truth = RetrievalObservationTruth(
        truth_ref="observation://run_001/obs_retrieval/truth",
        observation_id="obs_retrieval",
        action_id="act_retrieval",
        accepted_evidence=(evidence,),
        citation_refs=("travel-policy.md#meals:L10-L18",),
    )
    tool_truth = ToolObservationTruth(
        truth_ref="observation://run_001/obs_tool/truth",
        observation_id="obs_tool",
        action_id="act_tool",
        tool_name="customer_lookup",
        authorized_result={"status": "pending"},
    )
    context = AnswerEvidenceContext(
        run_id="run_001",
        observation_truth=(retrieval_truth, tool_truth),
        citation_refs=("travel-policy.md#meals:L10-L18",),
        source_refs=("Travel Policy", "tool://customer_lookup"),
        validation_precheck={"citation_ref_count": 1},
    )

    assert context.observation_truth == (retrieval_truth, tool_truth)
    assert context.citation_refs == ("travel-policy.md#meals:L10-L18",)
    with pytest.raises(TypeError):
        context.validation_precheck["extra"] = "blocked"


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


def test_business_flow_recommendation_accepts_single_candidate_pack() -> None:
    recommendation = BusinessFlowSkillPackRecommendation(
        recommendation_id="bfsp_rec_1",
        intent_resolution_id="intent_1",
        recommendation_type=BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
        confidence=0.86,
        reason="The request maps to one product clause business flow.",
        candidate_packs=(
            BusinessFlowCandidatePack(
                pack_id="product_clause_consultation",
                confidence=0.84,
                reason="The user asks for product pros and cons.",
            ),
        ),
    )

    assert recommendation.recommendation_type is (
        BusinessFlowSkillPackRecommendationType.SINGLE_PACK
    )
    assert recommendation.candidate_packs[0].pack_id == "product_clause_consultation"


def test_business_flow_recommendation_accepts_explicit_no_pack() -> None:
    recommendation = BusinessFlowSkillPackRecommendation(
        recommendation_id="bfsp_rec_no_pack",
        intent_resolution_id="intent_1",
        recommendation_type=BusinessFlowSkillPackRecommendationType.NO_PACK,
        confidence=0.74,
        reason="The request is in scope for the Agent but does not need a pack.",
        candidate_packs=(),
    )

    assert recommendation.recommendation_type is (BusinessFlowSkillPackRecommendationType.NO_PACK)
    assert recommendation.candidate_packs == ()


def test_business_flow_recommendation_validates_candidate_cardinality() -> None:
    with pytest.raises(ValidationError):
        BusinessFlowSkillPackRecommendation(
            recommendation_id="bfsp_rec_bad_single",
            intent_resolution_id="intent_1",
            recommendation_type=BusinessFlowSkillPackRecommendationType.SINGLE_PACK,
            confidence=0.86,
            reason="Invalid single-pack recommendation has no candidate.",
            candidate_packs=(),
        )

    with pytest.raises(ValidationError):
        BusinessFlowSkillPackRecommendation(
            recommendation_id="bfsp_rec_bad_no_pack",
            intent_resolution_id="intent_1",
            recommendation_type=BusinessFlowSkillPackRecommendationType.NO_PACK,
            confidence=0.86,
            reason="Invalid no-pack recommendation includes a candidate.",
            candidate_packs=(
                BusinessFlowCandidatePack(
                    pack_id="product_clause_consultation",
                    confidence=0.84,
                    reason="The user asks for product pros and cons.",
                ),
            ),
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_business_flow_candidate_pack_rejects_invalid_confidence(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        BusinessFlowCandidatePack(
            pack_id="product_clause_consultation",
            confidence=confidence,
            reason="The user asks for product pros and cons.",
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
