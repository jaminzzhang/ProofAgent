from __future__ import annotations

from proof_agent.contracts import (
    BusinessFlowSkillPackAdmission,
    BusinessFlowSkillPackAdmissionDecision,
    BusinessFlowSkillPackAdmissionResult,
    BusinessFlowSkillPackDefinition,
    BusinessFlowSkillPackRecommendation,
    IntentResolution,
)


def admit_business_flow_skill_pack(
    intent_resolution: IntentResolution,
    skill_packs: tuple[BusinessFlowSkillPackDefinition, ...],
    *,
    default_pack_id: str | None = None,
    authorization_context_present: bool = True,
    ready_pack_ids: tuple[str, ...] | None = None,
) -> BusinessFlowSkillPackAdmissionResult:
    """Recommend and admit a Primary Business Flow Skill Pack from a frozen set."""

    matched_packs = tuple(
        pack for pack in skill_packs if _matches_intent(intent_resolution, pack)
    )
    candidate_pack_ids = tuple(pack.id for pack in matched_packs)
    recommended_pack_id = candidate_pack_ids[0] if len(candidate_pack_ids) == 1 else None
    recommendation = BusinessFlowSkillPackRecommendation(
        recommendation_id=f"bfsp_rec_{intent_resolution.resolution_id}",
        intent_resolution_id=intent_resolution.resolution_id,
        recommended_pack_id=recommended_pack_id,
        candidate_pack_ids=candidate_pack_ids,
        confidence=intent_resolution.confidence,
        reason=_recommendation_reason(candidate_pack_ids),
    )
    if len(candidate_pack_ids) != 1:
        failure_reason = "ambiguous" if candidate_pack_ids else "missing"
        admission = BusinessFlowSkillPackAdmission(
            admission_id=f"bfsp_adm_{intent_resolution.resolution_id}",
            recommendation_id=recommendation.recommendation_id,
            decision=BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION,
            selected_pack_id=None,
            reason=_clarification_reason(candidate_pack_ids),
            failure_reason=failure_reason,
            trace_summary={
                "decision": BusinessFlowSkillPackAdmissionDecision.NEEDS_CLARIFICATION.value,
                "selected_pack_id": None,
                "candidate_count": len(candidate_pack_ids),
                "failure_reason": failure_reason,
            },
        )
        return BusinessFlowSkillPackAdmissionResult(
            recommendation=recommendation,
            admission=admission,
        )
    admission = _admission_for_match(
        intent_resolution,
        matched_packs[0],
        admission_id=f"bfsp_adm_{intent_resolution.resolution_id}",
        recommendation_id=recommendation.recommendation_id,
        default_pack_id=default_pack_id,
        available_pack_ids={pack.id for pack in skill_packs},
        authorization_context_present=authorization_context_present,
        ready_pack_ids=ready_pack_ids,
    )
    return BusinessFlowSkillPackAdmissionResult(
        recommendation=recommendation,
        admission=admission,
    )


def _recommendation_reason(candidate_pack_ids: tuple[str, ...]) -> str:
    if len(candidate_pack_ids) == 1:
        return "Matched Business Flow Skill Pack intent patterns."
    if len(candidate_pack_ids) > 1:
        return "Multiple Business Flow Skill Packs matched the resolved intent."
    return "No Business Flow Skill Pack matched the resolved intent."


def _clarification_reason(candidate_pack_ids: tuple[str, ...]) -> str:
    if candidate_pack_ids:
        return "Multiple Business Flow Skill Packs matched the resolved intent."
    return "No Business Flow Skill Pack matched the resolved intent."


def _admission_for_match(
    intent_resolution: IntentResolution,
    skill_pack: BusinessFlowSkillPackDefinition,
    *,
    admission_id: str,
    recommendation_id: str,
    default_pack_id: str | None,
    available_pack_ids: set[str],
    authorization_context_present: bool,
    ready_pack_ids: tuple[str, ...] | None,
) -> BusinessFlowSkillPackAdmission:
    if ready_pack_ids is not None and skill_pack.id not in set(ready_pack_ids):
        return BusinessFlowSkillPackAdmission(
            admission_id=admission_id,
            recommendation_id=recommendation_id,
            decision=BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED,
            selected_pack_id=None,
            reason="Recommended Business Flow Skill Pack is not ready for admission.",
            failure_reason="not_ready",
            trace_summary={
                "decision": BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED.value,
                "selected_pack_id": None,
                "candidate_count": 1,
                "failure_reason": "not_ready",
            },
        )
    if (
        skill_pack.admission.require_authorization_context
        and not authorization_context_present
    ):
        return BusinessFlowSkillPackAdmission(
            admission_id=admission_id,
            recommendation_id=recommendation_id,
            decision=BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED,
            selected_pack_id=None,
            reason=(
                "Business Flow Skill Pack requires authorization context, but no "
                "authorized context was available."
            ),
            failure_reason="unauthorized",
            trace_summary={
                "decision": BusinessFlowSkillPackAdmissionDecision.FAILED_CLOSED.value,
                "selected_pack_id": None,
                "candidate_count": 1,
                "failure_reason": "unauthorized",
            },
        )
    if intent_resolution.confidence < skill_pack.admission.min_confidence:
        if default_pack_id is not None and default_pack_id in available_pack_ids:
            return BusinessFlowSkillPackAdmission(
                admission_id=admission_id,
                recommendation_id=recommendation_id,
                decision=BusinessFlowSkillPackAdmissionDecision.SAFE_DEFAULT,
                selected_pack_id=default_pack_id,
                reason=(
                    "Recommended Business Flow Skill Pack did not meet admission "
                    "confidence; selected the configured safe default."
                ),
                failure_reason="not_admissible",
                trace_summary={
                    "decision": BusinessFlowSkillPackAdmissionDecision.SAFE_DEFAULT.value,
                    "selected_pack_id": default_pack_id,
                    "candidate_count": 1,
                    "failure_reason": "not_admissible",
                },
            )
        return BusinessFlowSkillPackAdmission(
            admission_id=admission_id,
            recommendation_id=recommendation_id,
            decision=BusinessFlowSkillPackAdmissionDecision.REFUSED,
            selected_pack_id=None,
            reason=(
                "Recommended Business Flow Skill Pack did not meet admission "
                "confidence and no safe default was configured."
            ),
            failure_reason="not_admissible",
            trace_summary={
                "decision": BusinessFlowSkillPackAdmissionDecision.REFUSED.value,
                "selected_pack_id": None,
                "candidate_count": 1,
                "failure_reason": "not_admissible",
            },
        )
    return BusinessFlowSkillPackAdmission(
        admission_id=admission_id,
        recommendation_id=recommendation_id,
        decision=BusinessFlowSkillPackAdmissionDecision.ADMITTED,
        selected_pack_id=skill_pack.id,
        reason="Admitted the uniquely recommended Business Flow Skill Pack.",
        trace_summary={
            "decision": BusinessFlowSkillPackAdmissionDecision.ADMITTED.value,
            "selected_pack_id": skill_pack.id,
            "candidate_count": 1,
        },
    )


def _matches_intent(
    intent_resolution: IntentResolution,
    skill_pack: BusinessFlowSkillPackDefinition,
) -> bool:
    searchable = " ".join(
        (
            intent_resolution.domain_intent,
            intent_resolution.user_goal,
            *intent_resolution.known_facts,
        )
    ).lower()
    return any(pattern.lower() in searchable for pattern in skill_pack.intent_patterns)
