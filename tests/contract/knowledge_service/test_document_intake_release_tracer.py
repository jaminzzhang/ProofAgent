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


def _query(
    engine: HybridKnowledgeRetrievalEngine,
    *,
    release_id: str,
    question: str,
) -> list[dict[str, object]]:
    result = engine.retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release_id,
                    "question": question,
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
    return result.model_dump(mode="json")["evidence_groups"][0]["candidate_evidence"]


def test_markdown_and_text_intake_publish_exact_replayable_releases() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    intake = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    )
    releases = KnowledgeReleaseApplication(artifacts=artifacts, catalog=catalog)

    markdown_v1 = intake.create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-policy",
            display_filename="../../客户上传/保险条款.md",
            media_type="text/markdown",
            content="# 等待期\n重大疾病保险等待期为三十天。\n".encode(),
        )
    )
    contact = intake.create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-contact",
            display_filename="contact.txt",
            media_type="text/plain",
            content="客服热线为 400-123-4567。\n".encode(),
        )
    )
    release_v1 = releases.publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                markdown_v1.version.knowledge_source_version_id,
                contact.version.knowledge_source_version_id,
            ),
        )
    )

    markdown_v2 = intake.create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-policy",
            display_filename="保险条款.md",
            media_type="text/markdown",
            content="# 等待期\n重大疾病保险等待期调整为十五天。\n".encode(),
        )
    )
    release_v2 = releases.publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-insurance",
            knowledge_base_id="base-insurance",
            knowledge_source_version_ids=(
                markdown_v2.version.knowledge_source_version_id,
                contact.version.knowledge_source_version_id,
            ),
        )
    )

    engine = HybridKnowledgeRetrievalEngine(catalog=catalog)
    old_candidates = _query(
        engine,
        release_id=release_v1.release.knowledge_base_release_id,
        question="等待期 三十天",
    )
    new_candidates = _query(
        engine,
        release_id=release_v2.release.knowledge_base_release_id,
        question="等待期 十五天",
    )
    old_release_new_term = _query(
        engine,
        release_id=release_v1.release.knowledge_base_release_id,
        question="十五天",
    )

    assert markdown_v1.original_artifact.sha256 != markdown_v2.original_artifact.sha256
    assert release_v1.release.knowledge_base_release_id != (
        release_v2.release.knowledge_base_release_id
    )
    assert "三十天" in old_candidates[0]["content"]["text"]  # type: ignore[index]
    assert old_candidates[0]["citation_locator"] == {  # type: ignore[index]
        "kind": "text_lines",
        "start_line": 2,
        "end_line": 2,
    }
    assert "十五天" in new_candidates[0]["content"]["text"]  # type: ignore[index]
    assert all(
        "十五天" not in candidate["content"]["text"]  # type: ignore[index]
        for candidate in old_release_new_term
    )

    keys = artifacts.keys()
    assert any("/originals/" in key for key in keys)
    assert any("/canonical/" in key for key in keys)
    assert any(key.endswith("/evidence-unit-manifest.json") for key in keys)
    assert any(key.endswith("/release-manifest.json") for key in keys)
    assert all("客户上传" not in key and ".." not in key for key in keys)


def test_html_intake_removes_active_content_and_preserves_dom_citation() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    catalog = InMemoryKnowledgeCatalog()
    intake = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024 * 1024,
    )
    published = intake.create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-insurance",
            knowledge_source_id="source-html-policy",
            display_filename="policy.html",
            media_type="text/html",
            content=(
                "<!doctype html>\n"
                "<html><head><script>steal-secret-token</script></head>\n"
                "<body><h1>Flight policy</h1>\n"
                "<p>Flight delay benefit is 300 CNY after four hours.</p>\n"
                "</body></html>\n"
            ).encode(),
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

    candidates = _query(
        HybridKnowledgeRetrievalEngine(catalog=catalog),
        release_id=release.release.knowledge_base_release_id,
        question="flight delay four hours benefit",
    )

    assert candidates[0]["content"]["text"] == (  # type: ignore[index]
        "Flight delay benefit is 300 CNY after four hours."
    )
    assert candidates[0]["citation_locator"] == {  # type: ignore[index]
        "kind": "html_dom",
        "dom_path": "/html[1]/body[1]/p[1]",
    }
    canonical = artifacts.get_exact(published.canonical_artifact).decode()
    assert "steal-secret-token" not in canonical
