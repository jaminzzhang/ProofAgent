from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from typing import BinaryIO
from uuid import uuid4

from pypdf import PdfWriter
import pytest
import sqlalchemy as sa

from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridPrivateParserBuildConfig,
    HybridVendorArtifactRef,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import AuditActorFacts
from proof_agent.contracts.hybrid_documents import StructuredArtifactBuildIdentity
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts.ports.knowledge_source_operations import (
    KnowledgeSourceIdempotencyConflictError,
)
from proof_agent.control.knowledge.application import (
    KnowledgeSourceRevisionConflictError,
)
from proof_agent.control.knowledge.production_intake import (
    ProductionHybridKnowledgeIntakeService,
    hybrid_knowledge_source_provider_capability,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def test_v1_metadata_import_command_is_absent_after_v2_cutover() -> None:
    assert not hasattr(ProductionHybridKnowledgeIntakeService, "import_metadata")
    features = hybrid_knowledge_source_provider_capability().features
    assert "metadata_workbook_v2" in features
    assert "metadata_imports" not in features


class _ExactArtifactStore:
    def __init__(self) -> None:
        self.by_key: dict[str, tuple[bytes, ExactArtifactRef]] = {}
        self.calls: list[str] = []

    def put_immutable_stream(
        self,
        *,
        key: str,
        content: BinaryIO,
        media_type: str,
        expected_sha256: str,
        expected_size_bytes: int,
    ) -> ExactArtifactRef:
        body = content.read()
        assert hashlib.sha256(body).hexdigest() == expected_sha256
        assert len(body) == expected_size_bytes
        self.calls.append(key)
        existing = self.by_key.get(key)
        if existing is not None:
            assert existing[0] == body
            return existing[1]
        ref = ExactArtifactRef(
            artifact_uri=f"s3://proof-agent/{key}",
            version_id=f"opaque-version-{len(self.by_key) + 1}",
            sha256=expected_sha256,
            size_bytes=expected_size_bytes,
            media_type=media_type,
        )
        self.by_key[key] = body, ref
        return ref


def _pdf(*, width: int) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=792)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _artifact_ref(label: str, media_type: str) -> ExactArtifactRef:
    payload = label.encode()
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/hybrid/{label}",
        version_id=f"version-{label}",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type=media_type,
    )


def _build_result(
    build_request: HybridArtifactBuildRequest,
) -> HybridArtifactBuildResult:
    identity = StructuredArtifactBuildIdentity(
        build_id=f"build-{build_request.revision_id}",
        source_sha256=build_request.original_ref.sha256,
        parser_adapter="docling",
        parser_revision=build_request.parser_revision,
        model_digests=build_request.model_digests,
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=build_request.configuration_sha256,
    )
    identity_bytes = json.dumps(
        identity.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode(
        "utf-8"
    )
    return HybridArtifactBuildResult(
        job_id=build_request.job_id,
        request_identity=build_request.request_identity,
        source_id=build_request.source_id,
        document_id=build_request.document_id,
        revision_id=build_request.revision_id,
        build_id=identity.build_id,
        build_identity=identity,
        original_ref=build_request.original_ref,
        persisted_original_ref=build_request.original_ref,
        vendor_refs=(
            HybridVendorArtifactRef(
                adapter="docling",
                ref=_artifact_ref("vendor", "application/json"),
            ),
        ),
        canonical_ref=_artifact_ref("canonical", "application/json"),
        preview_ref=_artifact_ref("preview", "text/markdown"),
        build_identity_ref=ExactArtifactRef(
            artifact_uri="s3://proof-agent/hybrid/build-identity",
            version_id="version-build-identity",
            sha256=hashlib.sha256(identity_bytes).hexdigest(),
            size_bytes=len(identity_bytes),
            media_type="application/json",
        ),
        insurance_metadata_ref=_artifact_ref(
            "insurance-metadata",
            "application/json",
        ),
    )


def test_v1_upload_replays_before_cas_and_rejects_mismatch_and_stale_revision(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = _ExactArtifactStore()
    now = datetime(2026, 7, 27, 2, tzinfo=UTC)
    service = ProductionHybridKnowledgeIntakeService(
        knowledge=bundle.knowledge,
        ingestion=bundle.hybrid_ingestion,
        unit_of_work_factory=bundle.configuration_uow,
        artifact_store=store,
        build_config=HybridPrivateParserBuildConfig(
            parser_revision="private-parser-v1",
            model_digests=("sha256:model-v1",),
            configuration_sha256="b" * 64,
        ),
        clock=lambda: now,
    )
    actor = AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id=str(uuid4()),
        permissions=("knowledge_source.edit",),
    )
    source_id = f"ks_{uuid4().hex}"
    try:
        service.create_source(
            source_id=source_id,
            name="Insurance terms",
            params={},
            actor=actor,
        )
        content = _pdf(width=612)

        admitted = service.upload_document(
            source_id=source_id,
            filename="terms.pdf",
            content_type="application/pdf",
            content=BytesIO(content),
            expected_revision=1,
            idempotency_key="upload-request-1",
            actor=actor,
        )
        replayed = service.upload_document(
            source_id=source_id,
            filename="terms.pdf",
            content_type="application/pdf",
            content=BytesIO(content),
            expected_revision=1,
            idempotency_key="upload-request-1",
            actor=actor,
        )

        assert admitted.source_revision == 2
        assert replayed == admitted
        assert bundle.knowledge_source_operations.get(admitted.operation_id) == admitted
        records = bundle.hybrid_ingestion.list_records_for_source(source_id)
        assert len(records) == 1
        candidate = bundle.hybrid_ingestion.get_document_candidate(
            source_id=source_id,
            document_id=records[0].build_request.document_id,
        )
        assert candidate is not None
        assert candidate.candidate_revision_id is None
        assert candidate.pending_revision_id == records[0].build_request.revision_id
        assert bundle.knowledge.get_source_record(source_id).revision == 2
        assert len(store.by_key) == 1

        with pytest.raises(KnowledgeSourceIdempotencyConflictError):
            service.upload_document(
                source_id=source_id,
                filename="terms.pdf",
                content_type="application/pdf",
                content=BytesIO(_pdf(width=613)),
                expected_revision=1,
                idempotency_key="upload-request-1",
                actor=actor,
            )
        with pytest.raises(KnowledgeSourceRevisionConflictError) as conflict:
            service.upload_document(
                source_id=source_id,
                filename="terms.pdf",
                content_type="application/pdf",
                content=BytesIO(content),
                expected_revision=1,
                idempotency_key="upload-request-stale",
                actor=actor,
            )

        assert conflict.value.current_revision == 2
        assert len(bundle.hybrid_ingestion.list_records_for_source(source_id)) == 1
        assert bundle.knowledge.get_source_record(source_id).revision == 2

        draft_id = bundle.knowledge.get_knowledge_source(
            source_id
        ).source_draft_version_id
        job_id = records[0].build_request.job_id
        cancelled = service.cancel_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=2,
            idempotency_key="cancel-request-1",
            actor=actor,
        )
        cancelled_replay = service.cancel_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=2,
            idempotency_key="cancel-request-1",
            actor=actor,
        )
        assert cancelled.source_revision == 3
        assert cancelled_replay == cancelled
        assert bundle.hybrid_ingestion.get(job_id).state == "CANCELLED"
        assert bundle.knowledge.get_source_record(source_id).revision == 3

        retried = service.retry_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=3,
            idempotency_key="retry-request-1",
            actor=actor,
        )
        retried_replay = service.retry_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=3,
            idempotency_key="retry-request-1",
            actor=actor,
        )
        assert retried.source_revision == 4
        assert retried_replay == retried
        assert bundle.hybrid_ingestion.get(job_id).state == "READY"
        assert bundle.knowledge.get_source_record(source_id).revision == 4

        claim = bundle.hybrid_ingestion.claim_next(
            worker_id="worker-1",
            lease_seconds=30,
        )
        assert claim is not None
        assert bundle.knowledge.get_source_record(source_id).revision == 5
        claimed_cancel = service.cancel_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=5,
            idempotency_key="claimed-cancel-request-1",
            actor=actor,
        )
        claimed_cancel_replay = service.cancel_ingestion(
            source_id=source_id,
            job_id=job_id,
            expected_revision=5,
            idempotency_key="claimed-cancel-request-1",
            actor=actor,
        )
        assert claimed_cancel.source_revision == 6
        assert claimed_cancel_replay == claimed_cancel
        assert bundle.hybrid_ingestion.get(job_id).state == "CANCEL_REQUESTED"
        bundle.hybrid_ingestion.acknowledge_cancellation(claim)
        assert bundle.hybrid_ingestion.get(job_id).state == "CANCELLED"
        assert bundle.knowledge.get_source_record(source_id).revision == 7
        assert bundle.knowledge.get_knowledge_source(
            source_id
        ).source_draft_version_id == draft_id
        assert [
            item.state
            for item in bundle.knowledge_ingestion_attempts.list_for_job(job_id)
        ] == ["cancelled"]
    finally:
        bundle.close()


