from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.metadata_import_jobs import (
    MetadataImportJob,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.capabilities.persistence.postgres.metadata_import_repository import (
    MetadataImportClaimRejectedError,
    PostgresMetadataImportRepository,
)
from proof_agent.contracts import (
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    KnowledgeSourceOperation,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _original_ref(*, media_type: str, suffix: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent-test/metadata-workbooks/{'a' * 64}/{suffix}",
        version_id=f"version-{suffix}",
        sha256="a" * 64,
        size_bytes=128,
        media_type=media_type,
    )


def _seed_candidate(
    bundle: PostgresPersistenceBundle,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
    now: datetime,
) -> None:
    bundle.knowledge.save_source(
        KnowledgeSource(
            source_id=source_id,
            name="Insurance clauses",
            provider="hybrid_index",
            lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
            params={},
            source_draft_version_id=str(uuid4()),
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
        ),
        expected_revision=0,
    )
    request = HybridArtifactBuildRequest(
        job_id=str(uuid4()),
        request_identity=f"{source_id}:{document_id}:{revision_id}",
        source_id=source_id,
        document_id=document_id,
        revision_id=revision_id,
        original_ref=_original_ref(media_type="application/pdf", suffix="original.pdf"),
        page_numbers=(1,),
        parser_revision="parser-v1",
        model_digests=("sha256:model-v1",),
        configuration_sha256="b" * 64,
    )
    bundle.hybrid_ingestion.enqueue(
        request.model_copy(
            update={"request_sha256": hybrid_build_request_sha256(request)}
        )
    )


def _seed_operation(
    bundle: PostgresPersistenceBundle,
    job: MetadataImportJob,
) -> None:
    timestamp = job.created_at.isoformat().replace("+00:00", "Z")
    bundle.knowledge_source_operations.save(
        KnowledgeSourceOperation(
            operation_id=job.operation_id,
            source_id=job.source_id,
            command="import_metadata",
            status="queued",
            stage="metadata_import_queued",
            source_revision=job.source_revision,
            poll_after_ms=1_000,
            created_at=timestamp,
            updated_at=timestamp,
        )
    )


def test_pg_metadata_import_claim_completion_and_stale_fence(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    now = datetime(2026, 7, 27, 8, 0, tzinfo=UTC)
    current = [now]
    repository = PostgresMetadataImportRepository(
        bundle.engine,
        clock=lambda: current[0],
    )
    source_id = f"hybrid-{uuid4()}"
    document_id = str(uuid4())
    revision_id = str(uuid4())
    try:
        _seed_candidate(
            bundle,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            now=now,
        )
        job = MetadataImportJob(
            import_job_id=str(uuid4()),
            operation_id=f"ksop_{uuid4().hex}",
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            source_revision=2,
            request_sha256="c" * 64,
            filename="metadata.xlsx",
            original_ref=_original_ref(
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                suffix="original.xlsx",
            ),
            content_sha256="a" * 64,
            state="READY",
            fencing_token=0,
            created_by="operator-1",
            created_at=now,
            updated_at=now,
        )

        _seed_operation(bundle, job)
        assert repository.enqueue(job) == job
        first = repository.claim_next(worker_id="knowledge-worker-1", lease_seconds=30)
        assert first is not None
        assert first.fencing_token == 1

        current[0] = now + timedelta(seconds=31)
        second = repository.claim_next(worker_id="knowledge-worker-2", lease_seconds=30)
        assert second is not None
        assert second.import_job_id == job.import_job_id
        assert second.fencing_token == 2
        with pytest.raises(MetadataImportClaimRejectedError):
            repository.complete(
                first,
                result_import_id="metadata_import_stale",
            )

        completed = repository.complete(
            second,
            result_import_id="metadata_import_exact",
        )
        assert completed.state == "COMPLETED"
        assert completed.result_import_id == "metadata_import_exact"
        assert repository.claim_next(
            worker_id="knowledge-worker-3",
            lease_seconds=30,
        ) is None
    finally:
        bundle.close()


def test_pg_metadata_import_failure_is_terminal(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    now = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    repository = PostgresMetadataImportRepository(bundle.engine, clock=lambda: now)
    source_id = f"hybrid-{uuid4()}"
    document_id = str(uuid4())
    revision_id = str(uuid4())
    try:
        _seed_candidate(
            bundle,
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            now=now,
        )
        job = MetadataImportJob(
            import_job_id=str(uuid4()),
            operation_id=f"ksop_{uuid4().hex}",
            source_id=source_id,
            document_id=document_id,
            revision_id=revision_id,
            source_revision=2,
            request_sha256="d" * 64,
            filename="metadata.xlsx",
            original_ref=_original_ref(
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                suffix="original.xlsx",
            ),
            content_sha256="a" * 64,
            state="READY",
            fencing_token=0,
            created_by="operator-1",
            created_at=now,
            updated_at=now,
        )
        _seed_operation(bundle, job)
        repository.enqueue(job)
        claim = repository.claim_next(worker_id="knowledge-worker-1", lease_seconds=30)
        assert claim is not None

        failed = repository.fail(
            claim,
            failure_code="metadata_workbook_unsafe",
            safe_reason="The metadata workbook failed controlled validation.",
        )

        assert failed.state == "FAILED"
        assert failed.failure_code == "metadata_workbook_unsafe"
        assert failed.safe_reason == (
            "The metadata workbook failed controlled validation."
        )
    finally:
        bundle.close()
