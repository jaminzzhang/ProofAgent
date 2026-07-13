from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from typer.testing import CliRunner

from proof_agent.capabilities.knowledge.hybrid.manifest import (
    ManifestRuleUnitMembership,
    ProjectionValidationEvidence,
    build_rule_unit_manifest,
)
from proof_agent.capabilities.knowledge.hybrid.ports import SearchIndexIdentity
from proof_agent.capabilities.knowledge.hybrid.publication import PublicationConflict
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    GenerationRebuildAuthority,
    HybridRecoveryService,
    OrphanProjection,
    OrphanReconciliationReport,
    RebuildProjectionAuthority,
    RetainedManifestAuthority,
    recovery_service_from_environment,
)
from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
    S3ArtifactError,
    S3ExactArtifactStore,
)
from proof_agent.configuration.hybrid_knowledge_repository import FileSystemKnowledgeArtifactStore
from proof_agent.contracts.knowledge_index import KnowledgeProjectionAttestation
from test_hybrid_publication import _request, _service


class _RecoveryRepository:
    def __init__(self, authority: GenerationRebuildAuthority) -> None:
        self.authority = authority
        self.orphans: list[OrphanProjection] = []
        self.referenced: set[str] = set()
        self.deleted: list[str] = []
        self.retries: list[str] = []
        self.swapped: tuple[SearchIndexIdentity, KnowledgeProjectionAttestation] | None = None
        self.operation_id = "rebuild-operation-1"
        self.failed_operations: list[tuple[str, str, SearchIndexIdentity | None]] = []

    def list_orphan_projections(self, source_id: str) -> tuple[OrphanProjection, ...]:
        return tuple(item for item in self.orphans if item.source_id == source_id)

    def projection_is_referenced(self, orphan: OrphanProjection) -> bool:
        return orphan.attempt_id in self.referenced

    def record_orphan_deleted(self, attempt_id: str) -> None:
        self.deleted.append(attempt_id)

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

    def begin_generation_rebuild(self, authority: GenerationRebuildAuthority) -> str:
        assert authority == self.authority
        return self.operation_id

    def fail_recovery_operation(
        self,
        operation_id: str,
        failure_code: str,
        projection_identity: SearchIndexIdentity | None = None,
    ) -> None:
        self.failed_operations.append((operation_id, failure_code, projection_identity))

    def swap_generation_projection(
        self,
        *,
        authority: GenerationRebuildAuthority,
        rebuilt_identity: SearchIndexIdentity,
        attestation: KnowledgeProjectionAttestation,
    ) -> None:
        self.swapped = (rebuilt_identity, attestation)


class _RecoveryIndex:
    def __init__(self) -> None:
        self.fail_delete: set[str] = set()
        self.deleted: list[str] = []
        self.repaired: list[str] = []
        self.rebuilt_documents: tuple[Any, ...] = ()

    def delete_attempt_projection(self, orphan: OrphanProjection) -> None:
        if orphan.attempt_id in self.fail_delete:
            raise RuntimeError("interrupted cleanup")
        self.deleted.append(orphan.attempt_id)

    def rebuild_generation(
        self,
        authority: GenerationRebuildAuthority,
        *,
        operation_id: str,
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
        )
        return identity, ProjectionValidationEvidence(
            publication_attempt_id=operation_id,
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
        OrphanProjection(attempt_id="failed-1", source_id="source-1", identity=identity),
        OrphanProjection(attempt_id="active-1", source_id="source-1", identity=identity),
    ]
    repository.referenced.add("active-1")
    report = service.reconcile_orphans(source_id="source-1")
    assert report.dry_run is True
    assert report.refused_attempt_ids == ()
    assert not index.deleted
    applied = service.reconcile_orphans(source_id="source-1", apply=True)
    assert applied.deleted_attempt_ids == ("failed-1", "active-1")
    assert index.deleted == ["failed-1"]
    assert index.repaired == ["active-1"]
    assert repository.swapped is not None


def test_interrupted_cleanup_is_recorded_for_retry(tmp_path: Any) -> None:
    service, repository, index = _fixture(tmp_path)
    orphan = OrphanProjection(
        attempt_id="failed-1",
        source_id="source-1",
        identity=repository.authority.current_identity,
    )
    repository.orphans = [orphan]
    index.fail_delete.add(orphan.attempt_id)
    report = service.reconcile_orphans(source_id="source-1", apply=True)
    assert report.retry_attempt_ids == ("failed-1",)
    assert repository.retries == ["failed-1"]


def test_generation_rebuild_uses_exact_artifacts_fresh_uuid_and_same_coverage(
    tmp_path: Any,
) -> None:
    service, repository, _ = _fixture(tmp_path)
    rebuilt = service.rebuild_generation(source_id="source-1", generation_id="generation-1")
    assert rebuilt.index_uuid == "fresh-index-uuid"
    assert rebuilt.manifest_root_sha256 == repository.authority.manifest_root.root_sha256
    assert rebuilt.covered_publication_sequences == (1,)
    assert rebuilt.parent_attestation_sha256 == (
        repository.authority.current_attestation.attestation_sha256
    )
    assert repository.swapped is not None


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
