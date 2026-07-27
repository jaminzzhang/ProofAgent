from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridVendorArtifactRef,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.capabilities.persistence.postgres.hybrid_ingestion_repository import (
    HybridIngestionClaimRejectedError,
    HybridIngestionRetryRejectedError,
    PostgresHybridIngestionRepository,
)
from proof_agent.contracts import KnowledgeSource, KnowledgeSourceLifecycleState
from proof_agent.contracts.hybrid_documents import StructuredArtifactBuildIdentity
from proof_agent.contracts.knowledge_index import ExactArtifactRef


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _request(
    source_id: str,
    *,
    document_id: str | None = None,
) -> HybridArtifactBuildRequest:
    request = HybridArtifactBuildRequest(
        job_id=str(uuid4()),
        request_identity=f"{source_id}:document:revision",
        source_id=source_id,
        document_id=document_id or str(uuid4()),
        revision_id=str(uuid4()),
        original_ref=ExactArtifactRef(
            artifact_uri="s3://proof-agent/hybrid/original.pdf",
            version_id="opaque-s3-version-id",
            sha256="a" * 64,
            size_bytes=1024,
            media_type="application/pdf",
        ),
        page_numbers=(1, 2),
        parser_revision="parser-v1",
        model_digests=("sha256:model-v1",),
        configuration_sha256="b" * 64,
    )
    return request.model_copy(
        update={"request_sha256": hybrid_build_request_sha256(request)}
    )


def _artifact_ref(label: str, media_type: str) -> ExactArtifactRef:
    payload = label.encode()
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/hybrid/{label}",
        version_id=f"version-{label}",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        media_type=media_type,
    )


def _result(request: HybridArtifactBuildRequest) -> HybridArtifactBuildResult:
    identity = StructuredArtifactBuildIdentity(
        build_id=f"build-{request.revision_id}",
        source_sha256=request.original_ref.sha256,
        parser_adapter="docling",
        parser_revision=request.parser_revision,
        model_digests=request.model_digests,
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=request.configuration_sha256,
    )
    identity_bytes = json.dumps(
        identity.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    return HybridArtifactBuildResult(
        job_id=request.job_id,
        request_identity=request.request_identity,
        source_id=request.source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        build_id=identity.build_id,
        build_identity=identity,
        original_ref=request.original_ref,
        persisted_original_ref=request.original_ref.model_copy(
            update={"artifact_uri": "s3://proof-agent/persisted/original.pdf"}
        ),
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


def test_pg_hybrid_ingestion_claim_retry_and_fencing(postgres_dsn: str) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 15, tzinfo=UTC)
    current = [now]
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: current[0],
    )
    try:
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
        request = _request(source_id)
        admitted = repository.enqueue(request)
        assert admitted.state == "READY"

        first = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert first is not None
        assert first.fencing_token == 1
        renewed = repository.renew_claim(first, lease_seconds=30)
        assert renewed.lease_expires_at == now + timedelta(seconds=30)
        retried = repository.schedule_retry(
            renewed,
            auto_retry_count=1,
            safe_error="Temporary parser failure.",
        )
        assert retried.state == "RETRY_SCHEDULED"

        current[0] = now + timedelta(seconds=6)
        second = repository.claim_next(worker_id="worker-2", lease_seconds=30)
        assert second is not None
        assert second.fencing_token == 2
        assert repository.load_build_request(second).auto_retry_count == 1
        with pytest.raises(HybridIngestionClaimRejectedError):
            repository.require_review(first, safe_reason="stale owner")
        reviewed = repository.require_review(
            second,
            safe_reason="Structured document requires operator review.",
        )
        assert reviewed.state == "REVIEW_REQUIRED"
    finally:
        bundle.close()


def test_pg_claimed_hybrid_ingestion_persists_fenced_cancel_request(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 27, tzinfo=UTC)
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: now,
    )
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Cancellation fencing",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=str(uuid4()),
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        admitted = repository.enqueue(_request(source_id))
        claim = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert claim is not None

        cancelled = repository.request_cancel(
            job_id=admitted.request.job_id,
            requested_by="operator-1",
        )

        assert cancelled.state == "CANCEL_REQUESTED"
        assert cancelled.cancel_requested_by == "operator-1"
        assert cancelled.cancel_requested_at == now
        assert repository.cancellation_requested(claim) is True
        acknowledged = repository.acknowledge_cancellation(claim)
        assert acknowledged.state == "CANCELLED"
        attempts = bundle.knowledge_ingestion_attempts.list_for_job(
            admitted.request.job_id
        )
        assert len(attempts) == 1
        assert attempts[0].state == "cancelled"
        with pytest.raises(HybridIngestionClaimRejectedError):
            repository.require_review(claim, safe_reason="late worker result")
    finally:
        bundle.close()


def test_pg_ready_cancellation_is_immediate_without_execution_attempt(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 27, tzinfo=UTC)
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: now,
    )
    draft_id = str(uuid4())
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Immediate cancellation",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=draft_id,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        admitted = repository.enqueue(_request(source_id))

        cancelled = repository.request_cancel(
            job_id=admitted.request.job_id,
            requested_by="operator-1",
        )

        assert cancelled.state == "CANCELLED"
        assert cancelled.fencing_token == 0
        assert (
            bundle.knowledge_ingestion_attempts.list_for_job(
                admitted.request.job_id
            )
            == ()
        )
        assert bundle.knowledge.get_knowledge_source(
            source_id
        ).source_draft_version_id == draft_id
        assert bundle.knowledge.get_source_record(source_id).revision == 2
    finally:
        bundle.close()


