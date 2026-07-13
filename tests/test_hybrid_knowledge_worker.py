from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Literal

import pytest

import proof_agent.capabilities.knowledge.ingestion.hybrid_worker as hybrid_worker_module

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridKnowledgeArtifactLifecycle,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobRequest,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
    HybridKnowledgeWorker,
    HybridPrivateParserBuildConfig,
    HybridParserBuildOutput,
    HybridVendorArtifact,
    HybridWorkerOutcome,
    LocalManagedOriginalStore,
    LocalStoreHybridQuarantinePromoter,
    LocalStoreHybridWorkerLifecycle,
    ReviewRequiredError,
    TransientKnowledgeServiceError,
    hybrid_build_request_sha256,
)
from proof_agent.capabilities.knowledge.hybrid.workbook import (
    FilesystemInsuranceMetadataReviewRepository,
    InsuranceMetadataDraftInput,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import (
    KnowledgeWorkerTaskClaim,
)
from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeWorkerTaskOutcome,
    LocalStoreHybridTaskHandler,
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
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft
from proof_agent.configuration.hybrid_knowledge_repository import (
    FileSystemKnowledgeArtifactStore,
    HybridKnowledgeLeaseError,
    InMemoryHybridKnowledgeRepository,
    ManualHybridClock,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.delivery.cli import create_knowledge_ingestion_worker
from proof_agent.errors import ProofAgentError
from pypdf import PdfWriter


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


def _artifact_ref(label: str, content: bytes, media_type: str) -> ExactArtifactRef:
    digest = hashlib.sha256(content).hexdigest()
    return ExactArtifactRef(
        artifact_uri=f"s3://private-artifacts/{label}/{digest}",
        version_id=f"sha256:{digest}",
        sha256=digest,
        size_bytes=len(content),
        media_type=media_type,
    )


def _build_request(
    original: bytes = b"%PDF-1.7\n", *, max_auto_retries: int = 2
) -> HybridArtifactBuildRequest:
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
        max_auto_retries=max_auto_retries,
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


def _insurance_metadata(
    request: HybridArtifactBuildRequest,
    *,
    pdf_drafts: tuple[InsuranceMetadataDraftInput, ...] = (),
) -> HybridInsuranceMetadataArtifact:
    return HybridInsuranceMetadataArtifact(
        source_id=request.source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        structured_build_id="build_1",
        original_sha256=request.original_ref.sha256,
        document_defaults=InsuranceRuleMetadataDraft(
            metadata_draft_id="metadata-defaults-1",
            document_id=request.document_id,
            revision_id=request.revision_id,
        ),
        pdf_drafts=pdf_drafts,
    )


def _build_result(request: HybridArtifactBuildRequest) -> HybridArtifactBuildResult:
    artifact = _artifact(request)
    build = artifact.build_identity
    return HybridArtifactBuildResult(
        job_id=request.job_id,
        request_identity=request.request_identity,
        source_id=request.source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        build_id=build.build_id,
        build_identity=build,
        original_ref=request.original_ref,
        persisted_original_ref=ExactArtifactRef(
            artifact_uri=f"s3://private-artifacts/original/{request.original_ref.sha256}",
            version_id=request.original_ref.version_id,
            sha256=request.original_ref.sha256,
            size_bytes=request.original_ref.size_bytes,
            media_type="application/pdf",
        ),
        vendor_refs=(
            hybrid_worker_module.HybridVendorArtifactRef(
                adapter="docling",
                ref=_artifact_ref("vendor", b"{}", "application/json"),
            ),
        ),
        canonical_ref=_artifact_ref("canonical", b"{}", "application/json"),
        preview_ref=_artifact_ref("preview", b"# preview", "text/markdown"),
        build_identity_ref=_artifact_ref(
            "build-identity",
            hybrid_worker_module._canonical_json(build.model_dump(mode="json")),
            "application/json",
        ),
        insurance_metadata_ref=_artifact_ref(
            "insurance-metadata",
            hybrid_worker_module._canonical_json(
                _insurance_metadata(request).model_dump(mode="json")
            ),
            "application/json",
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


class RecordingArtifactStore:
    def __init__(self) -> None:
        self.put_calls: list[tuple[str, int, str]] = []

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        self.put_calls.append((key, len(content), media_type))
        return _ref(content, media_type=media_type)

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        raise AssertionError("oversized output must fail before artifact reads")


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
            insurance_metadata=_insurance_metadata(request),
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


class TimeoutOncePipeline(FakePipeline):
    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        if self.calls == 0:
            self.calls += 1
            raise TransientKnowledgeServiceError("timeout")
        return super().build(request)


class AlwaysTimeoutPipeline(FakePipeline):
    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        self.calls += 1
        raise TransientKnowledgeServiceError("timeout")


class PrebuiltPipeline:
    def __init__(self, output: HybridParserBuildOutput) -> None:
        self.output = output

    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        return self.output


class LeaseExpiringPipeline(FakePipeline):
    def __init__(self, clock: ManualHybridClock) -> None:
        super().__init__()
        self.clock = clock

    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput:
        result = super().build(request)
        self.clock.advance(seconds=61)
        return result


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
        self.integrity_failure: tuple[str, str] | None = None
        self.exhausted_failure: tuple[str, str] | None = None
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

    def renew_claim(
        self, claim: HybridKnowledgeJobClaim, *, lease_seconds: int
    ) -> HybridKnowledgeJobClaim:
        return claim.model_copy(
            update={"lease_expires_at": claim.lease_expires_at + timedelta(seconds=lease_seconds)}
        )

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

    def fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> None:
        self.integrity_failure = (failure_code, safe_reason)

    def fail_retries_exhausted(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> None:
        self.exhausted_failure = (failure_code, safe_reason)


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
    assert result.insurance_metadata_ref.media_type == "application/json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "other_source"),
        ("document_id", "other_document"),
        ("revision_id", "other_revision"),
        ("structured_build_id", "other_build"),
        ("original_sha256", "f" * 64),
    ],
)
def test_hybrid_worker_rejects_insurance_metadata_lineage_mismatch(
    tmp_path, field: str, value: str
) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    parsed = FakePipeline().build(request)
    mismatched = parsed.insurance_metadata.model_copy(update={field: value})
    pipeline = PrebuiltPipeline(parsed.model_copy(update={"insurance_metadata": mismatched}))
    lifecycle = FakeLifecycle(request)
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=pipeline,
        worker_id="worker_1",
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert lifecycle.committed is None


def test_hybrid_worker_rejects_pdf_metadata_for_unknown_rule_anchor(tmp_path) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    unknown = InsuranceMetadataDraftInput(
        metadata_draft_id="pdf-unknown",
        origin="pdf",
        source_id=request.source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        canonical_anchor="unknown-anchor",
    )
    parsed = FakePipeline().build(request)
    metadata = _insurance_metadata(request, pdf_drafts=(unknown,))
    pipeline = PrebuiltPipeline(parsed.model_copy(update={"insurance_metadata": metadata}))
    lifecycle = FakeLifecycle(request)
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=pipeline,
        worker_id="worker_1",
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert lifecycle.committed is None


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
    assert lifecycle.exhausted_failure == (
        "PA_HYBRID_WORKER_RETRY_EXHAUSTED",
        "Private parser service retry limit reached.",
    )
    assert "secret" not in repr(outcome)


@pytest.mark.parametrize(
    "limit_name",
    ["MAX_HYBRID_VENDOR_ARTIFACT_BYTES", "MAX_HYBRID_VENDOR_AGGREGATE_BYTES"],
)
def test_hybrid_worker_rejects_oversized_vendor_output_before_any_artifact_write(
    tmp_path, monkeypatch, limit_name: str
) -> None:
    monkeypatch.setattr(hybrid_worker_module, limit_name, 1)
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    lifecycle = FakeLifecycle(request)
    artifacts = RecordingArtifactStore()
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=MemoryOriginalStore(original),
        artifact_store=artifacts,
        pipeline=FakePipeline(),
        worker_id="worker_1",
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert lifecycle.integrity_failure == (
        "PA_HYBRID_WORKER_INTEGRITY",
        "Hybrid artifact build failed deterministic integrity validation.",
    )
    assert artifacts.put_calls == []


def test_hybrid_worker_rechecks_resource_envelope_immediately_before_persistence(
    tmp_path, monkeypatch
) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    parsed = FakePipeline().build(request)
    monkeypatch.setattr(hybrid_worker_module, "MAX_HYBRID_VENDOR_AGGREGATE_BYTES", 1)
    lifecycle = FakeLifecycle(request)
    artifacts = RecordingArtifactStore()
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=MemoryOriginalStore(original),
        artifact_store=artifacts,
        pipeline=PrebuiltPipeline(parsed),
        worker_id="worker_1",
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert lifecycle.integrity_failure is not None
    assert artifacts.put_calls == []


def test_hybrid_parser_resource_envelope_accepts_exact_documented_boundaries() -> None:
    envelope = hybrid_worker_module.HybridParserResourceEnvelope(
        vendor_artifact_bytes=(
            hybrid_worker_module.MAX_HYBRID_VENDOR_ARTIFACT_BYTES,
            hybrid_worker_module.MAX_HYBRID_VENDOR_ARTIFACT_BYTES,
        ),
        aggregate_vendor_bytes=hybrid_worker_module.MAX_HYBRID_VENDOR_AGGREGATE_BYTES,
        canonical_json_bytes=hybrid_worker_module.MAX_HYBRID_CANONICAL_BYTES,
        preview_bytes=hybrid_worker_module.MAX_HYBRID_PREVIEW_BYTES,
        build_identity_bytes=hybrid_worker_module.MAX_HYBRID_BUILD_IDENTITY_BYTES,
        insurance_metadata_bytes=hybrid_worker_module.MAX_HYBRID_CANONICAL_BYTES,
        total_artifact_count=hybrid_worker_module.MAX_HYBRID_OUTPUT_ARTIFACT_COUNT,
        total_artifact_bytes=hybrid_worker_module.MAX_HYBRID_OUTPUT_BYTES,
    )

    hybrid_worker_module._require_parser_output_within_limits(envelope)


@pytest.mark.parametrize(
    ("field", "limit_name"),
    [
        ("aggregate_vendor_bytes", "MAX_HYBRID_VENDOR_AGGREGATE_BYTES"),
        ("canonical_json_bytes", "MAX_HYBRID_CANONICAL_BYTES"),
        ("preview_bytes", "MAX_HYBRID_PREVIEW_BYTES"),
        ("build_identity_bytes", "MAX_HYBRID_BUILD_IDENTITY_BYTES"),
        ("insurance_metadata_bytes", "MAX_HYBRID_CANONICAL_BYTES"),
        ("total_artifact_count", "MAX_HYBRID_OUTPUT_ARTIFACT_COUNT"),
        ("total_artifact_bytes", "MAX_HYBRID_OUTPUT_BYTES"),
    ],
)
def test_hybrid_parser_resource_envelope_rejects_one_over_each_boundary(
    field: str, limit_name: str
) -> None:
    envelope = hybrid_worker_module.HybridParserResourceEnvelope(
        vendor_artifact_bytes=(1,),
        aggregate_vendor_bytes=1,
        canonical_json_bytes=1,
        preview_bytes=1,
        build_identity_bytes=1,
        insurance_metadata_bytes=1,
        total_artifact_count=5,
        total_artifact_bytes=5,
    )
    oversized = envelope.model_copy(
        update={field: getattr(hybrid_worker_module, limit_name) + 1}
    )

    with pytest.raises(ValueError, match="exceed"):
        hybrid_worker_module._require_parser_output_within_limits(oversized)


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

    outcome = worker.run_once()

    assert outcome is not None and outcome.state == "failed"
    assert outcome.error_code == "PA_HYBRID_WORKER_INTEGRITY"
    assert lifecycle.integrity_failure is not None
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


def test_real_repository_persists_retry_and_recovers_with_next_fence(tmp_path) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    clock = ManualHybridClock(NOW)
    repository = InMemoryHybridKnowledgeRepository(clock=clock)
    repository.enqueue_artifact_build(
        HybridKnowledgeJobRequest(
            job_id=request.job_id,
            idempotency_key="idempotency_1",
            request_identity=request.request_identity,
            request_sha256=request.request_sha256,
            kind="parse",
        ),
        request,
    )
    worker = HybridKnowledgeWorker(
        lifecycle=repository,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=TimeoutOncePipeline(),
        worker_id="worker_1",
    )

    first = worker.run_once()
    assert first is not None and first.state == "retry_scheduled"
    persisted = repository.get("job_1")
    assert persisted is not None and persisted.state == "RETRY_SCHEDULED"
    assert persisted.auto_retry_count == 1
    assert worker.run_once() is None

    clock.advance(seconds=5)
    completed = worker.run_once()
    assert completed is not None and completed.state == "completed"
    assert repository.get_build_result("job_1") == completed.artifacts
    terminal = repository.get("job_1")
    assert terminal is not None and terminal.fencing_token == 2


@pytest.mark.parametrize("max_auto_retries", [0, 1, 3])
def test_real_repository_binds_exact_retry_limit_and_exhausts_safely(
    tmp_path, max_auto_retries: int
) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original, max_auto_retries=max_auto_retries)
    clock = ManualHybridClock(NOW)
    repository = InMemoryHybridKnowledgeRepository(clock=clock)
    enqueued = repository.enqueue_artifact_build(
        HybridKnowledgeJobRequest(
            job_id=request.job_id,
            idempotency_key="idempotency_1",
            request_identity=request.request_identity,
            request_sha256=request.request_sha256,
            kind="parse",
        ),
        request,
    )
    assert enqueued.max_auto_retries == max_auto_retries
    worker = HybridKnowledgeWorker(
        lifecycle=repository,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=AlwaysTimeoutPipeline(),
        worker_id="worker_1",
    )

    outcomes: list[HybridWorkerOutcome] = []
    for attempt in range(max_auto_retries + 1):
        outcome = worker.run_once()
        assert outcome is not None
        outcomes.append(outcome)
        if attempt < max_auto_retries:
            assert outcome.state == "retry_scheduled"
            assert outcome.auto_retry_count == attempt + 1
            persisted_retry = repository.get(request.job_id)
            assert persisted_retry is not None
            assert persisted_retry.state == "RETRY_SCHEDULED"
            assert persisted_retry.auto_retry_count == attempt + 1
            assert persisted_retry.max_auto_retries == max_auto_retries
            clock.advance(seconds=5)

    assert [outcome.state for outcome in outcomes] == [
        *("retry_scheduled" for _ in range(max_auto_retries)),
        "failed",
    ]
    terminal = repository.get(request.job_id)
    assert terminal is not None
    assert terminal.state == "FAILED"
    assert terminal.auto_retry_count == max_auto_retries
    assert terminal.max_auto_retries == max_auto_retries
    assert terminal.failure_code == "PA_HYBRID_WORKER_RETRY_EXHAUSTED"
    assert terminal.failure_classification == "recoverable_exhausted"
    assert terminal.safe_reason == "Private parser service retry limit reached."
    assert worker.run_once() is None


def test_parser_cannot_commit_after_lease_expires_during_call(tmp_path) -> None:
    original = b"%PDF-1.7\n"
    request = _build_request(original)
    clock = ManualHybridClock(NOW)
    repository = InMemoryHybridKnowledgeRepository(clock=clock)
    repository.enqueue_artifact_build(
        HybridKnowledgeJobRequest(
            job_id=request.job_id,
            idempotency_key="idempotency_1",
            request_identity=request.request_identity,
            request_sha256=request.request_sha256,
            kind="parse",
        ),
        request,
    )
    worker = HybridKnowledgeWorker(
        lifecycle=repository,
        original_store=MemoryOriginalStore(original),
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=LeaseExpiringPipeline(clock),
        worker_id="worker_1",
        lease_seconds=60,
    )

    with pytest.raises(HybridKnowledgeLeaseError):
        worker.run_once()

    persisted = repository.get("job_1")
    assert persisted is not None and persisted.state == "LEASED"
    assert repository.get_build_result("job_1") is None


@pytest.mark.parametrize("adapter", ["inmemory", "localstore"])
def test_hybrid_lifecycle_adapters_reject_the_same_non_exact_result(
    tmp_path, adapter: Literal["inmemory", "localstore"]
) -> None:
    if adapter == "inmemory":
        request = _build_request()
        lifecycle: HybridKnowledgeArtifactLifecycle = InMemoryHybridKnowledgeRepository(
            clock=ManualHybridClock(NOW)
        )
        assert isinstance(lifecycle, InMemoryHybridKnowledgeRepository)
        lifecycle.enqueue_artifact_build(
            HybridKnowledgeJobRequest(
                job_id=request.job_id,
                idempotency_key="idempotency_1",
                request_identity=request.request_identity,
                request_sha256=request.request_sha256,
                kind="parse",
            ),
            request,
        )
    else:
        store = LocalAgentConfigurationStore(tmp_path / "config")
        store.create_knowledge_source(
            source_id="source_1",
            name="Hybrid",
            provider="hybrid_index",
            params={},
            actor="operator",
        )
        pdf_path = tmp_path / "scanned.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with pdf_path.open("wb") as stream:
            writer.write(stream)
        store.stage_quarantined_knowledge_upload(
            source_id="source_1",
            filename="policy.pdf",
            content_type="application/pdf",
            content=pdf_path.read_bytes(),
            actor="operator",
        )
        unified = create_knowledge_ingestion_worker(
            tmp_path / "config",
            hybrid_pipeline=FakePipeline(),
            hybrid_build_config=HybridPrivateParserBuildConfig(
                parser_revision="docling@2.112.0",
                model_digests=("sha256:model",),
                configuration_sha256="b" * 64,
            ),
        )
        promoted = unified.run_once()
        assert promoted is not None and promoted.outcome is not None
        assert promoted.outcome.state == "accepted"
        lifecycle = LocalStoreHybridWorkerLifecycle(
            store=store,
            original_store=LocalManagedOriginalStore(),
        )

    if adapter == "localstore":
        selection = store.claim_next_knowledge_worker_task(
            lease_seconds=60, providers={"hybrid_index"}
        )
        assert selection.task is not None and selection.task.ingestion_job is not None
        claim = lifecycle.claim_from_job(selection.task.ingestion_job)
    else:
        claim = lifecycle.claim_next(worker_id="worker_1", lease_seconds=60)
    assert claim is not None
    request = lifecycle.load_build_request(claim)
    result = _build_result(request)
    mismatched_original = result.original_ref.model_copy(
        update={"artifact_uri": "s3://attacker/substituted-original.pdf"}
    )

    with pytest.raises(ValueError, match="exact immutable original"):
        lifecycle.commit_artifact_build(
            claim,
            result.model_copy(update={"original_ref": mismatched_original}),
        )


@pytest.mark.parametrize(
    "tamper",
    ["build_configuration", "vendor_media", "version_id", "duplicate_required_ref"],
)
def test_exact_result_validator_rejects_build_and_artifact_ref_tampering(
    tamper: str,
) -> None:
    request = _build_request()
    result = _build_result(request)
    if tamper == "build_configuration":
        result = result.model_copy(
            update={
                "build_identity": result.build_identity.model_copy(
                    update={"configuration_sha256": "c" * 64}
                )
            }
        )
    elif tamper == "vendor_media":
        vendor = result.vendor_refs[0]
        result = result.model_copy(
            update={
                "vendor_refs": (
                    vendor.model_copy(
                        update={
                            "ref": vendor.ref.model_copy(update={"media_type": "text/plain"})
                        }
                    ),
                )
            }
        )
    elif tamper == "version_id":
        result = result.model_copy(
            update={
                "canonical_ref": result.canonical_ref.model_copy(
                    update={"version_id": "sha256:" + "0" * 64}
                )
            }
        )
    else:
        result = result.model_copy(
            update={
                "preview_ref": result.preview_ref.model_copy(
                    update={"artifact_uri": result.canonical_ref.artifact_uri}
                )
            }
        )

    with pytest.raises(ValueError):
        hybrid_worker_module.validate_hybrid_artifact_build_result(request, result)


def test_localstore_adapter_uses_one_claim_and_persists_exact_result(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="source_1",
        name="Hybrid",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    pdf_path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    store.stage_quarantined_knowledge_upload(
        source_id="source_1",
        filename="policy.pdf",
        content_type="application/pdf",
        content=pdf_path.read_bytes(),
        actor="operator",
    )
    lifecycle = LocalStoreHybridWorkerLifecycle(
        store=store, original_store=LocalManagedOriginalStore()
    )
    assert isinstance(lifecycle, HybridKnowledgeArtifactLifecycle)
    unified = create_knowledge_ingestion_worker(
        tmp_path / "config",
        hybrid_pipeline=FakePipeline(),
        hybrid_build_config=HybridPrivateParserBuildConfig(
            parser_revision="docling@2.112.0",
            model_digests=("sha256:model",),
            configuration_sha256="b" * 64,
        ),
    )

    promoted = unified.run_once()
    assert promoted is not None and promoted.outcome is not None
    assert promoted.outcome.state == "accepted"
    result = unified.run_once()

    assert result is not None and result.outcome is not None
    assert result.outcome.state == "ready"
    jobs = store.list_knowledge_ingestion_jobs("source_1")
    assert len(jobs) == 1 and jobs[0].state == "ready"
    assert jobs[0].attempt_count == 1
    result_files = tuple((tmp_path / "config").rglob("hybrid-artifact-result.json"))
    assert len(result_files) == 1
    completed = store.get_completed_hybrid_artifact_build_result(
        source_id="source_1",
        document_id=jobs[0].document_id,
        revision_id=jobs[0].revision_id,
    )
    authority = FilesystemInsuranceMetadataReviewRepository(
        tmp_path / "config"
    ).list_authority_records(
        source_id="source_1",
        document_id=jobs[0].document_id,
        revision_id=jobs[0].revision_id,
    )
    assert len(authority) == 1
    assert authority[0].structured_build_id == completed.build_id
    assert authority[0].original_ref == completed.persisted_original_ref


def test_localstore_exhausted_transient_is_not_classified_as_integrity_failure(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="source_1",
        name="Hybrid",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    pdf_path = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with pdf_path.open("wb") as stream:
        writer.write(stream)
    store.stage_quarantined_knowledge_upload(
        source_id="source_1",
        filename="policy.pdf",
        content_type="application/pdf",
        content=pdf_path.read_bytes(),
        actor="operator",
    )
    unified = create_knowledge_ingestion_worker(
        tmp_path / "config",
        hybrid_pipeline=FakePipeline(),
        hybrid_build_config=HybridPrivateParserBuildConfig(
            parser_revision="docling@2.112.0",
            model_digests=("sha256:model",),
            configuration_sha256="b" * 64,
        ),
    )
    promoted = unified.run_once()
    assert promoted is not None and promoted.outcome is not None
    assert promoted.outcome.state == "accepted"
    lifecycle = LocalStoreHybridWorkerLifecycle(
        store=store,
        original_store=LocalManagedOriginalStore(),
    )
    selection = store.claim_next_knowledge_worker_task(
        lease_seconds=60, providers={"hybrid_index"}
    )
    assert selection.task is not None and selection.task.ingestion_job is not None
    claim = lifecycle.claim_from_job(selection.task.ingestion_job)
    assert claim is not None

    lifecycle.fail_retries_exhausted(
        claim,
        failure_code="PA_HYBRID_WORKER_RETRY_EXHAUSTED",
        safe_reason="Private parser service retry limit reached.",
    )

    job = store.list_knowledge_ingestion_jobs("source_1")[0]
    assert job.state == "failed"
    assert job.auto_retry_count == 0
    assert job.last_failure_classification == "recoverable_exhausted"
    assert job.error_code == "PA_HYBRID_WORKER_RETRY_EXHAUSTED"
    assert job.error_message == "Private parser service retry limit reached."


def test_localstore_request_integrity_failure_is_safe_and_releases_claim(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="source_1",
        name="Hybrid",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    upload = store.stage_quarantined_knowledge_upload(
        source_id="source_1",
        filename="policy.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7\n",
        actor="operator",
    )
    claimed_upload = store.claim_next_quarantined_knowledge_upload(source_id="source_1")
    assert claimed_upload is not None and claimed_upload.claim_token is not None
    document, job = store.accept_hybrid_quarantined_knowledge_upload(
        source_id="source_1",
        upload_id=upload.upload_id,
        claim_token=claimed_upload.claim_token,
        source_sha256=hashlib.sha256(b"%PDF-1.7\n").hexdigest(),
        source_size_bytes=len(b"%PDF-1.7\n"),
        page_count=1,
        parser_revision="docling@2.112.0",
        model_digests=("sha256:model",),
        configuration_sha256="b" * 64,
    )
    claimed_job = store.claim_next_knowledge_ingestion_job(source_id="source_1")
    assert claimed_job is not None and claimed_job.job_id == job.job_id
    frozen = store.knowledge_document_original_path(document).parent / "hybrid-build-request.json"
    tampered = HybridArtifactBuildRequest.model_validate_json(frozen.read_bytes()).model_copy(
        update={"parser_revision": "attacker@latest"}
    )
    tampered = tampered.model_copy(update={"request_sha256": hybrid_build_request_sha256(tampered)})
    frozen.write_text(tampered.model_dump_json(), encoding="utf-8")
    original_store = LocalManagedOriginalStore()
    lifecycle = LocalStoreHybridWorkerLifecycle(store=store, original_store=original_store)
    worker = HybridKnowledgeWorker(
        lifecycle=lifecycle,
        original_store=original_store,
        artifact_store=FileSystemKnowledgeArtifactStore(tmp_path / "artifacts"),
        pipeline=FakePipeline(),
        worker_id="unused",
    )
    handler = LocalStoreHybridTaskHandler(
        lifecycle=lifecycle,
        worker=worker,
        quarantine_promoter=LocalStoreHybridQuarantinePromoter(
            store=store,
            build_config=HybridPrivateParserBuildConfig(
                parser_revision="docling@2.112.0",
                model_digests=("sha256:model",),
                configuration_sha256="b" * 64,
            ),
        ),
    )

    outcome = handler(KnowledgeWorkerTaskClaim(kind="artifact_build", ingestion_job=claimed_job))

    assert outcome.state == "failed"
    assert outcome.error_code == "PA_HYBRID_WORKER_INTEGRITY"
    persisted = store.get_knowledge_ingestion_job(source_id="source_1", job_id=job.job_id)
    assert persisted is not None and persisted.state == "failed"
    assert persisted.claim_token is None
    assert persisted.error_message == (
        "Hybrid artifact build failed deterministic integrity validation."
    )


def test_expired_localstore_lease_cannot_reject_or_promote(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path)
    store.create_knowledge_source(
        source_id="source_1",
        name="Hybrid",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    upload = store.stage_quarantined_knowledge_upload(
        source_id="source_1",
        filename="policy.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7\n",
        actor="operator",
    )
    claimed = store.claim_next_quarantined_knowledge_upload(source_id="source_1")
    assert claimed is not None and claimed.claim_token is not None
    expired = claimed.model_copy(update={"lease_expires_at": "2000-01-01T00:00:00Z"})
    store._write_quarantined_knowledge_upload(expired)

    with pytest.raises(ProofAgentError, match="lease has expired"):
        store.reject_quarantined_knowledge_upload(
            source_id="source_1",
            upload_id=upload.upload_id,
            claim_token=claimed.claim_token,
            error_code="PA_HYBRID_INTAKE_006",
            error_message="safe",
        )

    persisted = store.get_quarantined_knowledge_upload(
        source_id="source_1", upload_id=upload.upload_id
    )
    assert persisted is not None and persisted.state == "processing"
