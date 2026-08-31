"""Candidate-bound Phase F preparation without publication side effects."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import re
from uuid import uuid4

from proof_agent.configuration.knowledge_release import (
    FormalProductionAgentPhaseFAuthority,
    require_formal_production_agent_phase_f_record,
    seal_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    AuditActorFacts,
    FormalProductionAgentCandidate,
    FormalProductionAgentPhaseFPreparation,
    KnowledgeReleaseEvidenceSet,
    ProvisionalProductionAgentVersion,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateRejected,
    require_formal_production_agent_candidate,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)


class FormalProductionAgentPhaseFRejected(RuntimeError):
    """Stable fail-closed rejection before publication or activation exists."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentPhaseFPreparer:
    """Verify exact evidence and produce an authorized, unpublished version candidate."""

    def __init__(
        self,
        *,
        phase_f_authority: FormalProductionAgentPhaseFAuthority,
        identifier_factory: Callable[[], str] = lambda: str(uuid4()),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._phase_f_authority = phase_f_authority
        self._identifier_factory = identifier_factory
        self._clock = clock

    def prepare(
        self,
        *,
        candidate: FormalProductionAgentCandidate,
        evidence: KnowledgeReleaseEvidenceSet,
        actor: AuditActorFacts,
    ) -> FormalProductionAgentPhaseFPreparation:
        try:
            require_formal_production_agent_candidate(candidate)
        except FormalProductionAgentCandidateRejected as exc:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_candidate_integrity_invalid",
                detail="The Formal Production Agent Candidate integrity check failed.",
            ) from exc

        record_id, version_id, validation_run_id = self._new_distinct_identities()
        source = WorkflowStageConfigurationRuntimeSource(
            source_type=(WorkflowStageConfigurationRuntimeSourceType.FORMAL_PRODUCTION_CANDIDATE),
            reference=(
                f"formal_candidate:{candidate.formal_candidate_sha256}:"
                f"provisional_version:{version_id}"
            ),
        )
        try:
            stage_facts = resolve_workflow_stage_runtime_configuration(
                candidate.contract_bundle.agent_yaml,
                source=source,
            )
        except Exception as exc:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_workflow_configuration_invalid",
                detail="The Formal Candidate Workflow Stage configuration is invalid.",
            ) from exc
        if stage_facts is None:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_workflow_configuration_invalid",
                detail="The Formal Candidate Workflow Stage configuration is invalid.",
            )

        prepared_at = _timestamp(self._clock())
        record = seal_formal_production_agent_phase_f_record(
            record_id=record_id,
            provisional_version_id=version_id,
            validation_run_id=validation_run_id,
            candidate=candidate,
            evidence=evidence,
            created_at=prepared_at,
            created_by=actor.subject,
        )
        try:
            require_formal_production_agent_phase_f_record(
                record=record,
                candidate=candidate,
            )
        except Exception as exc:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_evidence_invalid",
                detail="The Formal Candidate Phase F evidence is invalid.",
            ) from exc

        provisional = ProvisionalProductionAgentVersion(
            agent_id=candidate.agent_id,
            version_id=version_id,
            source_draft_id=candidate.draft_id,
            source_draft_revision=candidate.draft_revision,
            validation_run_id=validation_run_id,
            display_name=candidate.display_name,
            purpose=candidate.purpose,
            contract_bundle=candidate.contract_bundle,
            prepared_at=prepared_at,
            prepared_by=actor.subject,
            formal_candidate_sha256=candidate.formal_candidate_sha256,
            knowledge_release_candidate_sha256=(candidate.knowledge_release_candidate_sha256),
            resolved_knowledge_bindings=candidate.resolved_knowledge_bindings,
            phase_f_record=record,
            workflow_stage_availability=stage_facts.workflow_stage_availability,
            effective_workflow_stage_configuration=(stage_facts.effective_stage_configuration),
            workflow_stage_configuration_source=source,
        )
        try:
            authorized = self._phase_f_authority.verify_phase_f_record(record)
        except Exception as exc:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_authority_unavailable",
                detail="The independent Phase F authority is unavailable.",
            ) from exc
        if authorized is not True:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_authority_denied",
                detail="The independent Phase F authority denied the candidate.",
            )
        return FormalProductionAgentPhaseFPreparation(
            candidate=candidate,
            provisional_version=provisional,
        )

    def _new_distinct_identities(self) -> tuple[str, str, str]:
        identities = (
            _bounded_identifier(self._identifier_factory()),
            _bounded_identifier(self._identifier_factory()),
            _bounded_identifier(self._identifier_factory()),
        )
        if len(set(identities)) != 3:
            raise FormalProductionAgentPhaseFRejected(
                code="phase_f_identity_invalid",
                detail="Phase F preparation identities must be distinct.",
            )
        return identities


def _bounded_identifier(value: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", normalized) is None:
        raise FormalProductionAgentPhaseFRejected(
            code="phase_f_identity_invalid",
            detail="Phase F preparation identity is invalid.",
        )
    return normalized


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalProductionAgentPhaseFRejected(
            code="phase_f_clock_invalid",
            detail="Phase F preparation clock must be timezone-aware.",
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "FormalProductionAgentPhaseFPreparer",
    "FormalProductionAgentPhaseFRejected",
]
