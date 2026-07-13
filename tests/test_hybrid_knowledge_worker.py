from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Literal

import pytest

from proof_agent.capabilities.knowledge.hybrid.ports import HybridKnowledgeJobClaim
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridKnowledgeWorker,
    HybridParserBuildOutput,
    HybridVendorArtifact,
    HybridWorkerOutcome,
    ReviewRequiredError,
    TransientKnowledgeServiceError,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import KnowledgeWorkerTaskClaim
from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeWorkerTaskOutcome,
    dispatch_claimed_knowledge_task,
)
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
    StructuredQualitySignal,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
    HybridKnowledgeLeaseError,
)


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _ref(content: bytes, *, media_type: str = "application/pdf") -> ExactArtifactRef:
    digest = hashlib.sha256(content).hexdigest()
    return ExactArtifactRef(
        artifact_uri=f"s3://private-originals/{digest}.pdf",
        version_id=f"sha256:{digest}",
        sha256=digest,
        size_bytes=len(content),
        media_type=media_type,
    )


def _build_request(original: bytes = b"%PDF-1.7\n") -> HybridArtifactBuildRequest:
    request = HybridArtifactBuildRequest(
        job_id="job_1",
        request_identity="request_1",
        source_id="source_1",
        document_id="document_1",
        revision_id="revision_1",
        original_ref=_ref(original),
        page_numbers=(1,),
        parser_revision="docling@2.112.0",
        model_digests=("sha256:model",),
        configuration_sha256="b" * 64,
        auto_retry_count=0,
        max_auto_retries=2,
    )
    return request.model_copy(update={"request_sha256": hybrid_build_request_sha256(request)})


def _artifact(request: HybridArtifactBuildRequest) -> StructuredKnowledgeDocumentArtifact:
    build = StructuredArtifactBuildIdentity(
        build_id="build_1",
        source_sha256=request.original_ref.sha256,
        parser_adapter="docling",
        parser_revision=request.parser_revision,
        model_digests=request.model_digests,
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=request.configuration_sha256,
    )
    return StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id=request.document_id,
        revision_id=request.revision_id,
        original_sha256=request.original_ref.sha256,
        build_identity=build,
        pages=(
            StructuredPage(
                page_number=1,
                width=612,
                height=792,
                native_text_ratio=1,
                blocks=(
                    StructuredBlock(
                        block_id="block_1",
                        kind="paragraph",
                        text="Coverage is subject to the policy terms.",
                        bbox=BoundingBox(x0=1, y0=1, x1=100, y1=20),
                        reading_order=0,
                    ),
                ),
            ),
        ),
    )


class MemoryOriginalStore:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        assert ref.sha256 == hashlib.sha256(self.content).hexdigest()
        assert ref.size_bytes == len(self.content)
        return self.content

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        raise AssertionError("final artifacts use the dedicated artifact store")


