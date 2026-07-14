from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    ManifestRuleUnitMembership,
    ProjectionValidationEvidence,
    build_rule_unit_manifest,
    decode_manifest_shard_artifact,
)
from proof_agent.capabilities.knowledge.hybrid.ports import (
    ProjectionAuthorityDocument,
    ProjectionMembershipRestorationResult,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.publication import PublicationConflict
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    GenerationRebuildAuthority,
    GenerationRebuildOperation,
    GenerationRebuildValidation,
    HybridRecoveryService,
    OrphanProjection,
    OrphanReconciliationReport,
    RebuildProjectionOrphan,
    RebuildSwapResolution,
    OpenSearchRecoveryIndex,
    RebuildProjectionAuthority,
    RetainedManifestAuthority,
    recovery_service_from_environment,
)
from proof_agent.capabilities.knowledge.hybrid import recovery as recovery_module
from proof_agent.capabilities.knowledge.hybrid.opensearch import project_rule_unit_document
from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
    S3ArtifactError,
    S3ExactArtifactStore,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import rebuild_projection_locator
from proof_agent.configuration.hybrid_knowledge_repository import FileSystemKnowledgeArtifactStore
from proof_agent.configuration import postgres_hybrid_knowledge_repository as postgres_repository
from proof_agent.contracts.knowledge_index import KnowledgeProjectionAttestation
from test_hybrid_publication import _Embedding, _Index, _request, _service


