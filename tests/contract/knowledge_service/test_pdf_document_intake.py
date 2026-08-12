from __future__ import annotations

from datetime import UTC, datetime

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.ocr import OcrDocument, OcrPage, OcrRegion
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from pdf_fixture import single_page_pdf


def test_native_pdf_text_is_queryable_with_exact_page_citation() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-pdf-policy",
            display_filename="policy.pdf",
            media_type="application/pdf",
            content=single_page_pdf(
                "Flight delay benefit is 300 CNY after four hours."
            ),
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                published.version.knowledge_source_version_id,
            ),
        )
    )
    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": (
                        release.release.knowledge_base_release_id
                    ),
                    "question": "flight delay four hours benefit",
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 1000,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-insurance",
                client_grant_id="grant-proof-agent",
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == "Flight delay benefit is 300 CNY after four hours."
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "pdf_page",
        "page_number": 1,
    }


class _ReviewedPdfOcrExtractor:
    def extract(self, *, media_type: str, content: bytes) -> OcrDocument:
        assert media_type == "application/pdf"
        assert content.startswith(b"%PDF-")
        return OcrDocument(
            model_revision="ocr-private-v3",
            pages=(OcrPage(page_number=1, width=612, height=792),),
            regions=(
                OcrRegion(
                    page_number=1,
                    x_min=72,
                    y_min=60,
                    x_max=420,
                    y_max=100,
                    text="Scanned flight delay benefit is 500 CNY.",
                ),
            ),
        )


def test_ocr_only_pdf_escalates_to_reviewed_ocr_with_bbox_citation() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
        ocr_extractor=_ReviewedPdfOcrExtractor(),
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-scanned-pdf",
            knowledge_source_id="source-scanned-pdf",
            display_filename="scanned-policy.pdf",
            media_type="application/pdf",
            content=single_page_pdf(""),
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-scanned-pdf",
            knowledge_base_id="base-scanned-pdf",
            knowledge_source_version_ids=(
                published.version.knowledge_source_version_id,
            ),
        )
    ).release

    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "scanned delay benefit",
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 1000,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T12:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-scanned-pdf",
                client_grant_id="grant-scanned-pdf",
                effective_access_scope_digest=f"sha256:{'f' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == "Scanned flight delay benefit is 500 CNY."
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "ocr_region",
        "page_number": 1,
        "bounding_box": {
            "x_min": 72,
            "y_min": 60,
            "x_max": 420,
            "y_max": 100,
        },
    }
