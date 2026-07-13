"""Fenced Hybrid Index structured-artifact build orchestration."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING, Annotated, Literal, Protocol, Self

from pydantic import (
    ConfigDict,
    Field,
    StrictBytes,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridKnowledgeArtifactLifecycle,
    HybridKnowledgeJobClaim,
    HybridKnowledgeJobRequest,
    KnowledgeArtifactStore,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.contracts import KnowledgeIngestionJob

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.contracts import KnowledgeWorkerTaskClaim
    from proof_agent.capabilities.knowledge.ingestion.worker import KnowledgeWorkerTaskOutcome
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore


NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]

_TRANSIENT_CODE = "PA_HYBRID_WORKER_TRANSIENT"
_REVIEW_CODE = "PA_HYBRID_WORKER_REVIEW_REQUIRED"
_RETRY_EXHAUSTED_CODE = "PA_HYBRID_WORKER_RETRY_EXHAUSTED"


class _HybridWorkerModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class HybridArtifactBuildRequest(_HybridWorkerModel):
    """Immutable, exact parser-build input plus durable retry projection."""

    job_id: NonBlankStr
    request_identity: NonBlankStr
    request_sha256: Sha256 = "0" * 64
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    original_ref: ExactArtifactRef
    page_numbers: tuple[PositiveInt, ...] = Field(min_length=1, max_length=500)
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...] = Field(max_length=64)
    configuration_sha256: Sha256
    auto_retry_count: NonNegativeInt = 0
    max_auto_retries: StrictInt = Field(default=2, ge=0, le=10)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if tuple(sorted(self.page_numbers)) != self.page_numbers:
            raise ValueError("page_numbers must be strictly increasing")
        if len(set(self.page_numbers)) != len(self.page_numbers):
            raise ValueError("page_numbers must be unique")
        if self.page_numbers[-1] > 500:
            raise ValueError("page_numbers cannot exceed 500")
        if len(set(self.model_digests)) != len(self.model_digests):
            raise ValueError("model_digests must be unique")
        if self.auto_retry_count > self.max_auto_retries:
            raise ValueError("auto_retry_count cannot exceed max_auto_retries")
        if self.original_ref.media_type != "application/pdf":
            raise ValueError("Hybrid artifact builds require an application/pdf original")
        return self


def hybrid_build_request_sha256(request: HybridArtifactBuildRequest) -> str:
    """Digest immutable build inputs; retry bookkeeping is intentionally excluded."""

    payload = request.model_dump(mode="json", exclude={"request_sha256", "auto_retry_count"})
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class HybridVendorArtifact(_HybridWorkerModel):
    adapter: NonBlankStr
    content: StrictBytes
    media_type: Literal["application/json"] = "application/json"


class HybridParserBuildOutput(_HybridWorkerModel):
    artifact: StructuredKnowledgeDocumentArtifact
    vendor_artifacts: tuple[HybridVendorArtifact, ...] = Field(min_length=1, max_length=501)


class HybridVendorArtifactRef(_HybridWorkerModel):
    adapter: NonBlankStr
    ref: ExactArtifactRef


class HybridArtifactBuildResult(_HybridWorkerModel):
    job_id: NonBlankStr
    request_identity: NonBlankStr
    source_id: NonBlankStr
    document_id: NonBlankStr
    revision_id: NonBlankStr
    build_id: NonBlankStr
    original_ref: ExactArtifactRef
    vendor_refs: tuple[HybridVendorArtifactRef, ...] = Field(min_length=1)
    canonical_ref: ExactArtifactRef
    preview_ref: ExactArtifactRef
    build_identity_ref: ExactArtifactRef


class HybridWorkerOutcome(_HybridWorkerModel):
    job_id: NonBlankStr
    source_id: NonBlankStr
    state: Literal["completed", "retry_scheduled", "review_required", "failed"]
    auto_retry_count: NonNegativeInt
    error_code: NonBlankStr | None = None
    artifacts: HybridArtifactBuildResult | None = None

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state == "completed" and self.artifacts is None:
            raise ValueError("completed Hybrid outcomes require exact artifact references")
        if self.state != "completed" and self.artifacts is not None:
            raise ValueError("non-completed Hybrid outcomes cannot expose committed artifacts")
        if self.state == "completed" and self.error_code is not None:
            raise ValueError("completed Hybrid outcomes cannot contain an error code")
        if self.state != "completed" and self.error_code is None:
            raise ValueError("non-completed Hybrid outcomes require a safe error code")
        return self


class TransientKnowledgeServiceError(RuntimeError):
    """A temporary private parser or model-service failure eligible for bounded retry."""


class ReviewRequiredError(RuntimeError):
    """A deterministic content-quality failure requiring operator review."""


class HybridParserPipeline(Protocol):
    def build(self, request: HybridArtifactBuildRequest) -> HybridParserBuildOutput: ...


class HybridKnowledgeWorker:
    """Process one provider-owned Hybrid parse job under a durable fenced claim."""

    def __init__(
        self,
        *,
        lifecycle: HybridKnowledgeArtifactLifecycle,
        original_store: KnowledgeArtifactStore,
        artifact_store: KnowledgeArtifactStore,
        pipeline: HybridParserPipeline,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        if type(lease_seconds) is not int or lease_seconds <= 0:
            raise ValueError("lease_seconds must be a positive integer")
        self._lifecycle = lifecycle
        self._original_store = original_store
        self._artifact_store = artifact_store
        self._pipeline = pipeline
        self._worker_id = worker_id.strip()
        self._lease_seconds = lease_seconds

    def run_once(self) -> HybridWorkerOutcome | None:
        claim = self._lifecycle.claim_next(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if claim is None:
            return None
        return self.process_claim(claim)

    def process_claim(self, claim: HybridKnowledgeJobClaim) -> HybridWorkerOutcome:
        """Process one claim already owned by the authoritative lifecycle repository."""

        request: HybridArtifactBuildRequest | None = None
        try:
            request = self._lifecycle.load_build_request(claim)
            self._validate_claim_binding(claim, request)
            claim = self._lifecycle.renew_claim(claim, lease_seconds=self._lease_seconds)
            original = self._original_store.get_exact(request.original_ref)
            _verify_exact_bytes(request.original_ref, original)
            parsed = self._pipeline.build(request)
            claim = self._lifecycle.renew_claim(claim, lease_seconds=self._lease_seconds)
            self._validate_parser_output(request, parsed)
            result = self._persist_artifacts(request, original=original, parsed=parsed)
        except (TransientKnowledgeServiceError, TimeoutError, ConnectionError):
            if request is None:
                return self._fail_integrity(claim, request=None)
            return self._handle_transient(claim, request)
        except ReviewRequiredError:
            if request is None:
                return self._fail_integrity(claim, request=None)
            self._lifecycle.require_review(
                claim,
                safe_reason="Structured document requires operator review.",
            )
            return HybridWorkerOutcome(
                job_id=request.job_id,
                source_id=request.source_id,
                state="review_required",
                auto_retry_count=request.auto_retry_count,
                error_code=_REVIEW_CODE,
            )
        except Exception:
            return self._fail_integrity(claim, request=request)

        # This is the only state commit after immutable artifacts are finalized and read back.
        # A stale fencing token may therefore leave reusable orphan bytes, never committed state.
        self._lifecycle.commit_artifact_build(claim, result)
        return HybridWorkerOutcome(
            job_id=request.job_id,
            source_id=request.source_id,
            state="completed",
            auto_retry_count=request.auto_retry_count,
            artifacts=result,
        )

    def _fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        request: HybridArtifactBuildRequest | None,
    ) -> HybridWorkerOutcome:
        self._lifecycle.fail_integrity(
            claim,
            failure_code="PA_HYBRID_WORKER_INTEGRITY",
            safe_reason="Hybrid artifact build failed deterministic integrity validation.",
        )
        return HybridWorkerOutcome(
            job_id=claim.job_id,
            source_id=request.source_id if request is not None else "unknown_source",
            state="failed",
            auto_retry_count=request.auto_retry_count if request is not None else 0,
            error_code="PA_HYBRID_WORKER_INTEGRITY",
        )

    def _handle_transient(
        self,
        claim: HybridKnowledgeJobClaim,
        request: HybridArtifactBuildRequest,
    ) -> HybridWorkerOutcome:
        if request.auto_retry_count >= request.max_auto_retries:
            self._lifecycle.fail_integrity(
                claim,
                failure_code=_RETRY_EXHAUSTED_CODE,
                safe_reason="Private parser service retry limit reached.",
            )
            return HybridWorkerOutcome(
                job_id=request.job_id,
                source_id=request.source_id,
                state="failed",
                auto_retry_count=request.auto_retry_count,
                error_code=_RETRY_EXHAUSTED_CODE,
            )
        next_count = request.auto_retry_count + 1
        self._lifecycle.schedule_retry(
            claim,
            auto_retry_count=next_count,
            safe_error="Temporary private parser service failure.",
        )
        return HybridWorkerOutcome(
            job_id=request.job_id,
            source_id=request.source_id,
            state="retry_scheduled",
            auto_retry_count=next_count,
            error_code=_TRANSIENT_CODE,
        )

    @staticmethod
    def _validate_claim_binding(
        claim: HybridKnowledgeJobClaim,
        request: HybridArtifactBuildRequest,
    ) -> None:
        if request.job_id != claim.job_id:
            raise ValueError("Hybrid build request job identity does not match its claim")
        if request.request_identity != claim.request.request_identity:
            raise ValueError("Hybrid build request identity does not match its claim")
        if request.request_sha256 != claim.request.request_sha256:
            raise ValueError("Hybrid build request digest does not match its claim")
        if hybrid_build_request_sha256(request) != claim.request.request_sha256:
            raise ValueError("Hybrid build request digest does not bind its immutable payload")
        if claim.request.kind != "parse":
            raise ValueError("Hybrid structured artifact worker accepts only parse jobs")

    @staticmethod
    def _validate_parser_output(
        request: HybridArtifactBuildRequest,
        parsed: HybridParserBuildOutput,
    ) -> None:
        artifact = parsed.artifact
        build = artifact.build_identity
        if (
            artifact.document_id != request.document_id
            or artifact.revision_id != request.revision_id
        ):
            raise ValueError(
                "canonical artifact document identity does not match the build request"
            )
        if artifact.original_sha256 != request.original_ref.sha256:
            raise ValueError("canonical artifact original digest does not match the exact original")
        if build.source_sha256 != request.original_ref.sha256:
            raise ValueError("structured build identity does not bind the exact original")
        if build.parser_revision != request.parser_revision:
            raise ValueError("structured build parser revision does not match the request")
        if build.model_digests != request.model_digests:
            raise ValueError("structured build model digests do not match the request")
        if build.configuration_sha256 != request.configuration_sha256:
            raise ValueError("structured build configuration does not match the request")
        if tuple(page.page_number for page in artifact.pages) != request.page_numbers:
            raise ValueError("canonical artifact pages do not exactly cover the requested pages")
        if any(signal.requires_review for signal in artifact.quality_signals):
            raise ReviewRequiredError("canonical artifact contains a review-required signal")

    def _persist_artifacts(
        self,
        request: HybridArtifactBuildRequest,
        *,
        original: bytes,
        parsed: HybridParserBuildOutput,
    ) -> HybridArtifactBuildResult:
        artifact = parsed.artifact
        key_root = (
            f"hybrid/{request.original_ref.sha256}/"
            f"{hashlib.sha256(artifact.build_identity.build_id.encode()).hexdigest()}"
        )
        original_ref = self._put_verified(
            key=f"{key_root}/original.pdf",
            content=original,
            media_type="application/pdf",
        )
        vendor_refs = tuple(
            HybridVendorArtifactRef(
                adapter=vendor.adapter,
                ref=self._put_verified(
                    key=f"{key_root}/vendor-{index:04d}.json",
                    content=_validated_canonical_vendor_json(vendor.content),
                    media_type=vendor.media_type,
                ),
            )
            for index, vendor in enumerate(parsed.vendor_artifacts, 1)
        )
        canonical = _canonical_json(artifact.model_dump(mode="json", by_alias=True))
        canonical_ref = self._put_verified(
            key=f"{key_root}/canonical.json",
            content=canonical,
            media_type="application/json",
        )
        preview_ref = self._put_verified(
            key=f"{key_root}/preview.md",
            content=_preview_markdown(artifact),
            media_type="text/markdown",
        )
        build_identity_ref = self._put_verified(
            key=f"{key_root}/build-identity.json",
            content=_canonical_json(artifact.build_identity.model_dump(mode="json")),
            media_type="application/json",
        )
        return HybridArtifactBuildResult(
            job_id=request.job_id,
            request_identity=request.request_identity,
            source_id=request.source_id,
            document_id=request.document_id,
            revision_id=request.revision_id,
            build_id=artifact.build_identity.build_id,
            original_ref=original_ref,
            vendor_refs=vendor_refs,
            canonical_ref=canonical_ref,
            preview_ref=preview_ref,
            build_identity_ref=build_identity_ref,
        )

    def _put_verified(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        ref = self._artifact_store.put_immutable(
            key=key,
            content=content,
            media_type=media_type,
        )
        stored = self._artifact_store.get_exact(ref)
        _verify_exact_bytes(ref, stored)
        if stored != content:
            raise ValueError("immutable artifact read-back bytes do not match finalized bytes")
        return ref


def _verify_exact_bytes(ref: ExactArtifactRef, content: bytes) -> None:
    if len(content) != ref.size_bytes or hashlib.sha256(content).hexdigest() != ref.sha256:
        raise ValueError("artifact bytes failed exact digest or length verification")
    if ref.version_id != f"sha256:{ref.sha256}":
        raise ValueError("artifact version identity does not match its digest")


def _validated_canonical_vendor_json(content: bytes) -> bytes:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("vendor artifact must contain valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("vendor artifact root must be a JSON object")
    canonical = _canonical_json(value)
    if canonical != content:
        raise ValueError("vendor artifact must use deterministic canonical JSON encoding")
    return canonical


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _preview_markdown(artifact: StructuredKnowledgeDocumentArtifact) -> bytes:
    lines = [f"# Structured preview: {artifact.document_id}", ""]
    for page in artifact.pages:
        lines.extend((f"## Page {page.page_number}", ""))
        lines.extend(block.text for block in page.blocks if block.text)
        for table in page.tables:
            if table.title:
                lines.append(table.title)
            lines.extend(cell.text for cell in table.cells if cell.text)
        lines.append("")
    return "\n".join(lines).encode("utf-8")


class LocalManagedOriginalStore:
    """Exact-reader for LocalStore originals registered from an owned immutable job."""

    def __init__(self) -> None:
        self._paths: dict[ExactArtifactRef, Path] = {}
        self._lock = RLock()

    def register(self, ref: ExactArtifactRef, path: Path) -> None:
        with self._lock:
            self._paths[ref] = path

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        with self._lock:
            path = self._paths.get(ref)
        if path is None:
            raise ValueError("managed original reference is not bound to the owned job")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                content = stream.read()
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        _verify_exact_bytes(ref, content)
        return content

    def put_immutable(self, *, key: str, content: bytes, media_type: str) -> ExactArtifactRef:
        raise TypeError("managed original store is read-only")


class HybridPrivateParserBuildConfig(_HybridWorkerModel):
    parser_revision: NonBlankStr
    model_digests: tuple[NonBlankStr, ...] = Field(min_length=1, max_length=64)
    configuration_sha256: Sha256


class LocalStoreHybridQuarantinePromoter:
    """Revalidate and promote one already-owned Hybrid PDF quarantine claim."""

    def __init__(
        self,
        *,
        store: LocalAgentConfigurationStore,
        build_config: HybridPrivateParserBuildConfig,
        lease_seconds: int = 300,
    ) -> None:
        self._store = store
        self._build_config = build_config
        self._lease_seconds = lease_seconds

    def __call__(self, task: KnowledgeWorkerTaskClaim) -> KnowledgeWorkerTaskOutcome:
        from proof_agent.capabilities.knowledge.hybrid.intake import preflight_hybrid_pdf
        from proof_agent.capabilities.knowledge.ingestion.contracts import (
            HybridIntakeLimits,
        )
        from proof_agent.capabilities.knowledge.ingestion.worker import (
            KnowledgeWorkerTaskOutcome,
        )
        from proof_agent.errors import ProofAgentError

        upload = task.upload
        if task.kind != "quarantine_validation" or upload is None or upload.claim_token is None:
            raise ValueError("Hybrid quarantine claim is incomplete")
        source = self._store.get_knowledge_source(upload.source_id)
        if source is None or source.provider != "hybrid_index":
            raise ValueError("Hybrid quarantine claim Source is invalid")
        limits = HybridIntakeLimits.model_validate(dict(source.params), strict=True)
        self._store.renew_quarantined_knowledge_upload_claim(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token=upload.claim_token,
            lease_seconds=self._lease_seconds,
        )
        try:
            preflight = preflight_hybrid_pdf(
                self._store.quarantined_knowledge_upload_bytes_path(upload),
                limits=limits,
            )
        except ProofAgentError as exc:
            rejected = self._store.reject_quarantined_knowledge_upload(
                source_id=upload.source_id,
                upload_id=upload.upload_id,
                claim_token=upload.claim_token,
                error_code=exc.code,
                error_message=exc.message,
            )
            return KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id=upload.upload_id,
                source_id=upload.source_id,
                state="rejected",
                error_code=rejected.error_code,
                error_message=rejected.error_message,
            )
        self._store.renew_quarantined_knowledge_upload_claim(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token=upload.claim_token,
            lease_seconds=self._lease_seconds,
        )
        self._store.accept_hybrid_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token=upload.claim_token,
            source_sha256=preflight.source_sha256,
            source_size_bytes=preflight.source_size_bytes,
            page_count=preflight.page_count,
            parser_revision=self._build_config.parser_revision,
            model_digests=self._build_config.model_digests,
            configuration_sha256=self._build_config.configuration_sha256,
        )
        return KnowledgeWorkerTaskOutcome(
            kind="quarantine_validation",
            task_id=upload.upload_id,
            source_id=upload.source_id,
            state="accepted",
        )


class LocalStoreHybridWorkerLifecycle:
    """Production adapter mapping one LocalStore claim token to the fenced lifecycle."""

    def __init__(
        self,
        *,
        store: LocalAgentConfigurationStore,
        original_store: LocalManagedOriginalStore,
    ) -> None:
        self._store = store
        self._original_store = original_store
        self._owned: dict[str, tuple[str, HybridArtifactBuildRequest]] = {}
        self._lock = RLock()

    def claim_from_job(self, job: KnowledgeIngestionJob) -> HybridKnowledgeJobClaim:
        if job.claim_token is None or job.claimed_at is None or job.lease_expires_at is None:
            raise ValueError("Hybrid LocalStore job must already have an active claim")
        document = self._store.get_knowledge_document(
            source_id=job.source_id,
            document_id=job.document_id,
        )
        if document is None:
            raise ValueError("Hybrid LocalStore job document projection is missing")
        original_path = self._store.knowledge_document_original_path(document)
        original_content = _read_regular_nofollow(original_path)
        original_sha256 = hashlib.sha256(original_content).hexdigest()
        if original_sha256 != job.artifact_build_spec.content_hash:
            raise ValueError("Hybrid LocalStore original digest does not match its frozen job")
        original_ref = ExactArtifactRef(
            artifact_uri=original_path.resolve().as_uri(),
            version_id=f"sha256:{original_sha256}",
            sha256=original_sha256,
            size_bytes=len(original_content),
            media_type="application/pdf",
        )
        self._original_store.register(original_ref, original_path)
        try:
            frozen_request = HybridArtifactBuildRequest.model_validate_json(
                _read_regular_nofollow(original_path.parent / "hybrid-build-request.json")
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Hybrid LocalStore frozen build request is invalid") from exc
        expected_identity = f"{job.source_id}:{job.document_id}:{job.revision_id}"
        if (
            frozen_request.job_id != job.job_id
            or frozen_request.request_identity != expected_identity
            or frozen_request.source_id != job.source_id
            or frozen_request.document_id != job.document_id
            or frozen_request.revision_id != job.revision_id
            or frozen_request.original_ref != original_ref
            or frozen_request.parser_revision != job.artifact_build_spec.engine_version
            or _model_digests_identity(frozen_request.model_digests)
            != job.artifact_build_spec.parser_fingerprint_identity
            or frozen_request.configuration_sha256 != job.ingestion_config_fingerprint
            or frozen_request.max_auto_retries != job.max_auto_retries
            or hybrid_build_request_sha256(frozen_request) != frozen_request.request_sha256
        ):
            raise ValueError("Hybrid LocalStore frozen build request does not match its job")
        build_request = frozen_request.model_copy(update={"auto_retry_count": job.auto_retry_count})
        scheduler_request = HybridKnowledgeJobRequest(
            job_id=job.job_id,
            idempotency_key=job.job_id,
            request_identity=build_request.request_identity,
            request_sha256=build_request.request_sha256,
            kind="parse",
        )
        token = int.from_bytes(hashlib.sha256(job.claim_token.encode()).digest()[:8], "big") or 1
        claim = HybridKnowledgeJobClaim(
            job_id=job.job_id,
            request=scheduler_request,
            worker_id="local-store-worker",
            fencing_token=token,
            claimed_at=datetime.fromisoformat(job.claimed_at).astimezone(UTC),
            lease_expires_at=datetime.fromisoformat(job.lease_expires_at).astimezone(UTC),
        )
        with self._lock:
            self._owned[job.job_id] = (job.claim_token, build_request)
        return claim

    def claim_next(self, *, worker_id: str, lease_seconds: int) -> HybridKnowledgeJobClaim | None:
        raise TypeError("LocalStore lifecycle consumes an already-claimed unified task")

    def fail_claimed_job_integrity(self, job: KnowledgeIngestionJob) -> object:
        if job.claim_token is None:
            raise ValueError("Hybrid LocalStore job has no active claim")
        return self._store.fail_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=job.claim_token,
            error_code="PA_HYBRID_WORKER_INTEGRITY",
            error_message="Hybrid artifact build failed deterministic integrity validation.",
        )

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest:
        _token, request = self._require_owned(claim)
        return request

    def renew_claim(
        self, claim: HybridKnowledgeJobClaim, *, lease_seconds: int
    ) -> HybridKnowledgeJobClaim:
        token, request = self._require_owned(claim)
        renewed = self._store.renew_knowledge_ingestion_job_claim(
            source_id=request.source_id,
            job_id=request.job_id,
            claim_token=token,
            lease_seconds=lease_seconds,
        )
        if renewed.lease_expires_at is None:
            raise ValueError("renewed Hybrid LocalStore claim has no lease expiry")
        return claim.model_copy(
            update={"lease_expires_at": datetime.fromisoformat(renewed.lease_expires_at)}
        )

    def commit_artifact_build(
        self, claim: HybridKnowledgeJobClaim, result: HybridArtifactBuildResult
    ) -> object:
        token, request = self._require_owned(claim)
        if (
            result.job_id != request.job_id
            or result.request_identity != request.request_identity
            or result.source_id != request.source_id
            or result.document_id != request.document_id
            or result.revision_id != request.revision_id
            or result.original_ref.sha256 != request.original_ref.sha256
            or result.original_ref.size_bytes != request.original_ref.size_bytes
            or result.original_ref.media_type != "application/pdf"
            or not result.vendor_refs
            or result.canonical_ref.media_type != "application/json"
            or result.preview_ref.media_type != "text/markdown"
            or result.build_identity_ref.media_type != "application/json"
        ):
            raise ValueError("Hybrid result does not match the full owned LocalStore request")
        for ref in (
            result.original_ref,
            *(vendor.ref for vendor in result.vendor_refs),
            result.canonical_ref,
            result.preview_ref,
            result.build_identity_ref,
        ):
            if ref.version_id != f"sha256:{ref.sha256}" or ref.size_bytes <= 0:
                raise ValueError("Hybrid result contains an invalid exact artifact reference")
        completed = self._store.complete_hybrid_knowledge_ingestion_job(
            source_id=request.source_id,
            job_id=request.job_id,
            claim_token=token,
            artifact_path=result.canonical_ref.artifact_uri,
            artifact_result=result.model_dump(mode="json"),
        )
        self._release(claim.job_id)
        return completed

    def schedule_retry(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        auto_retry_count: int,
        safe_error: str,
    ) -> object:
        token, request = self._require_owned(claim)
        rescheduled = self._store.reschedule_knowledge_ingestion_job(
            source_id=request.source_id,
            job_id=request.job_id,
            claim_token=token,
            error_code=_TRANSIENT_CODE,
            error_message=safe_error,
            retry_delay_seconds=5,
        )
        if rescheduled.auto_retry_count != auto_retry_count:
            raise ValueError("LocalStore retry counter did not advance exactly once")
        self._release(claim.job_id)
        return rescheduled

    def require_review(self, claim: HybridKnowledgeJobClaim, *, safe_reason: str) -> object:
        token, request = self._require_owned(claim)
        reviewed = self._store.require_hybrid_knowledge_ingestion_review(
            source_id=request.source_id,
            job_id=request.job_id,
            claim_token=token,
            safe_reason=safe_reason,
        )
        self._release(claim.job_id)
        return reviewed

    def fail_integrity(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        failure_code: str,
        safe_reason: str,
    ) -> object:
        token, request = self._require_owned(claim)
        failed = self._store.fail_knowledge_ingestion_job(
            source_id=request.source_id,
            job_id=request.job_id,
            claim_token=token,
            error_code=failure_code,
            error_message=safe_reason,
        )
        self._release(claim.job_id)
        return failed

    def _require_owned(
        self, claim: HybridKnowledgeJobClaim
    ) -> tuple[str, HybridArtifactBuildRequest]:
        with self._lock:
            owned = self._owned.get(claim.job_id)
        if owned is None:
            raise ValueError("Hybrid LocalStore claim is no longer owned")
        token, request = owned
        expected = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], "big") or 1
        if expected != claim.fencing_token:
            raise ValueError("Hybrid LocalStore fencing token is stale")
        return owned

    def _release(self, job_id: str) -> None:
        with self._lock:
            self._owned.pop(job_id, None)


def _read_regular_nofollow(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _model_digests_identity(model_digests: tuple[str, ...]) -> str:
    return hashlib.sha256(
        json.dumps(list(model_digests), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