class FakePipeline:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = 0

    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        vendor = json.dumps(
            {"source_sha256": request.original_ref.sha256, "pages": [{"page_number": 1}]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return HybridParserBuildOutput(
            artifact=_artifact(request),
            vendor_artifacts=(
                HybridVendorArtifact(
                    adapter="docling",
                    content=vendor,
                    media_type="application/json",
                ),
            ),
        )


class ReviewSignalPipeline(FakePipeline):
    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        result = super().build(request)
        artifact = result.artifact.model_copy(
            update={
                "quality_signals": (
                    StructuredQualitySignal(
                        code="ambiguous_table",
                        score=0.2,
                        page_number=1,
                        requires_review=True,
                    ),
                )
            }
        )
        return result.model_copy(update={"artifact": artifact})


class FakeLifecycle:
    def __init__(self, request: HybridArtifactBuildRequest) -> None:
        self.request = request
        self.claim = HybridKnowledgeJobClaim(
            job_id=request.job_id,
            request={
                "job_id": request.job_id,
                "idempotency_key": "idempotency_1",
                "request_identity": request.request_identity,
                "request_sha256": request.request_sha256,
                "kind": "parse",
            },
            worker_id="worker_1",
            fencing_token=1,
            claimed_at=NOW,
            lease_expires_at=NOW + timedelta(seconds=60),
        )
        self.claimed = False
        self.committed: HybridArtifactBuildResult | None = None
        self.retry: tuple[int, str] | None = None
        self.review: str | None = None
        self.stale = False

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> HybridKnowledgeJobClaim | None:
        assert worker_id == "worker_1"
        assert lease_seconds == 60
        if self.claimed:
            return None
        self.claimed = True
        return self.claim

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest:
        assert claim == self.claim
        return self.request

    def commit_artifact_build(
        self, claim: HybridKnowledgeJobClaim, result: HybridArtifactBuildResult
    ) -> None:
        if self.stale:
            raise HybridKnowledgeLeaseError("stale")
        self.committed = result

    def schedule_retry(
        self, claim: HybridKnowledgeJobClaim, *, auto_retry_count: int, safe_error: str
    ) -> None:
        self.retry = (auto_retry_count, safe_error)

    def require_review(self, claim: HybridKnowledgeJobClaim, *, safe_reason: str) -> None:
        self.review = safe_reason


def _worker(
    tmp_path,
    *,
    failure: Exception | None = None,
    pipeline: FakePipeline | None = None,
):
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    lifecycle = FakeLifecycle(request)
    pipeline = pipeline or FakePipeline(failure)
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=pipeline,
        worker_id="worker_1",
        lease_seconds=60,
    )
    return worker, lifecycle, pipeline


def test_hybrid_worker_persists_and_commits_exact_build_artifacts(tmp_path) -> None:
    worker, lifecycle, _pipeline = _worker(tmp_path)

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "completed"
    assert lifecycle.committed is not None
    result = lifecycle.committed
    assert result.original_ref.sha256 == hashlib.sha256(b"%PDF-1.7\n").hexdigest()
    assert result.vendor_refs[0].adapter == "docling"
    assert result.vendor_refs[0].ref.media_type == "application/json"
    assert result.canonical_ref.media_type == "application/json"
    assert result.preview_ref.media_type == "text/markdown"
    assert result.build_identity_ref.media_type == "application/json"


def test_hybrid_worker_retries_transient_parser_failure_but_reviews_content_failure(
    tmp_path,
) -> None:
    transient_worker, transient_lifecycle, _ = _worker(
        tmp_path / "transient", failure=TransientKnowledgeServiceError("internal timeout detail")
    )
    transient = transient_worker.run_once()
    assert transient == HybridWorkerOutcome(
        job_id="job_1",
        source_id="source_1",
        state="retry_scheduled",
        auto_retry_count=1,
        error_code="PA_HYBRID_WORKER_TRANSIENT",
    )
    assert transient_lifecycle.retry == (1, "Temporary private parser service failure.")

    review_worker, review_lifecycle, _ = _worker(
        tmp_path / "review", failure=ReviewRequiredError("ambiguous table values")
    )
    review = review_worker.run_once()
    assert review is not None and review.state == "review_required"
    assert review.auto_retry_count == 0
    assert review_lifecycle.review == "Structured document requires operator review."


def test_hybrid_worker_bounds_retries_and_never_exposes_raw_service_error(tmp_path) -> None:
    worker, lifecycle, _ = _worker(
        tmp_path, failure=TransientKnowledgeServiceError("secret endpoint and token")
    )
    lifecycle.request = lifecycle.request.model_copy(update={"auto_retry_count": 2})

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert outcome.auto_retry_count == 2
    assert lifecycle.retry is None
    assert lifecycle.review == "Private parser service retry limit reached."
    assert "secret" not in repr(outcome)


def test_deterministic_quality_signal_enters_review_without_retry(tmp_path) -> None:
    worker, lifecycle, _ = _worker(tmp_path, pipeline=ReviewSignalPipeline())

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "review_required"
    assert outcome.auto_retry_count == 0
    assert lifecycle.retry is None
    assert lifecycle.review == "Structured document requires operator review."


def test_stale_fencing_can_leave_orphans_but_cannot_commit_state(tmp_path) -> None:
    worker, lifecycle, _ = _worker(tmp_path)
    lifecycle.stale = True

    with pytest.raises(HybridKnowledgeLeaseError):
        worker.run_once()

    assert lifecycle.committed is None
    assert any((tmp_path / "artifacts").rglob("canonical.json"))


def test_worker_rejects_job_payload_binding_mismatch_before_parser(tmp_path) -> None:
    worker, lifecycle, pipeline = _worker(tmp_path)
    lifecycle.request = lifecycle.request.model_copy(update={"document_id": "other_document"})

    with pytest.raises(ValueError, match="request digest"):
        worker.run_once()

    assert pipeline.calls == 0


def test_claimed_task_dispatch_never_invokes_hybrid_code_for_local_jobs() -> None:
    task = KnowledgeWorkerTaskClaim(kind="artifact_build")
    calls: list[str] = []

    def handler(name: Literal["local", "hybrid"]):
        def run(_task: KnowledgeWorkerTaskClaim) -> KnowledgeWorkerTaskOutcome:
            calls.append(name)
            return KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_1",
                source_id="source_1",
                state="ready",
            )

        return run

    local = dispatch_claimed_knowledge_task(
        provider="local_index",
        task=task,
        local_handler=handler("local"),
        hybrid_handler=handler("hybrid"),
    )
    assert local.state == "ready"
    assert calls == ["local"]

    calls.clear()
    hybrid = dispatch_claimed_knowledge_task(
        provider="hybrid_index",
        task=task,
        local_handler=handler("local"),
        hybrid_handler=handler("hybrid"),
    )
    assert hybrid.state == "ready"
    assert calls == ["hybrid"]
