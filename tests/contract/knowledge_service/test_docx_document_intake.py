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
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery
from office_fixture import docx_with_paragraphs, docx_with_table


def test_docx_paragraph_is_queryable_with_exact_paragraph_citation() -> None:
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
            knowledge_source_id="source-docx-policy",
            display_filename="policy.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=docx_with_paragraphs(
                "Policy overview",
                "Flight delay benefit is 300 CNY after four hours.",
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
    assert candidate.content.text == (
        "Flight delay benefit is 300 CNY after four hours."
    )
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "docx_paragraph",
        "paragraph_number": 2,
    }


def test_docx_table_cell_is_queryable_with_exact_cell_citation() -> None:
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
            knowledge_source_id="source-docx-table",
            display_filename="benefits.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
            content=docx_with_table(
                (
                    ("Event", "Benefit"),
                    ("Flight delay after four hours", "300 CNY"),
                )
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
                    "question": "300 CNY benefit",
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
                effective_access_scope_digest=f"sha256:{'b' * 64}",
            ),
        )
    )

    candidate = result.evidence_groups[0].candidate_evidence[0]
    assert candidate.content.text == "300 CNY"
    assert candidate.citation_locator.model_dump(mode="json") == {
        "kind": "docx_table_cell",
        "table_number": 1,
        "row_number": 2,
        "column_number": 2,
    }
