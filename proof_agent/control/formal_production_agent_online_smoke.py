"""Exact online smoke after Formal Production Agent Reference staging."""

from __future__ import annotations

from typing import Protocol

from proof_agent.configuration.knowledge_release import (
    require_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    FormalProductionAgentOnlineSmokeQualification,
    FormalProductionAgentOnlineSmokeRequest,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentQueryGrantStaging,
    ReceiptOutcome,
)
from proof_agent.control.formal_production_agent_candidate import (
    require_formal_production_agent_candidate,
)


class FormalProductionAgentOnlineSmokeValidator(Protocol):
    """Execution boundary that validates one exact registered candidate online."""

    def validate_online_smoke(
        self,
        request: FormalProductionAgentOnlineSmokeRequest,
        *,
        query_grant_staging: FormalProductionAgentQueryGrantStaging,
    ) -> FormalProductionAgentOnlineSmokeResult: ...


class FormalProductionAgentOnlineSmokeRejected(RuntimeError):
    """Stable fail-closed rejection before publication or activation exists."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentOnlineSmokeService:
    """Qualify an exact registered staging without publication side effects."""

    def __init__(
        self,
        *,
        online_smoke_validator: FormalProductionAgentOnlineSmokeValidator,
    ) -> None:
        self._online_smoke_validator = online_smoke_validator

    def qualify(
        self,
        *,
        query_grant_staging: FormalProductionAgentQueryGrantStaging,
        smoke_question: str,
    ) -> FormalProductionAgentOnlineSmokeQualification:
        validated_staging = _require_staging(query_grant_staging)
        question = _require_question(smoke_question)
        request = _smoke_request(validated_staging, question=question)
        try:
            raw_result = self._online_smoke_validator.validate_online_smoke(
                request,
                query_grant_staging=validated_staging,
            )
        except Exception as exc:
            raise FormalProductionAgentOnlineSmokeRejected(
                code="online_smoke_unavailable",
                detail="The Formal Production Agent online smoke validator is unavailable.",
            ) from exc
        try:
            result = FormalProductionAgentOnlineSmokeResult.model_validate(
                raw_result.model_dump(mode="python")
            )
        except Exception as exc:
            raise FormalProductionAgentOnlineSmokeRejected(
                code="online_smoke_integrity_invalid",
                detail="The Formal Production Agent online smoke result integrity check failed.",
            ) from exc
        if (
            result.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
            or result.accepted_citation_count < 1
        ):
            raise FormalProductionAgentOnlineSmokeRejected(
                code="online_smoke_failed",
                detail="The Formal Production Agent online smoke did not pass.",
            )
        try:
            return FormalProductionAgentOnlineSmokeQualification(
                query_grant_staging=validated_staging,
                request=request,
                result=result,
            )
        except Exception as exc:
            raise FormalProductionAgentOnlineSmokeRejected(
                code="online_smoke_integrity_invalid",
                detail="The Formal Production Agent online smoke result integrity check failed.",
            ) from exc


def _require_staging(
    staging: FormalProductionAgentQueryGrantStaging,
) -> FormalProductionAgentQueryGrantStaging:
    try:
        validated = FormalProductionAgentQueryGrantStaging.model_validate(
            staging.model_dump(mode="python")
        )
        preparation = validated.reference_staging.preparation
        require_formal_production_agent_candidate(preparation.candidate)
        require_formal_production_agent_phase_f_record(
            record=preparation.provisional_version.phase_f_record,
            candidate=preparation.candidate,
        )
        return validated
    except Exception as exc:
        raise FormalProductionAgentOnlineSmokeRejected(
            code="online_smoke_query_grant_staging_integrity_invalid",
            detail="The Formal Production Agent Query Grant staging integrity check failed.",
        ) from exc


def _require_question(value: str) -> str:
    try:
        normalized = value.strip()
    except Exception as exc:
        raise FormalProductionAgentOnlineSmokeRejected(
            code="online_smoke_question_invalid",
            detail="The Formal Production Agent online smoke question is invalid.",
        ) from exc
    if not normalized or len(normalized) > 4_000:
        raise FormalProductionAgentOnlineSmokeRejected(
            code="online_smoke_question_invalid",
            detail="The Formal Production Agent online smoke question is invalid.",
        )
    return normalized


def _smoke_request(
    staging: FormalProductionAgentQueryGrantStaging,
    *,
    question: str,
) -> FormalProductionAgentOnlineSmokeRequest:
    reference_staging = staging.reference_staging
    preparation = reference_staging.preparation
    candidate = preparation.candidate
    provisional = preparation.provisional_version
    release = candidate.knowledge_release_candidate
    try:
        return FormalProductionAgentOnlineSmokeRequest(
            agent_id=candidate.agent_id,
            provisional_version_id=provisional.version_id,
            validation_run_id=provisional.validation_run_id,
            formal_candidate_sha256=candidate.formal_candidate_sha256,
            knowledge_release_candidate_sha256=(candidate.knowledge_release_candidate_sha256),
            knowledge_space_id=release.knowledge_space_id,
            knowledge_base_id=release.knowledge_base_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            release_reference_id=reference_staging.release_reference.release_reference_id,
            smoke_question=question,
        )
    except Exception as exc:
        raise FormalProductionAgentOnlineSmokeRejected(
            code="online_smoke_request_invalid",
            detail="The Formal Production Agent online smoke request is invalid.",
        ) from exc


__all__ = [
    "FormalProductionAgentOnlineSmokeRejected",
    "FormalProductionAgentOnlineSmokeService",
    "FormalProductionAgentOnlineSmokeValidator",
]
