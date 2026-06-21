from __future__ import annotations

from collections.abc import Mapping

from proof_agent.contracts import (
    BusinessFlowCandidatePack,
    BusinessFlowSkillPackAdmission,
    BusinessFlowSkillPackAdmissionDecision,
    BusinessFlowSkillPackAdmissionResult,
    BusinessFlowSkillPackDefinition,
    BusinessFlowSkillPackRecommendation,
    BusinessFlowSkillPackRecommendationType,
)


def admit_business_flow_skill_pack(
    recommendation: BusinessFlowSkillPackRecommendation,
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
    *,
    route_min_confidence: float = 0.0,
    authorization_context_present: bool = True,
    ready_pack_ids: tuple[str, ...] | None = None,
) -> BusinessFlowSkillPackAdmissionResult:
    """Admit a Primary Business Flow Skill Pack from an LLM recommendation."""

    normalized_recommendation = _normalize_recommendation(recommendation)
    normalization_applied = (
        normalized_recommendation.candidate_packs != recommendation.candidate_packs
    )
    if normalized_recommendation.confidence < route_min_confidence:
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.NO_PACK,
            selected_pack_id=None,
            reason=(
                "Business Flow Skill Pack route confidence did not meet the "
                "agent-level admission threshold."
            ),
            failure_reason="route_confidence_below_threshold",
            normalization_applied=normalization_applied,
        )
    if (
        normalized_recommendation.recommendation_type
        is BusinessFlowSkillPackRecommendationType.NO_PACK
    ):
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.NO_PACK,
            selected_pack_id=None,
            reason="No Business Flow Skill Pack was recommended for this request.",
            normalization_applied=normalization_applied,
        )
    if (
        normalized_recommendation.recommendation_type
        is BusinessFlowSkillPackRecommendationType.AMBIGUOUS
    ):
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION,
            selected_pack_id=None,
            reason=(
                "Multiple Business Flow Skill Packs were plausible and require "
                "task splitting or user clarification."
            ),
            failure_reason="ambiguous",
            normalization_applied=normalization_applied,
        )

    candidate = normalized_recommendation.candidate_packs[0]
    skill_pack_by_id = {pack.id: pack for pack in skill_packs}
    skill_pack = skill_pack_by_id.get(candidate.pack_id)
    if skill_pack is None:
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED,
            selected_pack_id=None,
            reason="Recommended Business Flow Skill Pack is not in the published set.",
            failure_reason="unknown_pack",
            normalization_applied=normalization_applied,
        )
    if ready_pack_ids is not None and skill_pack.id not in set(ready_pack_ids):
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED,
            selected_pack_id=None,
            reason="Recommended Business Flow Skill Pack is not ready for admission.",
            failure_reason="not_ready",
            normalization_applied=normalization_applied,
        )
    if (
        skill_pack.admission.require_authorization_context
        and not authorization_context_present
    ):
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED,
            selected_pack_id=None,
            reason=(
                "Business Flow Skill Pack requires authorization context, but no "
                "authorized context was available."
            ),
            failure_reason="unauthorized",
            normalization_applied=normalization_applied,
        )
    if candidate.confidence < skill_pack.admission.min_confidence:
        return _result(
            normalized_recommendation,
            decision=BusinessFlowSkillPackAdmissionDecision.NO_PACK,
            selected_pack_id=None,
            reason=(
                "Recommended Business Flow Skill Pack candidate confidence did "
                "not meet the pack-level admission threshold."
            ),
            failure_reason="candidate_confidence_below_threshold",
            normalization_applied=normalization_applied,
        )
    return _result(
        normalized_recommendation,
        decision=BusinessFlowSkillPackAdmissionDecision.ADMITTED,
        selected_pack_id=skill_pack.id,
        reason="Admitted the recommended Business Flow Skill Pack.",
        normalization_applied=normalization_applied,
    )


def _normalize_recommendation(
    recommendation: BusinessFlowSkillPackRecommendation,
) -> BusinessFlowSkillPackRecommendation:
    candidate_packs = tuple(
        sorted(
            recommendation.candidate_packs,
            key=lambda candidate: candidate.confidence,
            reverse=True,
        )
    )
    if candidate_packs == recommendation.candidate_packs:
        return recommendation
    return BusinessFlowSkillPackRecommendation(
        recommendation_id=recommendation.recommendation_id,
        intent_resolution_id=recommendation.intent_resolution_id,
        recommendation_type=recommendation.recommendation_type,
        confidence=recommendation.confidence,
        reason=recommendation.reason,
        candidate_packs=candidate_packs,
        requires_task_split=recommendation.requires_task_split,
    )


def _result(
    recommendation: BusinessFlowSkillPackRecommendation,
    *,
    decision: BusinessFlowSkillPackAdmissionDecision,
    selected_pack_id: str | None,
    reason: str,
    failure_reason: str | None = None,
    normalization_applied: bool = False,
) -> BusinessFlowSkillPackAdmissionResult:
    admission = BusinessFlowSkillPackAdmission(
        admission_id=f"bfsp_adm_{recommendation.intent_resolution_id}",
        recommendation_id=recommendation.recommendation_id,
        decision=decision,
        selected_pack_id=selected_pack_id,
        reason=reason,
        failure_reason=failure_reason,
        trace_summary=_trace_summary(
            recommendation,
            decision=decision,
            selected_pack_id=selected_pack_id,
            failure_reason=failure_reason,
            normalization_applied=normalization_applied,
        ),
    )
    return BusinessFlowSkillPackAdmissionResult(
        recommendation=recommendation,
        admission=admission,
    )


def _trace_summary(
    recommendation: BusinessFlowSkillPackRecommendation,
    *,
    decision: BusinessFlowSkillPackAdmissionDecision,
    selected_pack_id: str | None,
    failure_reason: str | None,
    normalization_applied: bool,
) -> Mapping[str, object]:
    summary: dict[str, object] = {
        "decision": decision.value,
        "selected_pack_id": selected_pack_id,
        "candidate_count": len(recommendation.candidate_packs),
        "recommendation_type": recommendation.recommendation_type.value,
        "route_confidence": recommendation.confidence,
        "requires_task_split": recommendation.requires_task_split,
        "normalization_applied": normalization_applied,
    }
    if failure_reason is not None:
        summary["failure_reason"] = failure_reason
    if recommendation.candidate_packs:
        summary["candidate_packs"] = [
            _candidate_pack_trace(candidate)
            for candidate in recommendation.candidate_packs
        ]
    return summary


def _candidate_pack_trace(candidate: BusinessFlowCandidatePack) -> Mapping[str, object]:
    return {
        "pack_id": candidate.pack_id,
        "confidence": candidate.confidence,
        "reason": candidate.reason,
    }
