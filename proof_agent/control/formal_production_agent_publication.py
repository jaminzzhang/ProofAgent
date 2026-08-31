"""Formal Production Agent publication over exact pre-publication evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentPublicationRecord,
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    FormalProductionAgentCandidate,
    FormalProductionAgentPublicationCommandState,
    FormalProductionAgentPublicationEvidence,
    KnowledgeReleaseEvidenceSet,
    ProductionKssBindingProfile,
    PublishedAgentVersion,
    PublishedWorkflowStageConfigurationSnapshot,
)
from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationCommandRecord,
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistencePointerConflictError,
    complete_formal_publication_command_success,
)
from proof_agent.contracts.ports import (
    ConfigurationUnitOfWork,
    FormalProductionAgentPublicationCommandRepository,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateAssembler,
)
from proof_agent.control.formal_production_agent_online_smoke import (
    FormalProductionAgentOnlineSmokeService,
)
from proof_agent.control.formal_production_agent_phase_f import (
    FormalProductionAgentPhaseFPreparer,
    formal_production_agent_phase_f_identity_for_command,
)
from proof_agent.control.formal_production_agent_query_grant_staging import (
    FormalProductionAgentQueryGrantStager,
)
from proof_agent.control.formal_production_agent_reference_staging import (
    FormalProductionAgentReferenceStager,
)
from proof_agent.control.production_agent_publication import SOLE_PRODUCTION_AGENT_ID


class FormalProductionAgentPublicationRejected(RuntimeError):
    """Stable fail-closed rejection at the formal persistence boundary."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentPublisher:
    """Orchestrate exact evidence, then atomically publish and activate one Agent."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], ConfigurationUnitOfWork],
        candidate_assembler: FormalProductionAgentCandidateAssembler,
        phase_f_preparer: FormalProductionAgentPhaseFPreparer,
        reference_stager: FormalProductionAgentReferenceStager,
        query_grant_stager: FormalProductionAgentQueryGrantStager,
        online_smoke_service: FormalProductionAgentOnlineSmokeService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._candidate_assembler = candidate_assembler
        self._phase_f_preparer = phase_f_preparer
        self._reference_stager = reference_stager
        self._query_grant_stager = query_grant_stager
        self._online_smoke_service = online_smoke_service
        self._clock = clock

    def preflight(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
        binding_profile: ProductionKssBindingProfile,
    ) -> FormalProductionAgentCandidate:
        """Assemble one exact candidate without entering any publication stage."""

        return self._candidate_assembler.assemble(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            binding_profile=binding_profile,
        )

    def publish(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
        binding_profile: ProductionKssBindingProfile,
        evidence: KnowledgeReleaseEvidenceSet,
        smoke_question: str,
        actor: AuditActorFacts,
        command_record: FormalProductionAgentPublicationCommandRecord | None = None,
    ) -> AgentPublicationRecord:
        candidate = self.preflight(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            binding_profile=binding_profile,
        )
        if command_record is not None:
            return self.publish_checkpointed_candidate(
                candidate=candidate,
                evidence=evidence,
                smoke_question=smoke_question,
                actor=actor,
                command_record=command_record,
            )
        return self._publish_candidate(
            candidate=candidate,
            evidence=evidence,
            smoke_question=smoke_question,
            actor=actor,
            command_record=None,
        )

    def publish_checkpointed_candidate(
        self,
        *,
        candidate: FormalProductionAgentCandidate,
        evidence: KnowledgeReleaseEvidenceSet,
        smoke_question: str,
        actor: AuditActorFacts,
        command_record: FormalProductionAgentPublicationCommandRecord,
    ) -> AgentPublicationRecord:
        """Publish only when the current command froze the exact candidate identity."""

        receipt = command_record.receipt
        checkpoint = command_record.candidate_checkpoint
        if (
            receipt.state is not FormalProductionAgentPublicationCommandState.IN_PROGRESS
            or command_record.execution_claim is None
            or command_record.actor_subject != actor.subject
            or receipt.agent_id != candidate.agent_id
            or receipt.draft_id != candidate.draft_id
            or receipt.draft_revision != candidate.draft_revision
            or checkpoint is None
            or checkpoint.formal_candidate_sha256 != candidate.formal_candidate_sha256
            or checkpoint.knowledge_release_candidate_sha256
            != candidate.knowledge_release_candidate_sha256
        ):
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_candidate_checkpoint_conflict",
                detail="The durable Formal Candidate checkpoint does not match.",
            )
        return self._publish_candidate(
            candidate=candidate,
            evidence=evidence,
            smoke_question=smoke_question,
            actor=actor,
            command_record=command_record,
        )

    def _publish_candidate(
        self,
        *,
        candidate: FormalProductionAgentCandidate,
        evidence: KnowledgeReleaseEvidenceSet,
        smoke_question: str,
        actor: AuditActorFacts,
        command_record: FormalProductionAgentPublicationCommandRecord | None,
    ) -> AgentPublicationRecord:
        """Publish one internally verified exact candidate through governed stages."""

        preparation = self._phase_f_preparer.prepare(
            candidate=candidate,
            evidence=evidence,
            actor=actor,
            identity=(
                None
                if command_record is None
                else formal_production_agent_phase_f_identity_for_command(
                    command_record.receipt.command_id
                )
            ),
            prepared_at=(None if command_record is None else command_record.receipt.started_at),
        )
        active_expectation = self._capture_active_expectation(agent_id=candidate.agent_id)
        reference_staging = self._reference_stager.stage(preparation=preparation)
        query_grant_staging = self._query_grant_stager.stage(
            reference_staging=reference_staging,
        )
        qualification = self._online_smoke_service.qualify(
            query_grant_staging=query_grant_staging,
            smoke_question=smoke_question,
        )
        qualified_reference_staging = qualification.query_grant_staging.reference_staging
        provisional = qualified_reference_staging.preparation.provisional_version
        try:
            published_at = _timestamp(self._clock())
            formal_evidence = FormalProductionAgentPublicationEvidence(
                source_draft_revision=candidate.draft_revision,
                phase_f_record=provisional.phase_f_record,
                release_reference=qualified_reference_staging.release_reference,
                online_smoke_result=qualification.result,
            )
            operation = ConfigurationOperationAudit(
                operation_id=str(uuid4()),
                operation=ConfigurationOperation.PUBLISHED,
                actor=actor.subject,
                created_at=published_at,
                summary="Published the exact Formal Production Agent Candidate.",
                metadata=_publication_metadata(
                    formal_evidence=formal_evidence,
                    active_expectation=active_expectation,
                ),
            )
            version = PublishedAgentVersion(
                agent_id=provisional.agent_id,
                version_id=provisional.version_id,
                source_draft_id=provisional.source_draft_id,
                validation_run_id=provisional.validation_run_id,
                display_name=provisional.display_name,
                purpose=provisional.purpose,
                contract_bundle=provisional.contract_bundle,
                published_at=published_at,
                published_by=actor.subject,
                operation_audit=(operation,),
                resolved_knowledge_bindings=provisional.resolved_knowledge_bindings,
                formal_production_evidence=formal_evidence,
                workflow_stage_availability=provisional.workflow_stage_availability,
                effective_workflow_stage_configuration=(
                    PublishedWorkflowStageConfigurationSnapshot.model_validate(
                        provisional.effective_workflow_stage_configuration.model_dump(mode="python")
                    )
                ),
            )
            publication = AgentPublicationRecord(
                version=version,
                activation=ActiveAgentVersion(
                    agent_id=version.agent_id,
                    version_id=version.version_id,
                    activated_at=published_at,
                    activated_by=actor.subject,
                ),
                draft_revision=candidate.draft_revision,
                active_pointer_expectation=active_expectation,
            )
            audit = AuditMetadataRecord(
                audit_id=str(uuid4()),
                category=AuditCategory.CONFIGURATION,
                event_type="agent.formal_version_published",
                outcome=AuditOutcome.SUCCEEDED,
                actor=actor,
                occurred_at=published_at,
                target_type="agent_version",
                target_id=version.version_id,
                metadata={
                    "agent_id": version.agent_id,
                    "draft_id": version.source_draft_id,
                    **_publication_metadata(
                        formal_evidence=formal_evidence,
                        active_expectation=active_expectation,
                    ),
                },
            )
        except FormalProductionAgentPublicationRejected:
            raise
        except Exception as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_integrity_invalid",
                detail="The Formal Production Agent publication integrity check failed.",
            ) from exc

        try:
            with self._unit_of_work_factory() as uow:
                saved = uow.agents.publish_version(
                    publication,
                    expected_draft_revision=candidate.draft_revision,
                )
                validated_saved = AgentPublicationRecord.model_validate(
                    saved.model_dump(mode="python")
                )
                if validated_saved != publication:
                    raise FormalProductionAgentPublicationRejected(
                        code="formal_publication_storage_integrity_invalid",
                        detail=(
                            "The Formal Production Agent publication storage result "
                            "is inconsistent."
                        ),
                    )
                if command_record is not None:
                    expected_command = complete_formal_publication_command_success(
                        command_record,
                        validated_saved,
                    )
                    command_repository = cast(
                        FormalProductionAgentPublicationCommandRepository,
                        getattr(uow, "formal_publication_commands"),
                    )
                    saved_command = command_repository.complete(expected_command)
                    validated_command = (
                        FormalProductionAgentPublicationCommandRecord.model_validate(
                            saved_command.model_dump(mode="python")
                        )
                    )
                    if validated_command != expected_command:
                        raise FormalProductionAgentPublicationRejected(
                            code="formal_publication_storage_integrity_invalid",
                            detail=(
                                "The formal publication command storage result is inconsistent."
                            ),
                        )
                uow.audit.append(audit)
                uow.commit()
        except PersistencePointerConflictError as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_active_pointer_conflict",
                detail="The Active Agent Version changed during formal publication.",
            ) from exc
        except PersistenceConflictError as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_draft_revision_conflict",
                detail="The Agent Draft changed during formal publication.",
            ) from exc
        except PersistenceInvariantError as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_storage_integrity_invalid",
                detail="The Formal Production Agent storage integrity check failed.",
            ) from exc
        except FormalProductionAgentPublicationRejected:
            raise
        except Exception as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_storage_unavailable",
                detail="Formal Production Agent publication storage is unavailable.",
            ) from exc
        return validated_saved

    def _capture_active_expectation(
        self,
        *,
        agent_id: str,
    ) -> ActiveAgentPointerExpectation:
        try:
            with self._unit_of_work_factory() as uow:
                active_versions = tuple(uow.agents.list_active())
        except Exception as exc:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_active_pointer_unavailable",
                detail="The Active Agent Version expectation is unavailable.",
            ) from exc
        if (
            any(item.agent_id != SOLE_PRODUCTION_AGENT_ID for item in active_versions)
            or len(active_versions) > 1
        ):
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_active_invariant_invalid",
                detail="The sole production Agent activation invariant is invalid.",
            )
        active = None if not active_versions else active_versions[0]
        if active is not None and active.agent_id != agent_id:
            raise FormalProductionAgentPublicationRejected(
                code="formal_publication_active_invariant_invalid",
                detail="The sole production Agent activation invariant is invalid.",
            )
        return ActiveAgentPointerExpectation(
            version_id=None if active is None else active.version_id
        )


def _publication_metadata(
    *,
    formal_evidence: FormalProductionAgentPublicationEvidence,
    active_expectation: ActiveAgentPointerExpectation,
) -> dict[str, object]:
    smoke = formal_evidence.online_smoke_result
    return {
        "draft_revision": formal_evidence.source_draft_revision,
        "phase_f_record_id": formal_evidence.phase_f_record.record_id,
        "phase_f_record_sha256": formal_evidence.phase_f_record.record_sha256,
        "release_reference_id": formal_evidence.release_reference.release_reference_id,
        "validation_run_id": smoke.validation_run_id,
        "accepted_citation_count": smoke.accepted_citation_count,
        "validation_trace_ref": smoke.trace_ref.model_dump(mode="json"),
        "validation_receipt_ref": smoke.receipt_ref.model_dump(mode="json"),
        "replaced_active_version_id": active_expectation.version_id,
    }


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalProductionAgentPublicationRejected(
            code="formal_publication_clock_invalid",
            detail="Formal publication clock must be timezone-aware.",
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "FormalProductionAgentPublicationRejected",
    "FormalProductionAgentPublisher",
]
