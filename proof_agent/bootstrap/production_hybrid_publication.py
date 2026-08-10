"""Application-facing publication composition for production Hybrid Knowledge."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel

from proof_agent.bootstrap.production_hybrid_runtime import (
    ProductionHybridDeploymentSettings,
)
from proof_agent.capabilities.knowledge.hybrid.manifest import ManifestRuleUnitMembership
from proof_agent.capabilities.knowledge.hybrid.metadata_review import (
    InsuranceMetadataReviewSet,
    MetadataReviewConflictError,
    approved_insurance_metadata_for_anchor,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import rrf_pipeline_name
from proof_agent.capabilities.knowledge.hybrid.ports import KnowledgeArtifactStore
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationRequest,
    HybridPublicationValidationAuthority,
    PublicationCommit,
    ProjectionSeed,
    PublicationConflict,
    hybrid_candidate_material_fingerprint,
)
from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    materialize_rule_unit_revision,
    stable_digest,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
)
from proof_agent.contracts.agent_configuration import (
    KnowledgeDocument,
    KnowledgeSourceLifecycleState,
)
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.knowledge_index import (
    HybridKnowledgePublicationRecord,
    KnowledgeRetrievalProfileRevision,
    RuleUnitManifestEntry,
)


class HybridPublicationCandidateAssembler(Protocol):
    def build(
        self,
        *,
        source_id: str,
        validation_id: str,
        actor: str,
        smoke_query: str | None = None,
    ) -> HybridPublicationRequest: ...


class HybridPublicationFacadeRepository(Protocol):
    def stage_source_candidate(self, **kwargs: Any) -> None: ...

    def publish_retrieval_profile(self, **kwargs: Any) -> None: ...

    def register_validation(self, validation: HybridPublicationValidationAuthority) -> None: ...

    def list_publication_validations(
        self, source_id: str
    ) -> Sequence[HybridPublicationValidationAuthority]: ...

    def list_publications(self, source_id: str) -> Sequence[HybridKnowledgePublicationRecord]: ...


class HybridPublicationApplicationService(Protocol):
    def prepare(self, request: HybridPublicationRequest) -> PublicationCommit: ...

    def publish(self, request: HybridPublicationRequest) -> HybridKnowledgePublicationRecord: ...


class ProductionHybridKnowledgePublicationFacade:
    """Validate candidate identity, then delegate one fenced publication transaction."""

    def __init__(
        self,
        *,
        assembler: HybridPublicationCandidateAssembler,
        repository: HybridPublicationFacadeRepository,
        publication_service: HybridPublicationApplicationService,
        retrieval_profile: KnowledgeRetrievalProfileRevision,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        validation_id_factory: Callable[[], str] = lambda: f"hybrid-validation-{uuid4().hex}",
    ) -> None:
        self._assembler = assembler
        self._repository = repository
        self._publication_service = publication_service
        self._retrieval_profile = retrieval_profile
        self._clock = clock
        self._validation_id_factory = validation_id_factory

    def validate(self, *, source_id: str, smoke_query: str, actor: str) -> BaseModel:
        _require_nonblank(smoke_query, "smoke_query")
        validation_id = _require_nonblank(self._validation_id_factory(), "validation_id")
        request = self._assembler.build(
            source_id=_require_nonblank(source_id, "source_id"),
            validation_id=validation_id,
            actor=_require_nonblank(actor, "actor"),
            smoke_query=_require_nonblank(smoke_query, "smoke_query"),
        )
        self._repository.stage_source_candidate(
            source_id=request.source_id,
            source_draft_version_id=request.source_draft_version_id,
            candidate_digest=request.candidate_digest,
            generation=request.generation,
        )
        self._repository.publish_retrieval_profile(
            source_id=request.source_id,
            profile=self._retrieval_profile,
            make_default=True,
        )
        validation = HybridPublicationValidationAuthority(
            validation_id=validation_id,
            source_id=request.source_id,
            source_draft_version_id=request.source_draft_version_id,
            candidate_digest=request.candidate_digest,
            generation_id=request.generation.generation_id,
            validated_at=self._clock(),
            validated_by=actor,
            smoke_query=smoke_query,
        )
        self._repository.register_validation(validation)
        return validation

    def prepare(
        self,
        *,
        source_id: str,
        validation_id: str,
        smoke_query: str,
        actor: str,
    ) -> PublicationCommit:
        """Assemble, validate, and stage one publication without committing authority."""

        _require_nonblank(smoke_query, "smoke_query")
        request = self._assembler.build(
            source_id=_require_nonblank(source_id, "source_id"),
            validation_id=_require_nonblank(validation_id, "validation_id"),
            actor=_require_nonblank(actor, "actor"),
            smoke_query=smoke_query,
        )
        self._repository.stage_source_candidate(
            source_id=request.source_id,
            source_draft_version_id=request.source_draft_version_id,
            candidate_digest=request.candidate_digest,
            generation=request.generation,
        )
        self._repository.publish_retrieval_profile(
            source_id=request.source_id,
            profile=self._retrieval_profile,
            make_default=True,
        )
        self._repository.register_validation(
            HybridPublicationValidationAuthority(
                validation_id=validation_id,
                source_id=request.source_id,
                source_draft_version_id=request.source_draft_version_id,
                candidate_digest=request.candidate_digest,
                generation_id=request.generation.generation_id,
                validated_at=self._clock(),
                validated_by=actor,
                smoke_query=smoke_query,
            )
        )
        return self._publication_service.prepare(request)

    def publish(
        self,
        *,
        source_id: str,
        validation_id: str,
        change_note: str,
        actor: str,
    ) -> BaseModel:
        _require_nonblank(change_note, "change_note")
        validation = next(
            (
                item
                for item in self._repository.list_publication_validations(source_id)
                if item.validation_id == validation_id
            ),
            None,
        )
        if validation is None:
            raise KeyError(validation_id)
        request = self._assembler.build(
            source_id=source_id,
            validation_id=validation_id,
            actor=_require_nonblank(actor, "actor"),
            smoke_query=validation.smoke_query,
        )
        if (
            request.source_id != validation.source_id
            or request.source_draft_version_id != validation.source_draft_version_id
            or request.candidate_digest != validation.candidate_digest
            or request.generation.generation_id != validation.generation_id
        ):
            raise PublicationConflict("STALE_VALIDATION")
        return self._publication_service.publish(request)

    def list_validations(self, source_id: str) -> Sequence[BaseModel]:
        return tuple(self._repository.list_publication_validations(source_id))

    def list_publications(self, source_id: str) -> Sequence[BaseModel]:
        return tuple(self._repository.list_publications(source_id))

    def create_rollback_draft(
        self,
        *,
        source_id: str,
        historical_publication_id: str,
        reason: str,
        actor: str,
    ) -> BaseModel:
        del source_id, historical_publication_id, reason, actor
        raise PublicationConflict("HYBRID_ROLLBACK_DRAFT_NOT_IMPLEMENTED")


class HybridPublicationConfigurationStore(Protocol):
    def get_knowledge_source(self, source_id: str) -> Any: ...

    def list_knowledge_documents(self, source_id: str) -> Sequence[Any]: ...

    def get_completed_hybrid_artifact_build_result(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> HybridArtifactBuildResult: ...


class PostgresHybridPublicationConfigurationStore:
    """Read-only publication projection over PG Source and completed ingestion authority."""

    def __init__(self, *, knowledge: Any, ingestion: Any) -> None:
        self._knowledge = knowledge
        self._ingestion = ingestion

    def get_knowledge_source(self, source_id: str) -> Any:
        return self._knowledge.get_knowledge_source(source_id)

    def list_knowledge_documents(self, source_id: str) -> Sequence[KnowledgeDocument]:
        return tuple(
            _knowledge_document_from_ingestion_record(record)
            for record in self._ingestion.list_candidate_records_for_source(source_id)
        )

    def get_completed_hybrid_artifact_build_result(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> HybridArtifactBuildResult:
        matches = tuple(
            record
            for record in self._ingestion.list_records_for_source(source_id)
            if record.build_request.document_id == document_id
            and record.build_request.revision_id == revision_id
        )
        if len(matches) != 1 or matches[0].job.state != "COMPLETED":
            raise KeyError((source_id, document_id, revision_id))
        result = self._ingestion.get_result(matches[0].build_request.job_id)
        if result is None:
            raise KeyError((source_id, document_id, revision_id))
        return HybridArtifactBuildResult.model_validate(result)


class HybridMetadataReviewReader(Protocol):
    def get_current_review_set(
        self,
        *,
        source_id: str,
        document_id: str,
        revision_id: str,
    ) -> InsuranceMetadataReviewSet | None: ...


class HybridPublicationAssemblyRepository(Protocol):
    def load_active_publication(self, source_id: str) -> HybridKnowledgePublicationRecord | None: ...

    def load_generation_rebuild(self, source_id: str, generation_id: str) -> Any: ...


class HybridPublicationIndex(Protocol):
    def ensure_index(self, generation: Any, **kwargs: Any) -> Any: ...


class ProductionHybridPublicationCandidateAssembler:
    """Turn reviewed local ingestion state into one exact production publication request."""

    def __init__(
        self,
        *,
        configuration_store: HybridPublicationConfigurationStore,
        review_repository: HybridMetadataReviewReader,
        repository: HybridPublicationAssemblyRepository,
        artifact_store: KnowledgeArtifactStore,
        search_index: HybridPublicationIndex,
        settings: ProductionHybridDeploymentSettings,
    ) -> None:
        self._configuration_store = configuration_store
        self._review_repository = review_repository
        self._repository = repository
        self._artifact_store = artifact_store
        self._search_index = search_index
        self._settings = settings

    def build(
        self,
        *,
        source_id: str,
        validation_id: str,
        actor: str,
        smoke_query: str | None = None,
    ) -> HybridPublicationRequest:
        source = self._configuration_store.get_knowledge_source(source_id)
        if (
            source is None
            or source.provider != "hybrid_index"
            or source.lifecycle_state != KnowledgeSourceLifecycleState.ACTIVE
            or source.source_draft_version_id is None
        ):
            raise PublicationConflict("SOURCE_NOT_PUBLISHABLE")
        documents = tuple(self._configuration_store.list_knowledge_documents(source_id))
        blocked = tuple(item for item in documents if item.state not in {"ready", "archived"})
        ready = tuple(item for item in documents if item.state == "ready")
        if blocked or not ready:
            raise PublicationConflict("SOURCE_DOCUMENTS_NOT_READY")

        generation = self._settings.generation_for(source_id)
        active = self._repository.load_active_publication(source_id)
        next_sequence = 1 if active is None else active.source_publication_seq + 1
        retained = self._retained_active_projection_by_rule(active, generation.generation_id)
        materialized: list[tuple[Any, Any]] = []
        build_material: list[dict[str, Any]] = []
        for document in ready:
            result = self._configuration_store.get_completed_hybrid_artifact_build_result(
                source_id=source_id,
                document_id=document.document_id,
                revision_id=document.revision_id,
            )
            canonical = StructuredKnowledgeDocumentArtifact.model_validate_json(
                self._artifact_store.get_exact(result.canonical_ref)
            )
            metadata = HybridInsuranceMetadataArtifact.model_validate_json(
                self._artifact_store.get_exact(result.insurance_metadata_ref)
            )
            _validate_build_projection(result, canonical, metadata)
            review_set = self._review_repository.get_current_review_set(
                source_id=source_id,
                document_id=document.document_id,
                revision_id=document.revision_id,
            )
            if (
                review_set is None
                or review_set.source_id != result.source_id
                or review_set.document_id != result.document_id
                or review_set.revision_id != result.revision_id
                or review_set.structured_build_id != result.build_id
            ):
                raise PublicationConflict("METADATA_REVIEW_REQUIRED")
            drafts = project_rule_units(
                canonical,
                document_defaults=metadata.document_defaults,
                source_id=source_id,
            )
            for draft in drafts:
                try:
                    approved = approved_insurance_metadata_for_anchor(
                        review_set,
                        draft.canonical_anchor,
                    )
                except MetadataReviewConflictError as exc:
                    raise PublicationConflict("METADATA_REVIEW_REQUIRED") from exc
                rule = materialize_rule_unit_revision(
                    draft,
                    approved_metadata=approved,
                    approved_visibility=self._settings.approved_visibility,
                )
                materialized.append((rule, approved))
            build_material.append(
                {
                    "document_id": result.document_id,
                    "revision_id": result.revision_id,
                    "build_id": result.build_id,
                    "canonical_ref": result.canonical_ref.model_dump(mode="json"),
                    "metadata_ref": result.insurance_metadata_ref.model_dump(mode="json"),
                }
            )
        rule_ids = [rule.rule_unit_revision_id for rule, _ in materialized]
        if not materialized or len(rule_ids) != len(set(rule_ids)):
            raise PublicationConflict("RULE_UNIT_AUTHORITY_AMBIGUOUS")

        memberships: list[ManifestRuleUnitMembership] = []
        seeds: list[ProjectionSeed] = []
        for rule, approved in sorted(
            materialized, key=lambda item: item[0].rule_unit_revision_id
        ):
            prior = retained.get(rule.rule_unit_revision_id)
            publication_seq_from = (
                prior.manifest_entry.publication_seq_from if prior is not None else next_sequence
            )
            projection_id = (
                prior.projection_id
                if prior is not None
                else "projection-"
                + stable_digest(
                    {
                        "schema_version": "hybrid-projection-id.v1",
                        "generation_id": generation.generation_id,
                        "rule_unit_revision_id": rule.rule_unit_revision_id,
                    }
                )[:32]
            )
            entry = RuleUnitManifestEntry(
                rule_unit_revision_id=rule.rule_unit_revision_id,
                document_id=rule.document_id,
                revision_id=rule.revision_id,
                structured_build_id=rule.structured_build_id,
                metadata_revision_id=rule.metadata_revision_id,
                visibility_revision_id=rule.visibility_scope.revision_id,
                content_sha256=rule.content_sha256,
                authority_sha256=rule.authority_sha256,
                citation_uri=rule.citation_uri,
                publication_seq_from=publication_seq_from,
            )
            memberships.append(
                ManifestRuleUnitMembership(
                    rule_unit=rule,
                    publication_seq_from=publication_seq_from,
                )
            )
            seeds.append(
                ProjectionSeed(
                    projection_id=projection_id,
                    rule_unit=rule,
                    manifest_entry=entry,
                    approved_metadata=approved,
                    projection_revision=generation.search_projection_version,
                )
            )

        snapshot_digest = stable_digest(
            {
                "schema_version": "hybrid-source-snapshot.v1",
                "source_id": source_id,
                "source_draft_version_id": source.source_draft_version_id,
                "builds": sorted(build_material, key=lambda item: item["document_id"]),
                "rule_unit_revision_ids": sorted(rule_ids),
                "visibility": self._settings.approved_visibility.model_dump(mode="json"),
            }
        )
        identity = self._search_index.ensure_index(
            generation,
            rrf_pipeline=rrf_pipeline_name(rank_constant=self._settings.rrf_rank_constant),
            rrf_rank_constant=self._settings.rrf_rank_constant,
        )
        request = HybridPublicationRequest(
            source_id=source_id,
            source_draft_version_id=source.source_draft_version_id,
            candidate_digest="0" * 64,
            source_snapshot_id=f"hybrid-snapshot-{snapshot_digest[:32]}",
            generation=generation,
            validation_id=validation_id,
            published_by=actor,
            memberships=tuple(memberships),
            projection_seeds=tuple(seeds),
            identity=identity,
            embedding_instruction=self._settings.embedding_instruction,
            embedding_timeout_seconds=self._settings.embedding_timeout_seconds,
            smoke_query=smoke_query,
        )
        return request.model_copy(
            update={"candidate_digest": hybrid_candidate_material_fingerprint(request)}
        )

    def _retained_active_projection_by_rule(
        self,
        active: HybridKnowledgePublicationRecord | None,
        generation_id: str,
    ) -> dict[str, Any]:
        if active is None or active.generation_id != generation_id:
            return {}
        rebuild = self._repository.load_generation_rebuild(active.source_id, generation_id)
        if rebuild.current_attestation != active.attestation:
            raise PublicationConflict("PROJECTION_AUTHORITY_STALE")
        return {
            item.rule_unit.rule_unit_revision_id: item
            for item in rebuild.projection_authority
            if item.manifest_entry.publication_seq_from <= active.source_publication_seq
            and (
                item.manifest_entry.publication_seq_to is None
                or item.manifest_entry.publication_seq_to >= active.source_publication_seq
            )
        }


def _validate_build_projection(
    result: HybridArtifactBuildResult,
    canonical: StructuredKnowledgeDocumentArtifact,
    metadata: HybridInsuranceMetadataArtifact,
) -> None:
    if (
        canonical.document_id != result.document_id
        or canonical.revision_id != result.revision_id
        or canonical.build_identity != result.build_identity
        or metadata.source_id != result.source_id
        or metadata.document_id != result.document_id
        or metadata.revision_id != result.revision_id
        or metadata.structured_build_id != result.build_id
        or metadata.original_sha256 != result.original_ref.sha256
    ):
        raise PublicationConflict("BUILD_AUTHORITY_MISMATCH")


def _require_nonblank(value: str, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value.strip()


def _knowledge_document_from_ingestion_record(record: Any) -> KnowledgeDocument:
    request = record.build_request
    state = {
        "READY": "queued",
        "CLAIMED": "processing",
        "RETRY_SCHEDULED": "retry_scheduled",
        "REVIEW_REQUIRED": "review_required",
        "COMPLETED": "ready",
        "FAILED": "failed",
    }[record.job.state]
    return KnowledgeDocument(
        document_id=request.document_id,
        source_id=request.source_id,
        revision_id=request.revision_id,
        filename=record.filename,
        content_type="application/pdf",
        content_hash=request.original_ref.sha256,
        size_bytes=request.original_ref.size_bytes,
        state=state,
        storage_path=f"managed://hybrid/{request.document_id}/revisions/{request.revision_id}",
        ingestion_job_id=request.job_id,
        artifact_path=(
            f"managed://hybrid/{request.document_id}/artifacts"
            if record.job.state == "COMPLETED"
            else None
        ),
        error_code=record.job.failure_code,
        error_message=record.job.safe_reason,
        created_at=record.job.created_at.isoformat(),
        updated_at=record.job.updated_at.isoformat(),
    )


__all__ = [
    "ProductionHybridKnowledgePublicationFacade",
    "ProductionHybridPublicationCandidateAssembler",
    "PostgresHybridPublicationConfigurationStore",
]
