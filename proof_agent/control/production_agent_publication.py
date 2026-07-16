"""Controlled production publication for the sole Hybrid insurance Agent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.configuration.knowledge_release import (
    KnowledgeReleaseEvidenceAuthority,
    seal_knowledge_release_record,
)
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
    DraftAgent,
    ExactArtifactRef,
    KnowledgeReleaseEvidenceSet,
    PublishedAgentVersion,
    PublishedWorkflowStageConfigurationSnapshot,
    ReceiptOutcome,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
    ResolvedSharedAssetVersions,
    SharedAssetKind,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.control.production_agent import (
    ProductionAgentValidationError,
    validate_production_agent_candidate,
)
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.delivery.published_agents import PublishedAgent


SOLE_PRODUCTION_AGENT_ID = "agent_management_insurance_specialist"


@dataclass(frozen=True)
class ProductionAgentCandidateValidation:
    """Exact retained result of one real online candidate smoke run."""

    run_id: str
    outcome: ReceiptOutcome
    accepted_citation_count: int
    trace_ref: ExactArtifactRef
    receipt_ref: ExactArtifactRef


class ProductionAgentCandidateValidator(Protocol):
    def validate(
        self,
        *,
        agent: PublishedAgent,
        version: PublishedAgentVersion,
        question: str,
    ) -> ProductionAgentCandidateValidation: ...


class HybridBindingAuthority(Protocol):
    def resolve_binding_authority(
        self,
        *,
        source_id: str,
        profile_revision_id: str | None,
    ) -> Any: ...


class ProductionAgentPublicationService:
    """Stage a candidate, run it online, then atomically publish and activate it."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], Any],
        binding_authority: HybridBindingAuthority,
        release_authority: KnowledgeReleaseEvidenceAuthority,
        secret_provider: SecretProvider,
        candidate_validator: ProductionAgentCandidateValidator,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._binding_authority = binding_authority
        self._release_authority = release_authority
        self._secret_provider = secret_provider
        self._candidate_validator = candidate_validator
        self._clock = clock

    def publish(
        self,
        *,
        agent_manifest_path: Path,
        evidence: KnowledgeReleaseEvidenceSet,
        smoke_question: str,
        actor: AuditActorFacts,
    ) -> AgentPublicationRecord:
        question = _nonblank(smoke_question, "smoke_question", maximum=4_000)
        manifest_path = agent_manifest_path.resolve()
        manifest = load_agent_manifest(manifest_path)
        if manifest.name != SOLE_PRODUCTION_AGENT_ID:
            raise ProductionAgentValidationError(
                "production publication accepts only the sole insurance Agent"
            )
        if len(manifest.knowledge_bindings) != 1:
            raise ProductionAgentValidationError(
                "initial production online runtime requires exactly one Hybrid binding"
            )
        configured_binding = manifest.knowledge_bindings[0]
        if configured_binding.source_ref.scope != "shared":
            raise ProductionAgentValidationError(
                "production Agent Knowledge binding must reference a shared Source"
            )
        snapshot = self._binding_authority.resolve_binding_authority(
            source_id=configured_binding.source_ref.source_id,
            profile_revision_id=configured_binding.retrieval_profile_revision_id,
        )
        if snapshot is None:
            raise ProductionAgentValidationError(
                "production Agent Hybrid publication authority is unavailable"
            )
        publication = snapshot.publication
        profile = snapshot.retrieval_profile
        if (
            publication.source_id != configured_binding.source_ref.source_id
            or (
                configured_binding.retrieval_profile_revision_id is not None
                and profile.profile_revision_id
                != configured_binding.retrieval_profile_revision_id
            )
        ):
            raise ProductionAgentValidationError(
                "production Agent Hybrid publication authority is stale"
            )
        resolved_bindings = ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedHybridKnowledgeBinding(
                    binding_id=configured_binding.binding_id,
                    source_id=publication.source_id,
                    source_publication_id=publication.publication_id,
                    source_snapshot_id=publication.source_snapshot_id,
                    index_generation_id=publication.generation_id,
                    source_publication_seq=publication.source_publication_seq,
                    retrieval_profile_revision_id=profile.profile_revision_id,
                    manifest_ref=publication.manifest_ref,
                    publication_attestation_id=publication.attestation.attestation_id,
                    failure_mode=cast(
                        Literal["required", "advisory"],
                        configured_binding.failure_mode,
                    ),
                    fusion_weight=configured_binding.fusion_weight,
                ),
            )
        )
        bundle = build_agent_package_contract_bundle(manifest_path)
        now = _timestamp(self._clock())
        draft_id = str(uuid4())
        version_id = str(uuid4())
        validation_run_id = str(uuid4())
        release_record = seal_knowledge_release_record(
            record_id=str(uuid4()),
            contract_bundle=bundle,
            resolved_knowledge_bindings=resolved_bindings,
            shadow_artifact=evidence.shadow,
            capacity_artifact=evidence.capacity,
            acceptance_artifact=evidence.acceptance,
            recovery_artifact=evidence.recovery,
            created_at=now,
            created_by=actor.subject,
        )
        try:
            authorized = self._release_authority.verify_release_record(release_record)
        except Exception as exc:
            raise ProductionAgentValidationError(
                "independent Phase F release authority validation failed"
            ) from exc
        if authorized is not True:
            raise ProductionAgentValidationError(
                "independent Phase F release authority denied the candidate"
            )
        draft = DraftAgent(
            agent_id=manifest.name,
            draft_id=draft_id,
            display_name=manifest.name,
            purpose=manifest.purpose,
            contract_bundle=bundle,
            created_at=now,
            updated_at=now,
            created_by=actor.subject,
            updated_by=actor.subject,
        )
        stage_facts = _stage_facts(bundle.agent_yaml, version_id=version_id)
        provisional_version = PublishedAgentVersion(
            agent_id=manifest.name,
            version_id=version_id,
            source_draft_id=draft_id,
            validation_run_id=validation_run_id,
            display_name=manifest.name,
            purpose=manifest.purpose,
            contract_bundle=bundle,
            published_at=now,
            published_by=actor.subject,
            resolved_knowledge_bindings=resolved_bindings,
            knowledge_release_record=release_record,
            workflow_stage_availability=stage_facts.workflow_stage_availability,
            effective_workflow_stage_configuration=(
                PublishedWorkflowStageConfigurationSnapshot.model_validate(
                    stage_facts.effective_stage_configuration.model_dump(mode="python")
                )
            ),
        )
        provisional_agent = _published_agent(manifest_path, provisional_version)
        validate_production_agent_candidate(
            agent=provisional_agent,
            version=provisional_version,
            secret_provider=self._secret_provider,
        )

        with self._unit_of_work_factory() as uow:
            active_ids = tuple(sorted(item.agent_id for item in uow.agents.list_active()))
            if active_ids and active_ids != (SOLE_PRODUCTION_AGENT_ID,):
                raise ProductionAgentValidationError(
                    "another active Agent violates the sole production Agent invariant"
                )
            current_active = uow.agents.get_active(SOLE_PRODUCTION_AGENT_ID)
            expected_active_version_id = (
                None if current_active is None else current_active.version_id
            )
            source_version = uow.knowledge.resolve_version(publication.source_id)
            if source_version is None or source_version.kind is not SharedAssetKind.KNOWLEDGE_SOURCE:
                raise ProductionAgentValidationError(
                    "published Hybrid Source has no immutable PostgreSQL asset version"
                )
            draft_record = uow.agents.save_draft(draft, expected_revision=0)
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="agent.candidate_staged",
                    target_id=version_id,
                    occurred_at=now,
                    metadata={
                        "draft_id": draft_id,
                        "knowledge_release_record_id": release_record.record_id,
                        "source_publication_id": publication.publication_id,
                    },
                )
            )
            uow.commit()

        version = provisional_version.model_copy(
            update={
                "resolved_shared_asset_versions": ResolvedSharedAssetVersions(
                    versions=(source_version,)
                )
            }
        )
        agent = _published_agent(manifest_path, version)
        validate_production_agent_candidate(
            agent=agent,
            version=version,
            secret_provider=self._secret_provider,
        )
        validation = self._candidate_validator.validate(
            agent=agent,
            version=version,
            question=question,
        )
        _require_successful_candidate_validation(validation, expected_run_id=validation_run_id)
        operation = ConfigurationOperationAudit(
            operation_id=str(uuid4()),
            operation=ConfigurationOperation.PUBLISHED,
            actor=actor.subject,
            created_at=_timestamp(self._clock()),
            summary="Published the sole production Hybrid Agent after Phase F and online smoke.",
            metadata={
                "validation_run_id": validation.run_id,
                "validation_trace_ref": validation.trace_ref.model_dump(mode="json"),
                "validation_receipt_ref": validation.receipt_ref.model_dump(mode="json"),
                "knowledge_release_record_id": release_record.record_id,
            },
        )
        version = version.model_copy(update={"operation_audit": (operation,)})
        published_at = _timestamp(self._clock())
        version = version.model_copy(update={"published_at": published_at})
        publication_record = AgentPublicationRecord(
            version=version,
            activation=ActiveAgentVersion(
                agent_id=version.agent_id,
                version_id=version.version_id,
                activated_at=published_at,
                activated_by=actor.subject,
            ),
            draft_revision=draft_record.revision,
            active_pointer_expectation=ActiveAgentPointerExpectation(
                version_id=expected_active_version_id
            ),
        )
        with self._unit_of_work_factory() as uow:
            saved = uow.agents.publish_version(
                publication_record,
                expected_draft_revision=draft_record.revision,
            )
            uow.audit.append(
                _audit_event(
                    actor=actor,
                    event_type="agent.version_published",
                    target_id=version.version_id,
                    occurred_at=published_at,
                    metadata={
                        "validation_run_id": validation.run_id,
                        "accepted_citation_count": validation.accepted_citation_count,
                        "validation_trace_ref": validation.trace_ref.model_dump(
                            mode="json"
                        ),
                        "validation_receipt_ref": validation.receipt_ref.model_dump(
                            mode="json"
                        ),
                        "knowledge_release_record_id": release_record.record_id,
                    },
                )
            )
            uow.commit()
        return AgentPublicationRecord.model_validate(saved)


