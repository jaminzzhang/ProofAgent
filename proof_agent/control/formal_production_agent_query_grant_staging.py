"""Candidate-bound Query Grant staging before formal online smoke."""

from __future__ import annotations

from proof_agent.configuration.knowledge_release import (
    require_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    FormalProductionAgentQueryGrantStaging,
    FormalProductionAgentReferenceStaging,
    ProductionAgentKnowledgeQueryGrantRequest,
    ProvisionedProductionAgentKnowledgeQueryGrant,
)
from proof_agent.contracts.ports import KnowledgeQueryGrantProvisioner
from proof_agent.control.formal_production_agent_candidate import (
    require_formal_production_agent_candidate,
)


class FormalProductionAgentQueryGrantStagingRejected(RuntimeError):
    """Stable fail-closed rejection before online smoke or publication."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentQueryGrantStager:
    """Provision one exact KSS Query Grant without publishing the Agent."""

    def __init__(self, *, provisioner: KnowledgeQueryGrantProvisioner) -> None:
        self._provisioner = provisioner

    def stage(
        self,
        *,
        reference_staging: FormalProductionAgentReferenceStaging,
    ) -> FormalProductionAgentQueryGrantStaging:
        validated_staging = _require_reference_staging(reference_staging)
        release = validated_staging.preparation.candidate.knowledge_release_candidate
        try:
            request = ProductionAgentKnowledgeQueryGrantRequest(
                knowledge_base_release_id=release.knowledge_base_release_id,
            )
        except Exception as exc:
            raise FormalProductionAgentQueryGrantStagingRejected(
                code="query_grant_request_invalid",
                detail="The exact KSS Query Grant request is invalid.",
            ) from exc

        try:
            provisioned = self._provisioner.provision_query_grant(request)
        except Exception as exc:
            raise FormalProductionAgentQueryGrantStagingRejected(
                code="query_grant_provisioning_unavailable",
                detail="The exact KSS Query Grant could not be provisioned.",
            ) from exc

        try:
            grant = ProvisionedProductionAgentKnowledgeQueryGrant.model_validate(
                provisioned.model_dump(mode="python")
            )
            return FormalProductionAgentQueryGrantStaging(
                reference_staging=validated_staging,
                query_grant=grant,
            )
        except Exception as exc:
            raise FormalProductionAgentQueryGrantStagingRejected(
                code="query_grant_integrity_invalid",
                detail="The provisioned KSS Query Grant integrity check failed.",
            ) from exc


def _require_reference_staging(
    staging: FormalProductionAgentReferenceStaging,
) -> FormalProductionAgentReferenceStaging:
    try:
        validated = FormalProductionAgentReferenceStaging.model_validate(
            staging.model_dump(mode="python")
        )
        preparation = validated.preparation
        require_formal_production_agent_candidate(preparation.candidate)
        require_formal_production_agent_phase_f_record(
            record=preparation.provisional_version.phase_f_record,
            candidate=preparation.candidate,
        )
        return validated
    except Exception as exc:
        raise FormalProductionAgentQueryGrantStagingRejected(
            code="query_grant_reference_staging_integrity_invalid",
            detail="The Formal Production Agent Reference staging integrity check failed.",
        ) from exc


__all__ = [
    "FormalProductionAgentQueryGrantStager",
    "FormalProductionAgentQueryGrantStagingRejected",
]
