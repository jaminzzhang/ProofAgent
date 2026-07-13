"""Fenced Hybrid Index structured-artifact build orchestration."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Protocol, Self

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
    HybridKnowledgeJobClaim,
    KnowledgeArtifactStore,
)
from proof_agent.contracts._base import FrozenModel
from proof_agent.contracts.hybrid_documents import StructuredKnowledgeDocumentArtifact
from proof_agent.contracts.knowledge_index import ExactArtifactRef


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


class HybridWorkerLifecycle(Protocol):
    """Durable worker authority; every mutation must validate the claim fencing token."""

    def claim_next(
        self, *, worker_id: str, lease_seconds: int
    ) -> HybridKnowledgeJobClaim | None: ...

    def load_build_request(self, claim: HybridKnowledgeJobClaim) -> HybridArtifactBuildRequest: ...

    def commit_artifact_build(
        self, claim: HybridKnowledgeJobClaim, result: HybridArtifactBuildResult
    ) -> None: ...

    def schedule_retry(
        self,
        claim: HybridKnowledgeJobClaim,
        *,
        auto_retry_count: int,
        safe_error: str,
    ) -> None: ...

    def require_review(self, claim: HybridKnowledgeJobClaim, *, safe_reason: str) -> None: ...


class HybridKnowledgeWorker:
    """Process one provider-owned Hybrid parse job under a durable fenced claim."""

    def __init__(
        self,
        *,
        lifecycle: HybridWorkerLifecycle,
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
        request = self._lifecycle.load_build_request(claim)
        self._validate_claim_binding(claim, request)
        try:
            original = self._original_store.get_exact(request.original_ref)
            _verify_exact_bytes(request.original_ref, original)
            parsed = self._pipeline.build(request)
            self._validate_parser_output(request, parsed)
            result = self._persist_artifacts(request, original=original, parsed=parsed)
        except (TransientKnowledgeServiceError, TimeoutError, ConnectionError):
            return self._handle_transient(claim, request)
        except ReviewRequiredError:
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

    def _handle_transient(
        self,
        claim: HybridKnowledgeJobClaim,
        request: HybridArtifactBuildRequest,
    ) -> HybridWorkerOutcome:
        if request.auto_retry_count >= request.max_auto_retries:
            self._lifecycle.require_review(
                claim,
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