def _published_agent(path: Path, version: PublishedAgentVersion) -> PublishedAgent:
    return PublishedAgent(
        agent_id=version.agent_id,
        manifest_path=path,
        display_name=version.display_name,
        purpose=version.purpose,
        customer_facing=False,
        agent_version_id=version.version_id,
        source_draft_id=version.source_draft_id,
        validation_run_id=version.validation_run_id,
        resolved_knowledge_bindings=version.resolved_knowledge_bindings,
        source="postgres_publication",
    )


def _stage_facts(agent_yaml: str, *, version_id: str) -> Any:
    resolved = resolve_workflow_stage_runtime_configuration(
        agent_yaml,
        source=WorkflowStageConfigurationRuntimeSource(
            source_type=WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION,
            reference=f"published_version:{version_id}:effective_workflow_stage_configuration",
        ),
    )
    if resolved is None:
        raise ProductionAgentValidationError(
            "production Agent workflow stage configuration is unavailable"
        )
    return resolved


def _require_successful_candidate_validation(
    validation: ProductionAgentCandidateValidation,
    *,
    expected_run_id: str,
) -> None:
    if (
        validation.run_id != expected_run_id
        or validation.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
        or validation.accepted_citation_count < 1
        or validation.trace_ref == validation.receipt_ref
    ):
        raise ProductionAgentValidationError(
            "production Agent online validation did not answer with governed citations"
        )


def _audit_event(
    *,
    actor: AuditActorFacts,
    event_type: str,
    target_id: str,
    occurred_at: str,
    metadata: dict[str, object],
) -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id=str(uuid4()),
        category=AuditCategory.CONFIGURATION,
        event_type=event_type,
        outcome=AuditOutcome.SUCCEEDED,
        actor=actor,
        occurred_at=occurred_at,
        target_type="agent_version",
        target_id=target_id,
        metadata=metadata,
    )


def _nonblank(value: str, field: str, *, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} is empty or outside its length limit")
    return normalized


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production publication clock must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "ProductionAgentCandidateValidation",
    "ProductionAgentCandidateValidator",
    "ProductionAgentPublicationService",
]