def test_pg_attempts_cover_two_automatic_retries_and_one_manual_retry(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 27, tzinfo=UTC)
    current = [now]
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: current[0],
    )
    draft_id = str(uuid4())
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Attempt lifecycle",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=draft_id,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        request = _request(source_id)
        repository.enqueue(request)

        first = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert first is not None
        repository.schedule_retry(
            first,
            auto_retry_count=1,
            safe_error="Temporary parser failure.",
        )
        current[0] += timedelta(seconds=6)
        second = repository.claim_next(worker_id="worker-2", lease_seconds=30)
        assert second is not None
        repository.schedule_retry(
            second,
            auto_retry_count=2,
            safe_error="Temporary parser failure.",
        )
        current[0] += timedelta(seconds=6)
        third = repository.claim_next(worker_id="worker-3", lease_seconds=30)
        assert third is not None
        repository.fail_retries_exhausted(
            third,
            failure_code="PA_HYBRID_RETRY_EXHAUSTED",
            safe_reason="Private parser service retry limit reached.",
        )

        automatic = bundle.knowledge_ingestion_attempts.list_for_job(request.job_id)
        assert [item.attempt_number for item in automatic] == [1, 2, 3]
        assert [item.initiation for item in automatic] == [
            "automatic",
            "automatic",
            "automatic",
        ]
        assert [item.state for item in automatic] == ["failed", "failed", "failed"]
        assert automatic[-1].failure_classification == "recoverable_exhausted"
        assert bundle.knowledge.get_knowledge_source(
            source_id
        ).source_draft_version_id == draft_id

        retried = repository.manual_retry(
            job_id=request.job_id,
            requested_by="operator-1",
        )
        assert retried.state == "READY"
        manual = repository.claim_next(worker_id="worker-4", lease_seconds=30)
        assert manual is not None
        attempts = bundle.knowledge_ingestion_attempts.list_for_job(request.job_id)
        assert len(attempts) == 4
        assert attempts[-1].attempt_number == 4
        assert attempts[-1].initiation == "manual"
        assert attempts[-1].state == "running"
        with pytest.raises(HybridIngestionRetryRejectedError):
            repository.manual_retry(
                job_id=request.job_id,
                requested_by="operator-1",
            )
        assert bundle.knowledge.get_knowledge_source(
            source_id
        ).source_draft_version_id == draft_id
        assert bundle.knowledge.get_source_record(source_id).revision > 1
    finally:
        bundle.close()


def test_pg_replacement_preserves_candidate_until_new_revision_completes(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    source_id = f"hybrid-{uuid4()}"
    now = datetime(2026, 7, 27, tzinfo=UTC)
    repository = PostgresHybridIngestionRepository(
        bundle.engine,
        clock=lambda: now,
    )
    initial_draft_id = str(uuid4())
    try:
        bundle.knowledge.save_source(
            KnowledgeSource(
                source_id=source_id,
                name="Replacement candidate",
                provider="hybrid_index",
                lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
                params={},
                source_draft_version_id=initial_draft_id,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            ),
            expected_revision=0,
        )
        first = _request(source_id)
        repository.enqueue(first)

        pending_first = repository.get_document_candidate(
            source_id=source_id,
            document_id=first.document_id,
        )
        assert pending_first is not None
        assert pending_first.candidate_revision_id is None
        assert pending_first.pending_revision_id == first.revision_id

        first_claim = repository.claim_next(worker_id="worker-1", lease_seconds=30)
        assert first_claim is not None
        repository.commit_artifact_build(first_claim, _result(first))

        selected_first = repository.get_document_candidate(
            source_id=source_id,
            document_id=first.document_id,
        )
        assert selected_first is not None
        assert selected_first.candidate_revision_id == first.revision_id
        assert selected_first.pending_revision_id is None
        selected_draft_id = (
            bundle.knowledge.get_knowledge_source(source_id).source_draft_version_id
        )
        assert selected_draft_id != initial_draft_id

        replacement = _request(source_id, document_id=first.document_id)
        repository.enqueue(replacement, replacement=True)
        pending_replacement = repository.get_document_candidate(
            source_id=source_id,
            document_id=first.document_id,
        )
        assert pending_replacement is not None
        assert pending_replacement.candidate_revision_id == first.revision_id
        assert pending_replacement.pending_revision_id == replacement.revision_id
        assert (
            bundle.knowledge.get_knowledge_source(source_id).source_draft_version_id
            == selected_draft_id
        )

        replacement_claim = repository.claim_next(
            worker_id="worker-2",
            lease_seconds=30,
        )
        assert replacement_claim is not None
        repository.fail_integrity(
            replacement_claim,
            failure_code="PA_HYBRID_INTEGRITY_001",
            safe_reason="Replacement failed integrity checks.",
        )

        failed_replacement = repository.get_document_candidate(
            source_id=source_id,
            document_id=first.document_id,
        )
        assert failed_replacement is not None
        assert failed_replacement.candidate_revision_id == first.revision_id
        assert failed_replacement.pending_revision_id is None
        assert [
            item.build_request.revision_id
            for item in repository.list_candidate_records_for_source(source_id)
        ] == [first.revision_id]
        assert (
            bundle.knowledge.get_knowledge_source(source_id).source_draft_version_id
            == selected_draft_id
        )
    finally:
        bundle.close()