class _RecoveryRepository:
    def __init__(self, authority: GenerationRebuildAuthority) -> None:
        self.authority = authority
        self.orphans: list[OrphanProjection | RebuildProjectionOrphan] = []
        self.referenced: set[str] = set()
        self.deleted: list[str] = []
        self.resolved: list[str] = []
        self.retries: list[str] = []
        self.swapped: tuple[SearchIndexIdentity, KnowledgeProjectionAttestation] | None = None
        self.staged: tuple[SearchIndexIdentity, KnowledgeProjectionAttestation] | None = None
        self.operation_id = "rebuild-operation-1"
        self.failed_operations: list[tuple[str, str, SearchIndexIdentity | None]] = []
        self.recovery_orphans: dict[str, SearchIndexIdentity] = {}

    def list_orphan_projections(
        self, source_id: str
    ) -> tuple[OrphanProjection | RebuildProjectionOrphan, ...]:
        return tuple(item for item in self.orphans if item.source_id == source_id)

    def projection_is_referenced(self, orphan: OrphanProjection) -> bool:
        return orphan.attempt_id in self.referenced

    def record_orphan_purged(self, attempt_id: str) -> None:
        self.deleted.append(attempt_id)
        self.orphans = [item for item in self.orphans if item.attempt_id != attempt_id]

    def record_orphan_resolved(self, attempt_id: str) -> None:
        self.resolved.append(attempt_id)
        self.orphans = [item for item in self.orphans if item.attempt_id != attempt_id]

    def record_orphan_retry(self, attempt_id: str, failure_code: str) -> None:
        assert failure_code == "CLEANUP_RETRY"
        self.retries.append(attempt_id)

    def load_generation_rebuild(
        self, source_id: str, generation_id: str
    ) -> GenerationRebuildAuthority:
        assert (source_id, generation_id) == (
            self.authority.source_id,
            self.authority.generation_id,
        )
        return self.authority

    def begin_generation_rebuild(
        self, authority: GenerationRebuildAuthority
    ) -> GenerationRebuildOperation:
        assert authority == self.authority
        return GenerationRebuildOperation(
            operation_id=self.operation_id,
            source_id=authority.source_id,
            generation_id=authority.generation_id,
            projection_locator=rebuild_projection_locator(
                source_id=authority.source_id,
                generation_id=authority.generation_id,
                operation_id=self.operation_id,
            ),
        )

    def resolve_rebuild_swap(self, **_: Any) -> RebuildSwapResolution:
        return RebuildSwapResolution(state="PARENT_CURRENT")

    def rebuild_orphan_is_active(
        self,
        orphan: RebuildProjectionOrphan,
        identity: SearchIndexIdentity,
    ) -> bool:
        del orphan
        return identity == self.authority.current_identity

    def record_rebuild_projection_identity(
        self,
        orphan: RebuildProjectionOrphan,
        identity: SearchIndexIdentity,
    ) -> None:
        replacement = orphan.model_copy(update={"index_uuid": identity.index_uuid})
        self.orphans = [
            replacement if item.attempt_id == orphan.attempt_id else item for item in self.orphans
        ]

    def fail_recovery_operation(
        self,
        operation_id: str,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None = None,
        *,
        requires_reconciliation: bool = False,
    ) -> None:
        failure = (operation_id, failure_code, projection_identity)
        if failure not in self.failed_operations:
            self.failed_operations.append(failure)
        if projection_identity is not None:
            existing = self.recovery_orphans.setdefault(operation_id, projection_identity)
            assert existing == projection_identity
        if requires_reconciliation and projection_identity is None:
            operation = self.begin_generation_rebuild(self.authority)
            self.orphans.append(
                RebuildProjectionOrphan(
                    attempt_id=operation_id,
                    source_id=operation.source_id,
                    generation=self.authority.current_identity.generation,
                    projection_locator=operation.projection_locator,
                )
            )

    def swap_generation_projection(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> None:
        self.swapped = (rebuilt_identity, attestation)

    def stage_generation_rebuild_validation(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> GenerationRebuildValidation:
        assert authority == self.authority
        self.staged = (rebuilt_identity, attestation)
        return GenerationRebuildValidation(
            operation_id=attestation.publication_attempt_id,
            source_id=authority.source_id,
            generation_id=authority.generation_id,
            projection_locator=rebuild_projection_locator(
                source_id=authority.source_id,
                generation_id=authority.generation_id,
                operation_id=attestation.publication_attempt_id,
            ),
            index_uuid=rebuilt_identity.index_uuid,
            parent_index_uuid=authority.current_identity.index_uuid,
            parent_projection_locator=authority.current_identity.projection_locator,
            parent_attestation_sha256=authority.current_attestation.attestation_sha256,
            candidate_digest=authority.candidate_digest,
            manifest_root_sha256=authority.manifest_root.root_sha256,
            mapping_sha256=attestation.mapping_sha256,
            covered_publication_sequences=attestation.covered_publication_sequences,
            projection_sha256=attestation.projection_sha256,
            validated_document_count=attestation.validated_document_count,
            validated_rule_unit_count=attestation.validated_rule_unit_count,
            attestation_sha256=attestation.attestation_sha256,
        )


class _RecoveryIndex:
    def __init__(self) -> None:
        self.fail_delete: set[str] = set()
        self.deleted: list[str] = []
        self.repaired: list[str] = []
        self.rebuilt_documents: tuple[Any, ...] = ()
        self.discarded_rebuilds: list[SearchIndexIdentity] = []
        self.retain_rebuild = False
        self.fail_discard = False

    def delete_attempt_projection(self, orphan: OrphanProjection) -> None:
        if orphan.attempt_id in self.fail_delete:
            raise RuntimeError("interrupted cleanup")
        self.deleted.append(orphan.attempt_id)

    def rebuild_generation(
        self,
        authority: GenerationRebuildAuthority,
        *,
        operation: GenerationRebuildOperation,
        root: Any,
        shard_contents: tuple[bytes, ...],
        documents: tuple[Any, ...],
    ) -> tuple[SearchIndexIdentity, ProjectionValidationEvidence]:
        assert shard_contents
        assert documents
        self.rebuilt_documents = documents
        identity = SearchIndexIdentity(
            generation=authority.current_identity.generation,
            index_uuid="fresh-index-uuid",
            projection_locator=operation.projection_locator,
        )
        return identity, ProjectionValidationEvidence(
            publication_attempt_id=operation.operation_id,
            candidate_digest=authority.candidate_digest,
            identity=identity,
            refresh_checkpoint="rebuild-refresh-1",
            manifest_root_sha256=root.root_sha256,
            covered_publication_sequences=(
                authority.current_attestation.covered_publication_sequences
            ),
            projection_sha256="f" * 64,
            validated_document_count=len({item.rule_unit.document_id for item in documents}),
            validated_rule_unit_count=len(documents),
        )

    def repair_attempt_projection(
        self,
        authority: GenerationRebuildAuthority,
        orphan: OrphanProjection,
        *,
        operation_id: str,
        root: Any,
        documents: tuple[Any, ...],
    ) -> ProjectionValidationEvidence:
        assert documents
        self.repaired.append(orphan.attempt_id)
        return ProjectionValidationEvidence(
            publication_attempt_id=operation_id,
            candidate_digest=authority.candidate_digest,
            identity=authority.current_identity,
            refresh_checkpoint="repair-refresh-1",
            manifest_root_sha256=root.root_sha256,
            covered_publication_sequences=(1,),
            projection_sha256="6" * 64,
            validated_document_count=root.document_count,
            validated_rule_unit_count=root.rule_unit_count,
        )

    def resolve_rebuild_projection(
        self, orphan: RebuildProjectionOrphan
    ) -> SearchIndexIdentity | None:
        return SearchIndexIdentity(
            generation=orphan.generation,
            index_uuid=orphan.index_uuid or "resolved-index-uuid",
            projection_locator=orphan.projection_locator,
        )

    def purge_rebuild_projection(
        self,
        orphan: RebuildProjectionOrphan,
        identity: SearchIndexIdentity,
    ) -> None:
        if self.fail_discard:
            raise RuntimeError("fresh cleanup failed")
        if self.retain_rebuild:
            raise RuntimeError("fresh cleanup retained")
        if identity not in self.discarded_rebuilds:
            self.discarded_rebuilds.append(identity)


def _fixture(tmp_path: Any):
    publication_service, publication_repo, _, _ = _service(tmp_path)
    publication = publication_service.publish(_request())
    manifest = publication_repo.manifests[publication.manifest_ref.sha256]
    authority = GenerationRebuildAuthority(
        source_id=publication.source_id,
        generation_id=publication.generation_id,
        candidate_digest=publication.candidate_digest,
        manifest_root=manifest.root,
        root_ref=manifest.root_ref,
        shard_refs=tuple(item.artifact_ref for item in manifest.shards),
        current_identity=SearchIndexIdentity(
            generation=_request().generation,
            index_uuid=publication.attestation.index_uuid,
        ),
        current_attestation=publication.attestation,
        projection_authority=tuple(
            RebuildProjectionAuthority(
                projection_id=seed.projection_id,
                projection_revision=seed.projection_revision,
                rule_unit=seed.rule_unit,
                approved_metadata=seed.approved_metadata,
                last_publication_attempt_id=(publication.attestation.publication_attempt_id),
            )
            for seed in _request().projection_seeds
        ),
        retained_manifests=(
            RetainedManifestAuthority(
                root=manifest.root,
                root_ref=manifest.root_ref,
                shard_refs=tuple(item.artifact_ref for item in manifest.shards),
            ),
        ),
    )
    repository = _RecoveryRepository(authority)
    index = _RecoveryIndex()
    service = HybridRecoveryService(
        repository=repository,
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path),
        index=index,
    )
    return service, repository, index


def test_orphan_reconciliation_dry_run_then_repairs_shared_active_projection(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    identity = repository.authority.current_identity
    repository.orphans = [
        OrphanProjection(
            attempt_id="failed-1",
            source_id="source-1",
            identity=identity,
            reserved_publication_seq=2,
        ),
        OrphanProjection(
            attempt_id="active-1",
            source_id="source-1",
            identity=identity,
            reserved_publication_seq=2,
        ),
    ]
    repository.referenced.add("active-1")
    report = service.reconcile_orphans(source_id="source-1")
    assert report.dry_run is True
    assert report.refused_attempt_ids == ()
    assert not index.deleted
    applied = service.reconcile_orphans(source_id="source-1", apply=True)
    assert applied.purged_attempt_ids == ("failed-1", "active-1")
    assert applied.cleanup_scope == "OPERATION_PAYLOAD"
    assert applied.physical_index_retained is True
    assert index.deleted == ["failed-1"]
    assert index.repaired == ["active-1"]
    assert repository.swapped is not None


def test_interrupted_cleanup_is_recorded_for_retry(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    orphan = OrphanProjection(
        attempt_id="failed-1",
        source_id="source-1",
        identity=repository.authority.current_identity,
        reserved_publication_seq=2,
    )
    repository.orphans = [orphan]
    index.fail_delete.add(orphan.attempt_id)
    report = service.reconcile_orphans(source_id="source-1", apply=True)
    assert report.retry_attempt_ids == ("failed-1",)
    assert repository.retries == ["failed-1"]


def test_retry_orphan_cleanup_converges_to_purged_idempotently(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    orphan = OrphanProjection(
        attempt_id="retry-1",
        source_id="source-1",
        identity=repository.authority.current_identity,
        reserved_publication_seq=2,
        state="RETRY",
    )
    repository.orphans = [orphan]

    first = service.reconcile_orphans(source_id="source-1", apply=True)
    second = service.reconcile_orphans(source_id="source-1", apply=True)

    assert first.candidates == ("retry-1",)
    assert first.purged_attempt_ids == ("retry-1",)
    assert second.candidates == ()
    assert second.purged_attempt_ids == ()
    assert index.deleted == ["retry-1"]
    assert repository.deleted == ["retry-1"]


@pytest.mark.parametrize(
    ("operation_kind", "reserved_sequence"),
    (("PUBLICATION", None), ("OTHER", 2)),
)
def test_postgres_orphan_listing_requires_publication_sequence_authority(
    operation_kind: str,
    reserved_sequence: int | None,
) -> None:
    generation = _request().generation

    class Result:
        def fetchall(self) -> list[tuple[Any, ...]]:
            return [
                (
                    "orphan-attempt",
                    generation.source_id,
                    "PENDING",
                    "index-uuid",
                    generation.model_dump(mode="json"),
                    None,
                    operation_kind,
                    reserved_sequence,
                )
            ]

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def transaction(self) -> Connection:
            return self

        def execute(self, query: str, params: tuple[Any, ...]) -> Result:
            assert "attempt.reserved_sequence" in query
            assert params == (generation.source_id,)
            return Result()

    class Pool:
        def connection(self) -> Connection:
            return Connection()

    repository = postgres_repository.PostgresHybridKnowledgeRepository(pool=Pool())
    with pytest.raises(PublicationConflict, match="PROJECTION_AUTHORITY_MISMATCH"):
        repository.list_orphan_projections(generation.source_id)


def test_postgres_orphan_listing_binds_reserved_publication_sequence() -> None:
    generation = _request().generation

    class Result:
        def fetchall(self) -> list[tuple[Any, ...]]:
            return [
                (
                    "orphan-attempt",
                    generation.source_id,
                    "RETRY",
                    "index-uuid",
                    generation.model_dump(mode="json"),
                    None,
                    "PUBLICATION",
                    7,
                )
            ]

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def transaction(self) -> Connection:
            return self

        def execute(self, _query: str, _params: tuple[Any, ...]) -> Result:
            return Result()

    class Pool:
        def connection(self) -> Connection:
            return Connection()

    repository = postgres_repository.PostgresHybridKnowledgeRepository(pool=Pool())
    orphan = repository.list_orphan_projections(generation.source_id)[0]
    assert isinstance(orphan, OrphanProjection)
    assert orphan.reserved_publication_seq == 7


def test_generation_rebuild_uses_exact_artifacts_fresh_uuid_and_same_coverage(
    tmp_path: Any,
) -> None:
    service, repository, _ = _fixture(tmp_path)
    _, _, retained_documents = service._verified_inputs(repository.authority)
    assert tuple(item.last_publication_attempt_id for item in retained_documents) == (
        repository.authority.current_attestation.publication_attempt_id,
    )
    rebuilt = service.rebuild_generation(source_id="source-1", generation_id="generation-1")
    assert rebuilt.index_uuid == "fresh-index-uuid"
    assert rebuilt.manifest_root_sha256 == repository.authority.manifest_root.root_sha256
    assert rebuilt.covered_publication_sequences == (1,)
    assert rebuilt.parent_attestation_sha256 == (
        repository.authority.current_attestation.attestation_sha256
    )
    assert repository.swapped is not None


def test_post_validation_failure_discards_only_fresh_rebuild(tmp_path: Any) -> None:
    class InvalidEvidenceIndex(_RecoveryIndex):
        def rebuild_generation(self, *args: Any, **kwargs: Any) -> Any:
            identity, evidence = super().rebuild_generation(*args, **kwargs)
            return identity, evidence.model_copy(update={"candidate_digest": "0" * 64})

    service, repository, _ = _fixture(tmp_path)
    index = InvalidEvidenceIndex()
    service.index = index
    old_identity = repository.authority.current_identity

    with pytest.raises(PublicationConflict, match="ATTESTATION_MISMATCH"):
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")

    assert repository.swapped is None
    assert len(index.discarded_rebuilds) == 1
    assert index.discarded_rebuilds[0].index_uuid == "fresh-index-uuid"
    assert old_identity not in index.discarded_rebuilds
    assert repository.failed_operations == [(repository.operation_id, "ATTESTATION_MISMATCH", None)]


def test_rebuild_adapter_returning_active_identity_is_never_deleted(tmp_path: Any) -> None:
    class ActiveIdentityIndex(_RecoveryIndex):
        def rebuild_generation(self, authority: Any, *args: Any, **kwargs: Any) -> Any:
            _, evidence = super().rebuild_generation(authority, *args, **kwargs)
            identity = authority.current_identity
            return identity, evidence.model_copy(update={"identity": identity})

    service, repository, _ = _fixture(tmp_path)
    index = ActiveIdentityIndex()
    service.index = index

    with pytest.raises(PublicationConflict, match="REBUILD_INDEX_NOT_FRESH"):
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")

    assert index.discarded_rebuilds == []
    assert repository.swapped is None
    assert repository.failed_operations == [
        (repository.operation_id, "REBUILD_INDEX_NOT_FRESH", None)
    ]


def test_rebuild_cas_failure_discards_fresh_and_preserves_primary_failure(
    tmp_path: Any,
) -> None:
    class CasFailingRepository(_RecoveryRepository):
        def swap_generation_projection(self, **_: Any) -> None:
            raise PublicationConflict("FENCE_LOST")

    base_service, base_repository, _ = _fixture(tmp_path)
    repository = CasFailingRepository(base_repository.authority)
    index = _RecoveryIndex()
    service = HybridRecoveryService(
        repository=repository,
        artifact_store=base_service.artifact_store,
        index=index,
    )

    with pytest.raises(PublicationConflict, match="FENCE_LOST"):
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")

    assert repository.swapped is None
    assert len(index.discarded_rebuilds) == 1
    assert repository.authority.current_identity not in index.discarded_rebuilds
    assert repository.failed_operations == [(repository.operation_id, "FENCE_LOST", None)]


def test_ambiguous_committed_swap_converges_to_success_without_cleanup(tmp_path: Any) -> None:
    class ResponseLostRepository(_RecoveryRepository):
        def swap_generation_projection(self, **kwargs: Any) -> None:
            super().swap_generation_projection(**kwargs)
            raise RuntimeError("commit response lost")

        def resolve_rebuild_swap(self, **_: Any) -> RebuildSwapResolution:
            return RebuildSwapResolution(state="COMMITTED")

    base_service, base_repository, _ = _fixture(tmp_path)
    repository = ResponseLostRepository(base_repository.authority)
    index = _RecoveryIndex()
    service = HybridRecoveryService(
        repository=repository,
        artifact_store=base_service.artifact_store,
        index=index,
    )

    attestation = service.rebuild_generation(source_id="source-1", generation_id="generation-1")

    assert repository.swapped is not None
    assert repository.swapped[0].index_uuid == "fresh-index-uuid"
    assert attestation == repository.swapped[1]
    assert index.discarded_rebuilds == []
    assert repository.failed_operations == []


@pytest.mark.parametrize(
    "forgery",
    (
        "operation_kind",
        "operation_state",
        "operation_locator",
        "current_uuid",
        "current_locator",
        "current_attestation",
        "stored_parent",
        "stored_generation",
        "candidate",
        "database_root",
        "source_id",
        "generation_id",
        "operation_id",
        "fresh_uuid",
        "fresh_locator",
        "parent",
        "root",
        "mapping",
        "coverage",
        "document_count",
        "rule_count",
        "digest",
    ),
)
def test_postgres_rebuild_swap_rejects_each_forged_authority_field(
    tmp_path: Any,
    forgery: str,
) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    root, shard_contents, documents = service._verified_inputs(authority)
    operation = repository.begin_generation_rebuild(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    attestation = recovery_module._rebuild_attestation(authority, identity, evidence)
    row: list[Any] = [
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "BUILDING",
        operation.projection_locator,
        authority.current_identity.index_uuid,
        authority.current_identity.projection_locator,
        authority.current_attestation.attestation_sha256,
        authority.current_attestation.model_dump(mode="json"),
        authority.current_identity.generation.model_dump(mode="json"),
        authority.candidate_digest,
        authority.manifest_root.root_sha256,
    ]
    if forgery == "operation_kind":
        row[2] = "PUBLICATION"
    elif forgery == "operation_state":
        row[3] = "COMMITTED"
    elif forgery == "operation_locator":
        row[4] = "pa-rebuild-forged"
    elif forgery == "current_uuid":
        row[5] = "wrong-current-uuid"
    elif forgery == "current_locator":
        row[6] = "wrong-current-locator"
    elif forgery == "current_attestation":
        row[7] = "0" * 64
    elif forgery == "stored_parent":
        row[8] = authority.current_attestation.model_copy(
            update={"refresh_checkpoint": "forged"}
        ).model_dump(mode="json")
    elif forgery == "stored_generation":
        row[9] = authority.current_identity.generation.model_copy(
            update={"embedding_model_revision": "forged@sha256:model"}
        ).model_dump(mode="json")
    elif forgery == "candidate":
        row[10] = "0" * 64
    elif forgery == "database_root":
        row[11] = "0" * 64
    elif forgery == "fresh_locator":
        identity = identity.model_copy(update={"projection_locator": "pa-rebuild-forged"})
    elif forgery == "fresh_uuid":
        identity = authority.current_identity
    else:
        updates: dict[str, Any] = {
            "source_id": "source-2",
            "generation_id": "generation-2",
            "operation_id": "forged-operation",
            "parent": "0" * 64,
            "root": "0" * 64,
            "mapping": "0" * 64,
            "coverage": (1, 2),
            "document_count": attestation.validated_document_count + 1,
            "rule_count": attestation.validated_rule_unit_count + 1,
            "digest": "0" * 64,
        }
        field = {
            "operation_id": "publication_attempt_id",
            "parent": "parent_attestation_sha256",
            "root": "manifest_root_sha256",
            "mapping": "mapping_sha256",
            "coverage": "covered_publication_sequences",
            "document_count": "validated_document_count",
            "rule_count": "validated_rule_unit_count",
            "digest": "attestation_sha256",
        }.get(forgery, forgery)
        attestation = attestation.model_copy(update={field: updates[forgery]})

    with pytest.raises(PublicationConflict, match="ATTESTATION_MISMATCH"):
        postgres_repository._validate_rebuild_swap_authority(
            authority=authority,
            rebuilt_identity=identity,
            attestation=attestation,
            database_row=tuple(row),
        )


def _expected_rebuild_documents(
    service: HybridRecoveryService,
    authority: GenerationRebuildAuthority,
    operation: GenerationRebuildOperation,
) -> tuple[ProjectionAuthorityDocument, ...]:
    _, _, documents = service._verified_inputs(authority)
    result: list[ProjectionAuthorityDocument] = []
    for document in documents:
        projected = project_rule_unit_document(
            document,
            identity=authority.current_identity,
            publication_attempt_id=operation.operation_id,
        )
        result.append(
            ProjectionAuthorityDocument(
                projection_id=document.projection_id,
                rule_unit=document.rule_unit,
                manifest_entry=document.manifest_entry,
                approved_metadata=document.approved_metadata,
                projection_revision=document.projection_revision,
                embedding_sha256=str(projected["embedding_sha256"]),
                projection_material_sha256=str(projected["projection_material_sha256"]),
                immutable_projection_sha256=str(projected["immutable_projection_sha256"]),
                last_publication_attempt_id=(
                    document.last_publication_attempt_id or operation.operation_id
                ),
            )
        )
    return tuple(result)


def _resign_attestation(
    attestation: KnowledgeProjectionAttestation,
) -> KnowledgeProjectionAttestation:
    digest = postgres_repository._attestation_fingerprint(attestation)
    return attestation.model_copy(
        update={
            "attestation_sha256": digest,
            "attestation_id": f"attestation-{digest}",
        }
    )


def test_postgres_rebuild_stage_accepts_db_derived_projection_digest(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    root, shard_contents, documents = service._verified_inputs(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    expected = _expected_rebuild_documents(service, authority, operation)
    expected_digest = postgres_repository._projection_authority_digest(expected)
    attestation = _resign_attestation(
        recovery_module._rebuild_attestation(authority, identity, evidence).model_copy(
            update={"projection_sha256": expected_digest}
        )
    )
    row = (
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "BUILDING",
        operation.projection_locator,
        authority.current_identity.index_uuid,
        authority.current_identity.projection_locator,
        authority.current_attestation.attestation_sha256,
        authority.current_attestation.model_dump(mode="json"),
        authority.current_identity.generation.model_dump(mode="json"),
        authority.candidate_digest,
        authority.manifest_root.root_sha256,
    )

    postgres_repository._validate_rebuild_swap_authority(
        authority=authority,
        rebuilt_identity=identity,
        attestation=attestation,
        database_row=row,
        expected_documents=expected,
        expected_projection_sha256=expected_digest,
    )


def test_postgres_rebuild_stage_rejects_forged_resigned_projection_digest(
    tmp_path: Any,
) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    root, shard_contents, documents = service._verified_inputs(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    expected = _expected_rebuild_documents(service, authority, operation)
    expected_digest = postgres_repository._projection_authority_digest(expected)
    forged = _resign_attestation(
        recovery_module._rebuild_attestation(authority, identity, evidence).model_copy(
            update={"projection_sha256": "0" * 64}
        )
    )
    row = (
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "BUILDING",
        operation.projection_locator,
        authority.current_identity.index_uuid,
        authority.current_identity.projection_locator,
        authority.current_attestation.attestation_sha256,
        authority.current_attestation.model_dump(mode="json"),
        authority.current_identity.generation.model_dump(mode="json"),
        authority.candidate_digest,
        authority.manifest_root.root_sha256,
    )

    with pytest.raises(PublicationConflict, match="ATTESTATION_MISMATCH"):
        postgres_repository._validate_rebuild_swap_authority(
            authority=authority,
            rebuilt_identity=identity,
            attestation=forged,
            database_row=row,
            expected_documents=expected,
            expected_projection_sha256=expected_digest,
        )


def test_postgres_rebuild_stage_rejects_stored_material_digest_tamper(
    tmp_path: Any,
) -> None:
    service, repository, _ = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    expected = _expected_rebuild_documents(service, authority, operation)
    tampered = (
        expected[0].model_copy(update={"projection_material_sha256": "0" * 64}),
        *expected[1:],
    )

    with pytest.raises(PublicationConflict, match="PROJECTION_AUTHORITY_MISMATCH"):
        postgres_repository._validate_stored_projection_materialization(
            tampered,
            generation=authority.current_identity.generation,
        )


@pytest.mark.parametrize("already_staged", (False, True))
def test_postgres_rebuild_stage_persists_db_derived_validation_before_cas(
    tmp_path: Any,
    already_staged: bool,
) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    root, shard_contents, documents = service._verified_inputs(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    expected = _expected_rebuild_documents(service, authority, operation)
    expected_digest = postgres_repository._projection_authority_digest(expected)
    attestation = _resign_attestation(
        recovery_module._rebuild_attestation(authority, identity, evidence).model_copy(
            update={"projection_sha256": expected_digest}
        )
    )
    shard = decode_manifest_shard_artifact(
        service.artifact_store.get_exact(authority.shard_refs[0])
    )
    projected = expected[0]
    rule_payload = {
        "projection_id": projected.projection_id,
        "projection_revision": projected.projection_revision,
        "rule_unit": projected.rule_unit.model_dump(mode="json"),
    }
    current_row = (
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "VALIDATED" if already_staged else "BUILDING",
        operation.projection_locator,
        authority.current_identity.index_uuid,
        authority.current_identity.projection_locator,
        authority.current_attestation.attestation_sha256,
        authority.current_attestation.model_dump(mode="json"),
        authority.current_identity.generation.model_dump(mode="json"),
        authority.candidate_digest,
        authority.manifest_root.root_sha256,
    )

    class Result:
        def __init__(
            self,
            *,
            row: Any = None,
            rows: list[tuple[Any, ...]] | None = None,
            rowcount: int = 1,
        ) -> None:
            self.row = row
            self.rows = rows or []
            self.rowcount = rowcount

        def fetchone(self) -> Any:
            return self.row

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self.rows

    class Connection:
        def __init__(self) -> None:
            self.staged: tuple[Any, ...] | None = None
            self.queries: list[str] = []

        def transaction(self) -> Connection:
            return self

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, query: str, params: tuple[Any, ...] = ()) -> Result:
            self.queries.append(query)
            if "FROM pg_trigger" in query:
                return Result(row=(True,))
            if "SELECT operation.source_id" in query:
                return Result(row=current_row)
            if "SELECT m.source_publication_seq" in query:
                assert len(params[-1]) <= 1000
                return Result(
                    rows=[
                        (
                            authority.manifest_root.source_publication_seq,
                            shard.model_dump(mode="json"),
                        )
                    ]
                )
            if "SELECT reserved_sequence" in query:
                assert len(params[-1]) <= 1000
                return Result(
                    rows=[
                        (
                            authority.manifest_root.source_publication_seq,
                            authority.current_attestation.publication_attempt_id,
                        )
                    ]
                )
            if "SELECT r.rule_unit_revision_id" in query:
                assert len(params[-1]) <= 1000
                return Result(
                    rows=[
                        (
                            projected.rule_unit.rule_unit_revision_id,
                            rule_payload,
                            projected.approved_metadata.model_dump(mode="json"),
                            projected.embedding_sha256,
                            projected.projection_material_sha256,
                            projected.immutable_projection_sha256,
                        )
                    ]
                )
            if "INSERT INTO hybrid_rebuild_validation" in query:
                self.staged = (
                    params[1],
                    params[2],
                    params[3],
                    params[4],
                    params[5],
                    params[6],
                    params[7],
                    params[8],
                )
                return Result(rowcount=0 if already_staged else 1)
            if "FROM hybrid_rebuild_validation WHERE" in query:
                return Result(row=self.staged)
            if "UPDATE hybrid_projection_operation operation" in query:
                return Result(rowcount=1)
            if "SELECT state, index_uuid, projection_locator" in query:
                return Result(row=("VALIDATED", identity.index_uuid, operation.projection_locator))
            raise AssertionError(query)

    class Pool:
        def __init__(self) -> None:
            self.value = Connection()

        def connection(self) -> Connection:
            return self.value

    pool = Pool()
    postgres = postgres_repository.PostgresHybridKnowledgeRepository(pool=pool)

    validation = postgres.stage_generation_rebuild_validation(
        authority=authority,
        rebuilt_identity=identity,
        attestation=attestation,
    )

    assert validation.projection_sha256 == expected_digest
    assert validation.attestation_sha256 == attestation.attestation_sha256
    assert any("SET state='VALIDATED'" in query for query in pool.value.queries) is (
        not already_staged
    )


def test_postgres_rebuild_swap_rejects_tampered_staged_record(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    root, shard_contents, documents = service._verified_inputs(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    attestation = recovery_module._rebuild_attestation(authority, identity, evidence)
    validation = repository.stage_generation_rebuild_validation(
        authority=authority,
        rebuilt_identity=identity,
        attestation=attestation,
    )
    fingerprint = postgres_repository._rebuild_validation_fingerprint(validation)
    payload = validation.model_dump(mode="json")
    payload["projection_sha256"] = "0" * 64
    row = (
        validation.source_id,
        validation.generation_id,
        validation.projection_locator,
        validation.index_uuid,
        validation.parent_attestation_sha256,
        validation.attestation_sha256,
        fingerprint,
        payload,
    )

    with pytest.raises(PublicationConflict, match="REBUILD_VALIDATION_CONFLICT"):
        postgres_repository._validate_staged_rebuild_record(
            expected=validation,
            expected_validation_sha256=fingerprint,
            database_row=row,
        )


def test_postgres_rebuild_swap_rejects_parent_pointer_drift_after_stage(
    tmp_path: Any,
) -> None:
    service, repository, index = _fixture(tmp_path)
    authority = repository.authority
    operation = repository.begin_generation_rebuild(authority)
    root, shard_contents, documents = service._verified_inputs(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    attestation = recovery_module._rebuild_attestation(authority, identity, evidence)
    validation = repository.stage_generation_rebuild_validation(
        authority=authority,
        rebuilt_identity=identity,
        attestation=attestation,
    )
    row = (
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "VALIDATED",
        operation.projection_locator,
        identity.index_uuid,
        validation.parent_attestation_sha256,
        validation.attestation_sha256,
        postgres_repository._rebuild_validation_fingerprint(validation),
        validation.model_dump(mode="json"),
        "drifted-parent-index-uuid",
        validation.parent_projection_locator,
        validation.parent_attestation_sha256,
    )

    with pytest.raises(PublicationConflict, match="REBUILD_VALIDATION_CONFLICT"):
        postgres_repository._validate_staged_rebuild_swap(
            authority=authority,
            rebuilt_identity=identity,
            attestation=attestation,
            database_row=row,
        )


@pytest.mark.parametrize("lost_update", ("pointer", "committed"))
def test_postgres_rebuild_swap_requires_each_state_update_rowcount_one(
    tmp_path: Any,
    lost_update: str,
) -> None:
    service, authority_repository, index = _fixture(tmp_path)
    authority = authority_repository.authority
    root, shard_contents, documents = service._verified_inputs(authority)
    operation = authority_repository.begin_generation_rebuild(authority)
    identity, evidence = index.rebuild_generation(
        authority,
        operation=operation,
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )
    attestation = recovery_module._rebuild_attestation(authority, identity, evidence)
    validation = authority_repository.stage_generation_rebuild_validation(
        authority=authority,
        rebuilt_identity=identity,
        attestation=attestation,
    )
    database_row = (
        authority.source_id,
        authority.generation_id,
        "REBUILD",
        "VALIDATED",
        operation.projection_locator,
        identity.index_uuid,
        validation.parent_attestation_sha256,
        validation.attestation_sha256,
        postgres_repository._rebuild_validation_fingerprint(validation),
        validation.model_dump(mode="json"),
        validation.parent_index_uuid,
        validation.parent_projection_locator,
        validation.parent_attestation_sha256,
    )

    class Result:
        def __init__(self, *, rowcount: int = 1, row: Any = None) -> None:
            self.rowcount = rowcount
            self.row = row

        def fetchone(self) -> Any:
            return self.row

    class Connection:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def transaction(self) -> Connection:
            return self

        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: Any) -> None:
            return None

        def execute(self, query: str, _params: tuple[Any, ...]) -> Result:
            self.queries.append(query)
            if "SELECT operation.source_id" in query:
                return Result(row=database_row)
            if "UPDATE hybrid_generation_projection" in query:
                return Result(rowcount=0 if lost_update == "pointer" else 1)
            if "SET state='COMMITTED'" in query:
                return Result(rowcount=0 if lost_update == "committed" else 1)
            return Result()

    class Pool:
        def __init__(self) -> None:
            self.value = Connection()

        def connection(self) -> Connection:
            return self.value

    repository = postgres_repository.PostgresHybridKnowledgeRepository(pool=Pool())

    with pytest.raises(PublicationConflict, match="FENCE_LOST"):
        repository.swap_generation_projection(
            authority=authority,
            rebuilt_identity=identity,
            attestation=attestation,
        )
    assert not any(
        authority_table in query
        for query in repository._pool.value.queries
        for authority_table in (
            "hybrid_rule_unit_manifest_member",
            "hybrid_knowledge_rule_unit_revision",
            "hybrid_projection_materialization",
        )
    )


def test_fresh_cleanup_failure_tracks_orphan_without_overwriting_primary_and_retries_idempotently(
    tmp_path: Any,
) -> None:
    class InvalidEvidenceIndex(_RecoveryIndex):
        def rebuild_generation(self, *args: Any, **kwargs: Any) -> Any:
            identity, evidence = super().rebuild_generation(*args, **kwargs)
            return identity, evidence.model_copy(update={"candidate_digest": "0" * 64})

    service, repository, _ = _fixture(tmp_path)
    index = InvalidEvidenceIndex()
    index.fail_discard = True
    service.index = index

    for _ in range(2):
        with pytest.raises(PublicationConflict, match="ATTESTATION_MISMATCH") as captured:
            service.rebuild_generation(source_id="source-1", generation_id="generation-1")
        assert any(
            "fresh rebuild cleanup failed: RuntimeError" in note
            for note in getattr(captured.value, "__notes__", ())
        )

    tracked = repository.recovery_orphans[repository.operation_id]
    assert tracked.index_uuid == "fresh-index-uuid"
    assert tracked != repository.authority.current_identity
    assert repository.swapped is None
    assert repository.failed_operations == [
        (repository.operation_id, "ATTESTATION_MISMATCH", tracked)
    ]


class _LowLevelRecoveryIndex(_Index):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[str] = []
        self.deleted_rebuilds: list[SearchIndexIdentity] = []

    def create_rebuild_index(self, generation: Any, **kwargs: Any) -> SearchIndexIdentity:
        self.events.append("create")
        return SearchIndexIdentity(
            generation=generation,
            index_uuid="fresh-index-uuid",
            projection_locator=kwargs["projection_locator"],
        )

    def bulk_upsert(self, request: Any) -> Any:
        self.events.append("bulk")
        return super().bulk_upsert(request)

    def restore_projection_memberships(self, **kwargs: Any) -> Any:
        self.events.append("restore")
        return ProjectionMembershipRestorationResult(
            accepted_count=len(kwargs["restorations"]),
            refresh_checkpoint="restoration-checkpoint",
        )

    def validate_exact_projection(self, **kwargs: Any) -> Any:
        self.events.append("readback")
        return super().validate_exact_projection(**kwargs)

    def validate_smoke_retrieval(self, request: Any) -> Any:
        self.events.append("smoke")
        return super().validate_smoke_retrieval(request)

    def delete_attempt_projection(self, **_: Any) -> str:
        self.events.append("cleanup")
        return "cleanup-checkpoint"

    def resolve_rebuild_projection(self, **kwargs: Any) -> SearchIndexIdentity:
        return SearchIndexIdentity(
            generation=kwargs["generation"],
            index_uuid=kwargs["expected_index_uuid"] or "resolved-index-uuid",
            projection_locator=kwargs["projection_locator"],
        )

    def purge_rebuild_projection(self, **kwargs: Any) -> None:
        self.deleted_rebuilds.append(
            SearchIndexIdentity(
                generation=kwargs["generation"],
                index_uuid=kwargs["expected_index_uuid"],
                projection_locator=kwargs["projection_locator"],
            )
        )


def test_rebuild_requires_exact_readback_and_smoke_before_evidence(tmp_path: Any) -> None:
    service, repository, _ = _fixture(tmp_path)
    root, shard_contents, documents = service._verified_inputs(repository.authority)
    index = _LowLevelRecoveryIndex()
    adapter = OpenSearchRecoveryIndex(
        index=index,  # type: ignore[arg-type]
        embedding=_Embedding(),  # type: ignore[arg-type]
        embedding_instruction="Represent the insurance rule.",
    )

    _, evidence = adapter.rebuild_generation(
        repository.authority,
        operation=repository.begin_generation_rebuild(repository.authority),
        root=root,
        shard_contents=shard_contents,
        documents=documents,
    )

    assert index.events == ["create", "bulk", "readback", "smoke"]
    assert index.readbacks
    assert index.smokes
    assert evidence.validated_rule_unit_count == len(documents)


def test_shared_orphan_repair_reads_back_after_cleanup_then_smokes(tmp_path: Any) -> None:
    service, repository, _ = _fixture(tmp_path)
    root, _, documents = service._verified_inputs(repository.authority)
    index = _LowLevelRecoveryIndex()
    adapter = OpenSearchRecoveryIndex(
        index=index,  # type: ignore[arg-type]
        embedding=_Embedding(),  # type: ignore[arg-type]
        embedding_instruction="Represent the insurance rule.",
    )
    orphan = OrphanProjection(
        attempt_id="orphan-attempt",
        source_id=repository.authority.source_id,
        identity=repository.authority.current_identity,
        reserved_publication_seq=2,
    )

    adapter.repair_attempt_projection(
        repository.authority,
        orphan,
        operation_id="repair-operation-2",
        root=root,
        documents=documents,
    )

    assert index.events == ["restore", "bulk", "cleanup", "readback", "smoke"]


def test_rebuild_readback_failure_defers_cleanup_to_authoritative_service(tmp_path: Any) -> None:
    class ReadbackFailingIndex(_LowLevelRecoveryIndex):
        def validate_exact_projection(self, **kwargs: Any) -> Any:
            self.events.append("readback")
            raise RuntimeError("exact readback failed")

    service, repository, _ = _fixture(tmp_path)
    root, shard_contents, documents = service._verified_inputs(repository.authority)
    index = ReadbackFailingIndex()
    adapter = OpenSearchRecoveryIndex(
        index=index,  # type: ignore[arg-type]
        embedding=_Embedding(),  # type: ignore[arg-type]
        embedding_instruction="Represent the insurance rule.",
    )

    with pytest.raises(RuntimeError, match="exact readback failed"):
        adapter.rebuild_generation(
            repository.authority,
            operation=repository.begin_generation_rebuild(repository.authority),
            root=root,
            shard_contents=shard_contents,
            documents=documents,
        )

    assert index.events == ["create", "bulk", "readback"]
    assert index.deleted_rebuilds == []


def test_adapter_readback_failure_keeps_primary_and_tracks_durable_unknown_locator(
    tmp_path: Any,
) -> None:
    class ReadbackAndCleanupFailingIndex(_LowLevelRecoveryIndex):
        def validate_exact_projection(self, **kwargs: Any) -> Any:
            self.events.append("readback")
            raise RuntimeError("exact readback failed")

        def purge_rebuild_projection(self, **_: Any) -> None:
            raise RuntimeError("delete failed")

    service, repository, _ = _fixture(tmp_path)
    index = ReadbackAndCleanupFailingIndex()
    service.index = OpenSearchRecoveryIndex(
        index=index,  # type: ignore[arg-type]
        embedding=_Embedding(),  # type: ignore[arg-type]
        embedding_instruction="Represent the insurance rule.",
    )

    with pytest.raises(RuntimeError, match="exact readback failed") as captured:
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")

    assert not getattr(captured.value, "__notes__", ())
    tracked = next(item for item in repository.orphans if isinstance(item, RebuildProjectionOrphan))
    assert tracked.index_uuid is None
    assert tracked.projection_locator == rebuild_projection_locator(
        source_id="source-1",
        generation_id="generation-1",
        operation_id=repository.operation_id,
    )
    assert repository.swapped is None


def test_rebuild_unions_historical_rule_across_failed_sequence_gap(tmp_path: Any) -> None:
    store = FileSystemKnowledgeArtifactStore(tmp_path)
    request = _request()
    old_seed = request.projection_seeds[0]
    old_manifest = build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id="snapshot-1",
        source_publication_seq=1,
        generation_id="generation-1",
        memberships=request.memberships,
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        artifact_store=store,
    )
    new_content = "Replacement rule for sequence two."
    new_rule = old_seed.rule_unit.model_copy(
        update={
            "rule_unit_revision_id": "rule-2",
            "logical_rule_key": "rule-logical-2",
            "document_id": "document-2",
            "revision_id": "revision-2",
            "structured_build_id": "build-2",
            "content": new_content,
            "content_sha256": hashlib.sha256(new_content.encode()).hexdigest(),
            "citation_uri": (
                "knowledge://source/source-1/document/document-2/revision/revision-2#page=1"
            ),
            "lineage": old_seed.rule_unit.lineage.model_copy(update={"block_ids": ("block-2",)}),
        }
    )
    new_manifest = build_rule_unit_manifest(
        source_id="source-1",
        source_snapshot_id="snapshot-2",
        source_publication_seq=3,
        generation_id="generation-1",
        memberships=(ManifestRuleUnitMembership(rule_unit=new_rule, publication_seq_from=3),),
        created_at=datetime(2026, 7, 14, 1, tzinfo=UTC),
        artifact_store=store,
        previous=old_manifest,
    )
    _, base_repository, _ = _fixture(tmp_path)
    authority = base_repository.authority.model_copy(
        update={
            "manifest_root": new_manifest.root,
            "root_ref": new_manifest.root_ref,
            "shard_refs": tuple(item.artifact_ref for item in new_manifest.shards),
            "current_attestation": base_repository.authority.current_attestation.model_copy(
                update={
                    "manifest_root_sha256": new_manifest.root.root_sha256,
                    "covered_publication_sequences": (1, 3),
                }
            ),
            "projection_authority": (
                base_repository.authority.projection_authority[0],
                RebuildProjectionAuthority(
                    projection_id="projection-2",
                    projection_revision="rule-unit-search.v1",
                    rule_unit=new_rule,
                    approved_metadata=old_seed.approved_metadata,
                    last_publication_attempt_id="attempt-3",
                ),
            ),
            "retained_manifests": (
                RetainedManifestAuthority(
                    root=old_manifest.root,
                    root_ref=old_manifest.root_ref,
                    shard_refs=tuple(item.artifact_ref for item in old_manifest.shards),
                ),
                RetainedManifestAuthority(
                    root=new_manifest.root,
                    root_ref=new_manifest.root_ref,
                    shard_refs=tuple(item.artifact_ref for item in new_manifest.shards),
                ),
            ),
        }
    )
    repository = _RecoveryRepository(authority)
    index = _RecoveryIndex()
    service = HybridRecoveryService(repository=repository, artifact_store=store, index=index)
    service.rebuild_generation(source_id="source-1", generation_id="generation-1")
    documents = index.rebuilt_documents
    entries = {item.rule_unit.rule_unit_revision_id: item.manifest_entry for item in documents}
    assert entries["rule-1"].publication_seq_to == 2
    assert entries["rule-2"].publication_seq_from == 3
    assert entries["rule-2"].publication_seq_to is None


class _CorruptingStore:
    def __init__(self, delegate: Any, corrupt_ref: Any) -> None:
        self.delegate = delegate
        self.corrupt_ref = corrupt_ref

    def get_exact(self, ref: Any) -> bytes:
        content = self.delegate.get_exact(ref)
        if ref == self.corrupt_ref:
            return content + b" "
        return content


def test_corrupt_exact_root_fails_before_index_or_pointer_swap(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    service.artifact_store = _CorruptingStore(service.artifact_store, repository.authority.root_ref)
    with pytest.raises((ValueError, PublicationConflict)):
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")
    assert repository.swapped is None
    assert index.deleted == []


def test_rebuild_failure_after_durable_begin_transitions_operation_for_retry(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)

    def fail(*_: Any, **__: Any) -> Any:
        raise RuntimeError("rebuild transport failed")

    index.rebuild_generation = fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="transport failed"):
        service.rebuild_generation(source_id="source-1", generation_id="generation-1")
    assert repository.failed_operations == [(repository.operation_id, "REBUILD_FAILED", None)]
    assert repository.swapped is None


class _Body:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def read(self, amount: int) -> bytes:
        return self.content[:amount]


class _S3:
    def __init__(self) -> None:
        self.objects: dict[str, dict[str, Any]] = {}

    def get_bucket_versioning(self, **_: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def head_object(self, *, Key: str, **_: Any) -> dict[str, Any]:
        if Key not in self.objects:
            raise KeyError(Key)
        return {key: value for key, value in self.objects[Key].items() if key != "Body"}

    def put_object(self, *, Key: str, Body: bytes, ContentType: str, Metadata: Any, **_: Any):
        if Key in self.objects:
            raise RuntimeError("precondition")
        version = "opaque-version-1"
        self.objects[Key] = {
            "VersionId": version,
            "ContentLength": len(Body),
            "ContentType": ContentType,
            "Metadata": Metadata,
            "Body": Body,
        }
        return {"VersionId": version}

    def get_object(self, *, Key: str, VersionId: str, **_: Any) -> dict[str, Any]:
        item = self.objects[Key]
        assert item["VersionId"] == VersionId
        return {**item, "Body": _Body(item["Body"])}


def test_s3_artifacts_require_content_address_and_verify_exact_version() -> None:
    client = _S3()
    store = S3ExactArtifactStore(client=client, bucket="test-bucket")
    content = b'{"canonical":true}'
    digest = hashlib.sha256(content).hexdigest()
    key = f"hybrid-manifests/roots/{digest}.json"
    ref = store.put_immutable(key=key, content=content, media_type="application/json")
    assert store.put_immutable(key=key, content=content, media_type="application/json") == ref
    assert store.get_exact(ref) == content
    with pytest.raises(S3ArtifactError, match="system-generated"):
        store.put_immutable(key="../secret", content=content, media_type="application/json")
    client.objects[key]["Body"] = b"corrupt"
    with pytest.raises(S3ArtifactError, match="length|corrupt"):
        store.get_exact(ref)


def test_s3_environment_custom_endpoint_does_not_inherit_ambient_proxy(
    monkeypatch: Any,
) -> None:
    import boto3

    calls: list[dict[str, Any]] = []

    def client(_service: str, **kwargs: Any) -> _S3:
        calls.append(kwargs)
        return _S3()

    monkeypatch.setattr(boto3, "client", client)
    S3ExactArtifactStore.from_environment(
        bucket="test-bucket",
        endpoint_url="http://127.0.0.1:9000",
    )
    assert calls[-1]["config"].proxies == {}

    S3ExactArtifactStore.from_environment(bucket="test-bucket")
    assert "config" not in calls[-1]

    S3ExactArtifactStore.from_environment(
        bucket="test-bucket",
        endpoint_url="https://s3-gateway.example.test",
        allow_endpoint_proxy=True,
    )
    assert "config" not in calls[-1]


def test_s3_custom_endpoint_scheme_policy_is_fail_closed(monkeypatch: Any) -> None:
    import boto3

    calls: list[dict[str, Any]] = []

    def client(_service: str, **kwargs: Any) -> _S3:
        calls.append(kwargs)
        return _S3()

    monkeypatch.setattr(boto3, "client", client)
    with pytest.raises(ValueError, match="explicit opt-in"):
        S3ExactArtifactStore.from_environment(
            bucket="test-bucket",
            endpoint_url="http://s3.internal:9000",
        )

    S3ExactArtifactStore.from_environment(
        bucket="test-bucket",
        endpoint_url="http://s3.internal:9000",
        allow_insecure_endpoint=True,
    )
    assert calls[-1]["config"].proxies == {}

    S3ExactArtifactStore.from_environment(
        bucket="test-bucket",
        endpoint_url="https://s3.internal:9000",
    )
    assert calls[-1]["config"].proxies == {}


def test_postgres_authority_verification_batches_every_any_query_at_1000() -> None:
    size = postgres_repository.MAX_AUTHORITY_BATCH_SIZE + 1
    metadata = {f"metadata-{index:04d}": "a" * 64 for index in range(size)}
    visibility = {f"visibility-{index:04d}": "b" * 64 for index in range(size)}
    rules = {f"rule-{index:04d}": ("c" * 64, "d" * 64) for index in range(size)}
    materials = {
        f"projection-{index:04d}": (
            f"rule-{index:04d}",
            "e" * 64,
            "f" * 64,
            "0" * 64,
        )
        for index in range(size)
    }

    class Result:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self.rows = rows

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self.rows

    class Connection:
        def __init__(self) -> None:
            self.batch_sizes: list[int] = []

        def execute(self, query: str, params: tuple[Any, ...]) -> Result:
            keys = params[-1]
            assert isinstance(keys, list)
            self.batch_sizes.append(len(keys))
            assert len(keys) <= postgres_repository.MAX_AUTHORITY_BATCH_SIZE
            if "hybrid_approved_rule_metadata" in query:
                rows = [(key, metadata[key]) for key in keys]
            elif "hybrid_approved_visibility_scope" in query:
                rows = [(key, visibility[key]) for key in keys]
            elif "hybrid_knowledge_rule_unit_revision" in query:
                rows = [(key, *rules[key]) for key in keys]
            else:
                rows = [(key, *materials[key]) for key in keys]
            return Result(rows)

    connection = Connection()
    postgres_repository.PostgresHybridKnowledgeRepository._verify_projection_authority_batches(
        connection,
        source_id="source-1",
        generation_id="generation-1",
        metadata=metadata,
        visibility=visibility,
        rules=rules,
        materials=materials,
    )

    assert connection.batch_sizes == [1000, 1] * 4


def test_postgres_authority_inserts_use_psycopg_cursor_executemany(tmp_path: Any) -> None:
    service, in_memory_repository, _, _ = _service(tmp_path)
    service.publish(_request())
    commit = next(iter(in_memory_repository.staged_commits.values()))
    authority = commit.staged_projection_documents[0]
    metadata = authority.approved_metadata
    visibility = authority.rule_unit.visibility_scope

    expected_metadata = {
        metadata.metadata_revision_id: postgres_repository.stable_digest(
            metadata.model_dump(mode="json")
        )
    }
    expected_visibility = {
        visibility.revision_id: postgres_repository.stable_digest(
            visibility.model_dump(mode="json")
        )
    }
    expected_rules = {
        authority.rule_unit.rule_unit_revision_id: (
            authority.rule_unit.content_sha256,
            authority.rule_unit.authority_sha256,
        )
    }
    expected_materials = {
        authority.projection_id: (
            authority.rule_unit.rule_unit_revision_id,
            authority.embedding_sha256,
            authority.projection_material_sha256,
            authority.immutable_projection_sha256,
        )
    }

    class Result:
        def __init__(self, rows: list[tuple[Any, ...]]) -> None:
            self._rows = rows

        def fetchall(self) -> list[tuple[Any, ...]]:
            return self._rows

    class Cursor:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[tuple[Any, ...]]]] = []
            self.closed = False

        def __enter__(self) -> Cursor:
            return self

        def __exit__(self, *_: Any) -> None:
            self.closed = True

        def executemany(self, query: str, params: list[tuple[Any, ...]]) -> None:
            assert len(params) <= postgres_repository.MAX_AUTHORITY_BATCH_SIZE
            self.calls.append((query, params))

    class Connection:
        def __init__(self) -> None:
            self.cursor_value = Cursor()
            self.cursor_calls = 0

        def cursor(self) -> Cursor:
            self.cursor_calls += 1
            return self.cursor_value

        def execute(self, query: str, params: tuple[Any, ...]) -> Result:
            keys = params[-1]
            assert isinstance(keys, list)
            if "hybrid_approved_rule_metadata" in query:
                rows = [(key, expected_metadata[key]) for key in keys]
            elif "hybrid_approved_visibility_scope" in query:
                rows = [(key, expected_visibility[key]) for key in keys]
            elif "hybrid_knowledge_rule_unit_revision" in query:
                rows = [(key, *expected_rules[key]) for key in keys]
            else:
                rows = [(key, *expected_materials[key]) for key in keys]
            return Result(rows)

    connection = Connection()
    assert not hasattr(connection, "executemany")

    repository = postgres_repository.PostgresHybridKnowledgeRepository(pool=None)
    repository._insert_projection_authority(connection, commit)

    assert connection.cursor_calls == 1
    assert len(connection.cursor_value.calls) == 5
    assert connection.cursor_value.closed is True


def test_postgres_jsonb_hydration_uses_json_mode_for_strict_models(tmp_path: Any) -> None:
    service, in_memory_repository, _, _ = _service(tmp_path)
    publication = service.publish(_request())
    commit = next(iter(in_memory_repository.staged_commits.values()))
    authority = commit.staged_projection_documents[0]
    rebuild_validation = GenerationRebuildValidation(
        operation_id="rebuild-jsonb-hydration",
        source_id=commit.attempt.source_id,
        generation_id=commit.attempt.generation_id,
        projection_locator="proofagent-hybrid-source-1-generation-1-rebuild-jsonb-hydration",
        index_uuid=commit.identity.index_uuid,
        parent_index_uuid=commit.identity.index_uuid,
        parent_projection_locator=commit.identity.projection_locator,
        parent_attestation_sha256=commit.attestation.attestation_sha256,
        candidate_digest=commit.attempt.candidate_digest,
        manifest_root_sha256=commit.manifest.root.root_sha256,
        mapping_sha256=commit.generation.mapping_sha256,
        covered_publication_sequences=commit.attestation.covered_publication_sequences,
        projection_sha256=commit.attestation.projection_sha256,
        validated_document_count=commit.attestation.validated_document_count,
        validated_rule_unit_count=commit.attestation.validated_rule_unit_count,
        attestation_sha256=commit.attestation.attestation_sha256,
    )
    root_payload = commit.manifest.root.model_dump(mode="json")
    publication_payload = publication.model_dump(mode="json")
    assert isinstance(root_payload["created_at"], str)
    assert isinstance(publication_payload["published_at"], str)

    strict_jsonb_models = (
        commit.manifest.root,
        commit.manifest.shards[0].shard,
        commit.attestation,
        commit.generation,
        publication,
        rebuild_validation,
        authority.rule_unit,
        authority.approved_metadata,
    )
    for expected in strict_jsonb_models:
        assert (
            postgres_repository._hydrate_jsonb_model(
                type(expected), expected.model_dump(mode="json")
            )
            == expected
        )


def test_manifest_materialization_hydrates_iso_datetime_jsonb_dict(tmp_path: Any) -> None:
    service, in_memory_repository, _, _ = _service(tmp_path)
    service.publish(_request())
    commit = next(iter(in_memory_repository.staged_commits.values()))
    root_ref = commit.manifest.root_ref

    class Result:
        def fetchall(self) -> list[tuple[Any, ...]]:
            return [
                (
                    persisted.shard.model_dump(mode="json"),
                    persisted.artifact_ref.artifact_uri,
                    persisted.artifact_ref.version_id,
                    persisted.artifact_ref.sha256,
                    persisted.artifact_ref.size_bytes,
                    persisted.artifact_ref.media_type,
                )
                for persisted in commit.manifest.shards
            ]

    class Connection:
        def execute(self, _query: str, params: tuple[Any, ...]) -> Result:
            assert params == (commit.manifest.root.root_sha256,)
            return Result()

    publication_row = (
        {},
        commit.manifest.root.model_dump(mode="json"),
        root_ref.artifact_uri,
        root_ref.version_id,
        root_ref.sha256,
        root_ref.size_bytes,
        root_ref.media_type,
    )
    assert isinstance(publication_row[1]["created_at"], str)

    materialization = postgres_repository._load_manifest_materialization(
        Connection(), publication_row
    )

    assert materialization == commit.manifest


def test_hybrid_migration_upgrades_early_schema_and_is_rerunnable() -> None:
    migration = Path("proof_agent/configuration/migrations/0001_hybrid_knowledge.sql").read_text(
        encoding="utf-8"
    )

    assert "ADD COLUMN IF NOT EXISTS projection_locator" in migration
    assert "ADD COLUMN IF NOT EXISTS index_uuid" in migration
    assert (
        "CREATE UNIQUE INDEX IF NOT EXISTS hybrid_projection_operation_locator_unique" in migration
    )
    assert "DROP CONSTRAINT IF EXISTS hybrid_projection_orphan_cleanup_state_check" in migration
    assert "ALTER COLUMN index_uuid DROP NOT NULL" in migration
    attestation_table = migration.split(
        "CREATE TABLE IF NOT EXISTS hybrid_projection_attestation (", 1
    )[1].split(");", 1)[0]
    operation_table = migration.split(
        "CREATE TABLE IF NOT EXISTS hybrid_projection_operation (", 1
    )[1].split(");", 1)[0]
    validation_table = migration.split("CREATE TABLE IF NOT EXISTS hybrid_rebuild_validation (", 1)[
        1
    ].split(");", 1)[0]
    assert "index_uuid text NOT NULL" in attestation_table
    assert "index_uuid text," in operation_table
    assert "operation_id text PRIMARY KEY" in validation_table
    assert "validation_sha256 text NOT NULL" in validation_table
    assert "validation_json jsonb NOT NULL" in validation_table
    assert "'hybrid_projection_attestation', 'hybrid_rebuild_validation'" in migration
    assert "(trigger.tgtype & 24)=24" in (
        Path("proof_agent/configuration/postgres_hybrid_knowledge_repository.py").read_text(
            encoding="utf-8"
        )
    )


def test_configured_environment_composes_functional_recovery_service(monkeypatch: Any) -> None:
    from proof_agent.bootstrap import composition
    from proof_agent.capabilities.knowledge.hybrid import opensearch, s3_artifacts
    from proof_agent.capabilities.knowledge.hybrid import recovery as recovery_module
    from proof_agent.configuration import postgres_hybrid_knowledge_repository

    class Graph:
        embedding = object()

        def close(self) -> None:
            return None

    class Transport:
        def __init__(self, **_: Any) -> None:
            pass

        def close(self) -> None:
            return None

    class Index:
        def __init__(self, **_: Any) -> None:
            pass

    class Repository:
        def close(self) -> None:
            pass

    monkeypatch.setattr(composition, "compose_hybrid_knowledge_from_env", lambda _: Graph())
    monkeypatch.setattr(opensearch, "HttpxOpenSearchTransport", Transport)
    monkeypatch.setattr(opensearch, "OpenSearchHybridIndex", Index)
    monkeypatch.setattr(recovery_module, "OpenSearchHybridIndex", Index)
    monkeypatch.setattr(
        s3_artifacts.S3ExactArtifactStore,
        "from_environment",
        classmethod(lambda cls, **kwargs: object()),
    )
    monkeypatch.setattr(
        postgres_hybrid_knowledge_repository.PostgresHybridKnowledgeRepository,
        "from_dsn",
        classmethod(lambda cls, dsn: Repository()),
    )
    service = recovery_service_from_environment(
        {
            "HYBRID_POSTGRES_DSN": "postgresql://authority.invalid/db",
            "HYBRID_S3_BUCKET": "bucket",
            "HYBRID_OPENSEARCH_ENDPOINT": "http://127.0.0.1:19200",
            "HYBRID_EMBEDDING_INSTRUCTION": "Represent rule.",
            "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "1",
        }
    )
    assert isinstance(service, HybridRecoveryService)
    service.close()


def test_recovery_environment_factory_closes_staged_resources_on_partial_failure(
    monkeypatch: Any,
) -> None:
    from proof_agent.bootstrap import composition
    from proof_agent.capabilities.knowledge.hybrid import opensearch, s3_artifacts
    from proof_agent.capabilities.knowledge.hybrid import recovery as recovery_module
    from proof_agent.configuration import postgres_hybrid_knowledge_repository

    closed: list[str] = []

    class Graph:
        embedding = object()

        def close(self) -> None:
            closed.append("graph")

    class Transport:
        def __init__(self, **_: Any) -> None:
            pass

        def close(self) -> None:
            closed.append("transport")

    class Store:
        def close(self) -> None:
            closed.append("store")

    class Index:
        def __init__(self, **_: Any) -> None:
            pass

    monkeypatch.setattr(composition, "compose_hybrid_knowledge_from_env", lambda _: Graph())
    monkeypatch.setattr(opensearch, "HttpxOpenSearchTransport", Transport)
    monkeypatch.setattr(opensearch, "OpenSearchHybridIndex", Index)
    monkeypatch.setattr(recovery_module, "OpenSearchHybridIndex", Index)
    monkeypatch.setattr(
        s3_artifacts.S3ExactArtifactStore,
        "from_environment",
        classmethod(lambda cls, **kwargs: Store()),
    )
    monkeypatch.setattr(
        postgres_hybrid_knowledge_repository.PostgresHybridKnowledgeRepository,
        "from_dsn",
        classmethod(lambda cls, dsn: (_ for _ in ()).throw(RuntimeError("database down"))),
    )

    with pytest.raises(RuntimeError, match="database down"):
        recovery_service_from_environment(
            {
                "HYBRID_POSTGRES_DSN": "postgresql://authority.invalid/db",
                "HYBRID_S3_BUCKET": "bucket",
                "HYBRID_OPENSEARCH_ENDPOINT": "http://127.0.0.1:19200",
                "HYBRID_EMBEDDING_INSTRUCTION": "Represent rule.",
                "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "1",
            }
        )

    assert closed == ["store", "transport", "graph"]


def test_recovery_cli_defaults_cleanup_to_dry_run_and_rebuild_is_idempotent(
    monkeypatch: Any,
) -> None:
    from proof_agent.delivery import cli

    calls: list[tuple[str, str, object]] = []

    class Service:
        def close(self) -> None:
            calls.append(("close", "", False))

        def reconcile_orphans(self, *, source_id: str, apply: bool):
            calls.append(("reconcile", source_id, apply))
            return OrphanReconciliationReport(source_id=source_id, dry_run=not apply)

        def rebuild_generation(self, *, source_id: str, generation_id: str):
            calls.append(("rebuild", source_id, generation_id))
            return Result()

    class Result:
        def model_dump(self, *, mode: str) -> dict[str, str]:
            assert mode == "json"
            return {"attestation_id": "attestation-1"}

    monkeypatch.setattr(cli, "_hybrid_recovery_service_from_environment", lambda: Service())
    runner = CliRunner()
    dry = runner.invoke(cli.app, ["knowledge", "reconcile-orphans", "--source-id", "source-1"])
    rebuilt = runner.invoke(
        cli.app,
        [
            "knowledge",
            "rebuild-generation",
            "--source-id",
            "source-1",
            "--generation-id",
            "generation-1",
        ],
    )
    assert dry.exit_code == 0
    assert rebuilt.exit_code == 0
    assert calls == [
        ("reconcile", "source-1", False),
        ("close", "", False),
        ("rebuild", "source-1", "generation-1"),
        ("close", "", False),
    ]
