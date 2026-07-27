from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
from typing import Any, BinaryIO
from uuid import uuid4

from openpyxl import Workbook
from pypdf import PdfWriter
import pytest

from proof_agent.capabilities.knowledge.hybrid.rule_units import project_rule_units
from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import (
    S3ExactArtifactStore,
)
from proof_agent.capabilities.knowledge.hybrid.workbook import WORKBOOK_MEDIA_TYPE
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridArtifactBuildRequest,
    HybridArtifactBuildResult,
    HybridInsuranceMetadataArtifact,
    HybridPrivateParserBuildConfig,
    HybridVendorArtifactRef,
)
from proof_agent.capabilities.knowledge.ingestion.metadata_import_worker import (
    MetadataWorkbookImportWorker,
)
from proof_agent.capabilities.persistence.postgres.bundle import PostgresPersistenceBundle
from proof_agent.capabilities.persistence.postgres.database import upgrade_database
from proof_agent.contracts import AuditActorFacts
from proof_agent.contracts.hybrid_documents import (
    BoundingBox,
    StructuredArtifactBuildIdentity,
    StructuredBlock,
    StructuredKnowledgeDocumentArtifact,
    StructuredPage,
)
from proof_agent.contracts.insurance_rules import InsuranceRuleMetadataDraft
from proof_agent.contracts.knowledge_index import ExactArtifactRef
from proof_agent.control.knowledge.production_intake import (
    ProductionHybridKnowledgeIntakeService,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

_HEADERS = (
    "template_revision",
    "source_id",
    "document_id",
    "revision_id",
    "canonical_anchor",
    "authority",
    "effective_from",
    "effective_to",
    "taxonomy_id",
    "taxonomy_revision_id",
    "precedence_policy_revision_id",
    "precedence_authority_tier",
    "precedence_order",
)


class _MemoryExactArtifactStore:
    def __init__(self) -> None:
        self._by_uri: dict[str, bytes] = {}
        self._by_key: dict[str, ExactArtifactRef] = {}

    def put_immutable(
        self,
        *,
        key: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactRef:
        digest = hashlib.sha256(content).hexdigest()
        existing = self._by_key.get(key)
        if existing is not None:
            assert self._by_uri[existing.artifact_uri] == content
            assert existing.sha256 == digest
            return existing
        ref = ExactArtifactRef(
            artifact_uri=f"s3://proof-agent-test/{key}",
            version_id=f"version-{len(self._by_key) + 1}",
            sha256=digest,
            size_bytes=len(content),
            media_type=media_type,
        )
        self._by_key[key] = ref
        self._by_uri[ref.artifact_uri] = content
        return ref

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
        assert len(body) == expected_size_bytes
        assert hashlib.sha256(body).hexdigest() == expected_sha256
        return self.put_immutable(key=key, content=body, media_type=media_type)

    def get_exact(self, ref: ExactArtifactRef) -> bytes:
        body = self._by_uri[ref.artifact_uri]
        assert len(body) == ref.size_bytes
        assert hashlib.sha256(body).hexdigest() == ref.sha256
        return body


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def _workbook(
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
    canonical_anchor: str,
    formula: bool = False,
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Metadata"
    sheet.append(_HEADERS)
    sheet.append(
        (
            "insurance-rule-metadata.v1",
            source_id,
            document_id,
            revision_id,
            canonical_anchor,
            "=1+1" if formula else "national",
            "2026-01-01",
            "2026-12-31",
            "insurance-product-applicability",
            "taxonomy-2026-01",
            "precedence-2026-01",
            "policy_terms",
            10,
        )
    )
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _seed_completed_candidate(
    bundle: PostgresPersistenceBundle,
    store: Any,
    *,
    source_id: str,
    actor: AuditActorFacts,
) -> tuple[ProductionHybridKnowledgeIntakeService, HybridArtifactBuildRequest, str]:
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
    )
    service.create_source(
        source_id=source_id,
        name="Insurance terms",
        params={},
        actor=actor,
    )
    service.upload_document(
        source_id=source_id,
        filename="terms.pdf",
        content_type="application/pdf",
        content=BytesIO(_pdf()),
        expected_revision=1,
        idempotency_key="upload-request-1",
        actor=actor,
    )
    request = bundle.hybrid_ingestion.list_records_for_source(
        source_id
    )[0].build_request
    claim = bundle.hybrid_ingestion.claim_next(
        worker_id="knowledge-worker-parser",
        lease_seconds=60,
    )
    assert claim is not None
    identity = StructuredArtifactBuildIdentity(
        build_id=f"build-{request.revision_id}",
        source_sha256=request.original_ref.sha256,
        parser_adapter="docling",
        parser_revision=request.parser_revision,
        model_digests=request.model_digests,
        canonical_schema_version="structured-knowledge.v1",
        configuration_sha256=request.configuration_sha256,
    )
    canonical = StructuredKnowledgeDocumentArtifact(
        schema_version="structured-knowledge.v1",
        document_id=request.document_id,
        revision_id=request.revision_id,
        original_sha256=request.original_ref.sha256,
        build_identity=identity,
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
                        bbox=BoundingBox(x0=1, y0=1, x1=500, y1=50),
                        reading_order=0,
                    ),
                ),
            ),
        ),
    )
    metadata = HybridInsuranceMetadataArtifact(
        source_id=source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        structured_build_id=identity.build_id,
        original_sha256=request.original_ref.sha256,
        document_defaults=InsuranceRuleMetadataDraft(
            metadata_draft_id="metadata-defaults-1",
            document_id=request.document_id,
            revision_id=request.revision_id,
        ),
        pdf_drafts=(),
    )
    build_key = (
        f"hybrid/{request.original_ref.sha256}/{request.request_sha256}"
    )
    canonical_ref = store.put_immutable(
        key=f"{build_key}/canonical.json",
        content=_canonical_json(canonical.model_dump(mode="json")),
        media_type="application/json",
    )
    metadata_ref = store.put_immutable(
        key=f"{build_key}/insurance-metadata.json",
        content=_canonical_json(metadata.model_dump(mode="json")),
        media_type="application/json",
    )
    build_identity_ref = store.put_immutable(
        key=f"{build_key}/build-identity.json",
        content=_canonical_json(identity.model_dump(mode="json")),
        media_type="application/json",
    )
    vendor_ref = store.put_immutable(
        key=f"{build_key}/vendor-0001.json",
        content=b"{}",
        media_type="application/json",
    )
    preview_ref = store.put_immutable(
        key=f"{build_key}/preview.md",
        content=b"# preview",
        media_type="text/markdown",
    )
    bundle.hybrid_ingestion.commit_artifact_build(
        claim,
        HybridArtifactBuildResult(
            job_id=request.job_id,
            request_identity=request.request_identity,
            source_id=source_id,
            document_id=request.document_id,
            revision_id=request.revision_id,
            build_id=identity.build_id,
            build_identity=identity,
            original_ref=request.original_ref,
            persisted_original_ref=request.original_ref,
            vendor_refs=(
                HybridVendorArtifactRef(adapter="docling", ref=vendor_ref),
            ),
            canonical_ref=canonical_ref,
            preview_ref=preview_ref,
            build_identity_ref=build_identity_ref,
            insurance_metadata_ref=metadata_ref,
        ),
    )
    projected = project_rule_units(
        canonical,
        document_defaults=metadata.document_defaults,
        source_id=source_id,
    )
    assert len(projected) == 1
    return service, request, projected[0].canonical_anchor


