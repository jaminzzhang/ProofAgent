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
from knowledge_source_service.domain.identities import sha256_json
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from ocr_fixture import ReviewedOcrExtractor, blank_png


def test_png_ocr_region_is_queryable_with_exact_bounding_box_citation() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    published = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
        ocr_extractor=ReviewedOcrExtractor(),
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-scan-policy",
            display_filename="policy.png",
            media_type="image/png",
            content=blank_png(),
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
                effective_access_scope_digest=f"sha256:{'f' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == (
        "Flight delay benefit is 300 CNY after four hours."
    )
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "ocr_region",
        "page_number": 1,
        "bounding_box": {
            "x_min": 10,
            "y_min": 12,
            "x_max": 190,
            "y_max": 42,
        },
    }
    assert published.processing_lineage_digest == sha256_json(
        {
            "schema": "document-processing-lineage.v1",
            "pipeline_revision": "document-pipeline-v1",
            "media_type": "image/png",
            "document_structure_schema": "document-structure-graph.v2",
            "evidence_manifest_schema": "evidence-unit-manifest.v1",
            "ocr_model_revision": "ocr-private-v3",
        }
    )
