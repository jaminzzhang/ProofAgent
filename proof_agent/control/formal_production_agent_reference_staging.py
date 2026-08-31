"""Reference-first staging for an authorized Formal Production Agent candidate."""

from __future__ import annotations

from typing import Protocol

from proof_agent.configuration.knowledge_release import (
    require_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    FormalProductionAgentPhaseFPreparation,
    FormalProductionAgentReferenceStaging,
    ProductionAgentReleaseReferenceRequest,
    RegisteredProductionAgentReleaseReference,
)
from proof_agent.control.formal_production_agent_candidate import (
    require_formal_production_agent_candidate,
)


class FormalProductionAgentReleaseReferenceRegistrar(Protocol):
    """Authenticated KSS client boundary; implementations own credentials and transport."""

    def register_release_reference(
        self,
        request: ProductionAgentReleaseReferenceRequest,
        *,
        idempotency_key: str,
    ) -> RegisteredProductionAgentReleaseReference: ...


class FormalProductionAgentReferenceStagingRejected(RuntimeError):
    """Stable fail-closed rejection before publication or activation exists."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentReferenceStager:
    """Register one exact KSS Reference without publishing or activating the Agent."""

    def __init__(
        self,
        *,
        registrar: FormalProductionAgentReleaseReferenceRegistrar,
    ) -> None:
        self._registrar = registrar

    def stage(
        self,
        *,
        preparation: FormalProductionAgentPhaseFPreparation,
    ) -> FormalProductionAgentReferenceStaging:
        validated_preparation = _require_preparation(preparation)
        release = validated_preparation.candidate.knowledge_release_candidate
        try:
            request = ProductionAgentReleaseReferenceRequest(
                knowledge_space_id=release.knowledge_space_id,
                knowledge_base_id=release.knowledge_base_id,
                knowledge_base_release_id=release.knowledge_base_release_id,
                external_resource_id=validated_preparation.provisional_version.version_id,
            )
        except Exception as exc:
            raise FormalProductionAgentReferenceStagingRejected(
                code="reference_request_invalid",
                detail="The exact KSS Release Reference request is invalid.",
            ) from exc

        try:
            registered = self._registrar.register_release_reference(
                request,
                idempotency_key=_reference_idempotency_key(request),
            )
        except Exception as exc:
            raise FormalProductionAgentReferenceStagingRejected(
                code="reference_registration_unavailable",
                detail="The exact KSS Release Reference could not be registered.",
            ) from exc

        try:
            validated_reference = RegisteredProductionAgentReleaseReference.model_validate(
                registered.model_dump(mode="python")
            )
            staging = FormalProductionAgentReferenceStaging(
                preparation=validated_preparation,
                release_reference=validated_reference,
            )
        except Exception as exc:
            raise FormalProductionAgentReferenceStagingRejected(
                code="reference_registration_integrity_invalid",
                detail="The registered KSS Release Reference integrity check failed.",
            ) from exc
        return staging


def _require_preparation(
    preparation: FormalProductionAgentPhaseFPreparation,
) -> FormalProductionAgentPhaseFPreparation:
    try:
        require_formal_production_agent_candidate(preparation.candidate)
        require_formal_production_agent_phase_f_record(
            record=preparation.provisional_version.phase_f_record,
            candidate=preparation.candidate,
        )
        return FormalProductionAgentPhaseFPreparation.model_validate(
            preparation.model_dump(mode="python")
        )
    except Exception as exc:
        raise FormalProductionAgentReferenceStagingRejected(
            code="reference_preparation_integrity_invalid",
            detail="The Formal Production Agent Phase F preparation integrity check failed.",
        ) from exc


def _reference_idempotency_key(request: ProductionAgentReleaseReferenceRequest) -> str:
    return f"formal-agent-reference:{request.external_resource_id}"


__all__ = [
    "FormalProductionAgentReferenceStager",
    "FormalProductionAgentReferenceStagingRejected",
    "FormalProductionAgentReleaseReferenceRegistrar",
]