def _admit_workbook(
    bundle: PostgresPersistenceBundle,
    store: Any,
    *,
    formula: bool = False,
) -> tuple[str, str]:
    actor = AuditActorFacts(
        subject="operator-1",
        identity_provider="enterprise-oidc",
        session_id=str(uuid4()),
        permissions=("knowledge_source.edit",),
    )
    source_id = f"ks_{uuid4().hex}"
    service, request, anchor = _seed_completed_candidate(
        bundle,
        store,
        source_id=source_id,
        actor=actor,
    )
    content = _workbook(
        source_id=source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        canonical_anchor=anchor,
        formula=formula,
    )
    source_revision = bundle.knowledge.get_source_record(source_id).revision
    operation = service.import_metadata(
        source_id=source_id,
        document_id=request.document_id,
        revision_id=request.revision_id,
        filename="metadata.xlsx",
        content_type=WORKBOOK_MEDIA_TYPE,
        content=BytesIO(content),
        expected_revision=source_revision,
        idempotency_key="metadata-import-1",
        actor=actor,
    )
    return source_id, operation.operation_id


def test_worker_atomically_commits_valid_workbook_reviews(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = _MemoryExactArtifactStore()
    try:
        source_id, operation_id = _admit_workbook(bundle, store)
        revision_before = bundle.knowledge.get_source_record(source_id).revision
        worker = MetadataWorkbookImportWorker(
            jobs=bundle.metadata_imports,
            ingestion=bundle.hybrid_ingestion,
            unit_of_work_factory=bundle.configuration_uow,
            artifact_store=store,
            worker_id="knowledge-worker-metadata",
        )

        outcome = worker.run_once()

        assert outcome is not None
        assert outcome.state == "completed", outcome
        assert len(bundle.metadata_reviews.list(source_id)) == 1
        operation = bundle.knowledge_source_operations.get(operation_id)
        assert operation is not None
        assert operation.status == "succeeded"
        assert operation.stage == "metadata_import_completed"
        assert bundle.knowledge.get_source_record(source_id).revision == (
            revision_before + 1
        )
        job = bundle.metadata_imports.get_for_operation(operation_id)
        assert job is not None
        assert job.state == "COMPLETED"
        assert job.result_import_id == outcome.result_import_id
    finally:
        bundle.close()


def test_worker_rejects_formula_workbook_without_partial_reviews(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = _MemoryExactArtifactStore()
    try:
        source_id, operation_id = _admit_workbook(bundle, store, formula=True)
        worker = MetadataWorkbookImportWorker(
            jobs=bundle.metadata_imports,
            ingestion=bundle.hybrid_ingestion,
            unit_of_work_factory=bundle.configuration_uow,
            artifact_store=store,
            worker_id="knowledge-worker-metadata",
        )

        outcome = worker.run_once()

        assert outcome is not None
        assert outcome.state == "failed"
        assert outcome.error_code == "metadata_workbook_invalid"
        assert bundle.metadata_reviews.list(source_id) == ()
        operation = bundle.knowledge_source_operations.get(operation_id)
        assert operation is not None
        assert operation.status == "failed"
        job = bundle.metadata_imports.get_for_operation(operation_id)
        assert job is not None
        assert job.state == "FAILED"
    finally:
        bundle.close()


class _FailAfterFirstReview:
    def __init__(self, repository: Any) -> None:
        self._repository = repository

    def put_many(self, reviews: Any) -> None:
        batch = tuple(reviews)
        self._repository.put_many((batch[0],))
        raise RuntimeError("injected review batch failure")


class _FailingReviewUnitOfWork:
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __enter__(self) -> "_FailingReviewUnitOfWork":
        self._inner.__enter__()
        self.metadata_reviews = _FailAfterFirstReview(
            self._inner.metadata_reviews
        )
        return self

    def __exit__(self, *args: Any) -> None:
        self._inner.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailSecondUnitOfWork:
    def __init__(self, bundle: PostgresPersistenceBundle) -> None:
        self._bundle = bundle
        self._calls = 0

    def __call__(self) -> Any:
        self._calls += 1
        unit_of_work = self._bundle.configuration_uow()
        if self._calls == 2:
            return _FailingReviewUnitOfWork(unit_of_work)
        return unit_of_work


def test_worker_rolls_back_entire_review_batch_when_commit_fails(
    postgres_dsn: str,
) -> None:
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = _MemoryExactArtifactStore()
    try:
        source_id, operation_id = _admit_workbook(bundle, store)
        worker = MetadataWorkbookImportWorker(
            jobs=bundle.metadata_imports,
            ingestion=bundle.hybrid_ingestion,
            unit_of_work_factory=_FailSecondUnitOfWork(bundle),
            artifact_store=store,
            worker_id="knowledge-worker-metadata",
        )

        outcome = worker.run_once()

        assert outcome is not None
        assert outcome.state == "failed"
        assert outcome.error_code == "metadata_import_failed"
        assert bundle.metadata_reviews.list(source_id) == ()
        operation = bundle.knowledge_source_operations.get(operation_id)
        assert operation is not None
        assert operation.status == "failed"
    finally:
        bundle.close()


def test_worker_runs_end_to_end_over_real_postgres_and_s3(
    postgres_dsn: str,
) -> None:
    endpoint = os.environ.get("PROOF_AGENT_TEST_S3_ENDPOINT", "").strip()
    bucket = os.environ.get("PROOF_AGENT_TEST_S3_BUCKET", "").strip()
    if not endpoint or not bucket:
        pytest.skip("real S3-compatible integration environment is not configured")
    upgrade_database(postgres_dsn)
    bundle = PostgresPersistenceBundle.create(postgres_dsn)
    store = S3ExactArtifactStore.from_environment(
        bucket=bucket,
        key_prefix=f"metadata-worker-e2e/{uuid4().hex}/",
        endpoint_url=endpoint,
        region_name="us-east-1",
    )
    try:
        source_id, operation_id = _admit_workbook(bundle, store)
        worker = MetadataWorkbookImportWorker(
            jobs=bundle.metadata_imports,
            ingestion=bundle.hybrid_ingestion,
            unit_of_work_factory=bundle.configuration_uow,
            artifact_store=store,
            worker_id="knowledge-worker-metadata-s3",
        )

        outcome = worker.run_once()

        assert outcome is not None
        assert outcome.state == "completed"
        review = bundle.metadata_reviews.list(source_id)[0]
        assert store.get_exact(review.original_ref)
        assert b"insurance-metadata-workbook-normalized.v1" in store.get_exact(
            review.normalized_ref
        )
        operation = bundle.knowledge_source_operations.get(operation_id)
        assert operation is not None
        assert operation.status == "succeeded"
    finally:
        bundle.close()