def test_v1_upload_operation_tracks_worker_failure_to_terminal_state(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    now = datetime(2026, 7, 28, 2, tzinfo=UTC)
    service = ProductionHybridKnowledgeIntakeService(
        knowledge=bundle.knowledge,
        ingestion=bundle.hybrid_ingestion,
        unit_of_work_factory=bundle.configuration_uow,
        artifact_store=_ExactArtifactStore(),
        build_config=HybridPrivateParserBuildConfig(
            parser_revision="private-parser-v1",
            model_digests=("sha256:model-v1",),
            configuration_sha256="b" * 64,
        ),
        clock=lambda: now,
    )
    actor = AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id=str(uuid4()),
        permissions=("knowledge_source.edit",),
    )
    source_id = f"ks_{uuid4().hex}"
    try:
        service.create_source(
            source_id=source_id,
            name="Insurance terms",
            params={},
            actor=actor,
        )
        operation = service.upload_document(
            source_id=source_id,
            filename="terms.pdf",
            content_type="application/pdf",
            content=BytesIO(_pdf(width=612)),
            expected_revision=1,
            idempotency_key="upload-terminal-1",
            actor=actor,
        )
        record = bundle.hybrid_ingestion.list_records_for_source(source_id)[0]
        with bundle.engine.connect() as connection:
            linked_operation_id = connection.execute(
                sa.text(
                    "SELECT operation_id FROM hybrid_ingestion_jobs WHERE job_id=:job_id"
                ),
                {"job_id": record.build_request.job_id},
            ).scalar_one()
        assert linked_operation_id == operation.operation_id

        claim = bundle.hybrid_ingestion.claim_next(
            worker_id="worker-1",
            lease_seconds=30,
        )
        assert claim is not None
        assert bundle.knowledge_source_operations.get(operation.operation_id).status == "running"

        bundle.hybrid_ingestion.fail_integrity(
            claim,
            failure_code="PA_HYBRID_WORKER_INTEGRITY",
            safe_reason="Hybrid artifact build failed deterministic integrity validation.",
        )

        failed = bundle.knowledge_source_operations.get(operation.operation_id)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.stage == "ingestion_failed"
        assert failed.outcome_code == "hybrid_ingestion_integrity_failed"
        assert failed.completed_at is not None
    finally:
        bundle.close()
