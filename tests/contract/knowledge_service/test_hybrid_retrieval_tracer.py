from __future__ import annotations

from datetime import UTC, datetime

from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


def test_markdown_and_csv_share_one_release_without_losing_evidence_semantics() -> None:
    catalog = InMemoryKnowledgeCatalog()
    document = catalog.add_document(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-claims-analysis",
        media_type="text/markdown",
        content=(
            "# 年度理赔分析\n"
            "2025 年理赔总额为 12345.67 元，主要增长原因是极端天气。\n"
        ),
    )
    dataset = catalog.add_csv_dataset(
        knowledge_space_id="space-insurance",
        knowledge_source_id="source-claims-ledger",
        content=(
            "claim_year,claim_total,currency\n"
            "2024,11000.00,CNY\n"
            "2025,12345.67,CNY\n"
        ),
        field_types={
            "claim_year": "integer",
            "claim_total": "decimal",
            "currency": "string",
        },
    )
    release = catalog.publish_release(
        knowledge_space_id="space-insurance",
        knowledge_base_id="base-insurance",
        knowledge_source_version_ids=(
            document.knowledge_source_version_id,
            dataset.knowledge_source_version_id,
        ),
    )
    engine = HybridKnowledgeRetrievalEngine(catalog=catalog)
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "理赔 极端天气",
            "query_constraints": {
                "filters": [
                    {"field": "claim_year", "operator": "eq", "value": 2025}
                ]
            },
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        }
    )

    result = engine.retrieve(
        AdmittedKnowledgeQuery(
            request=request,
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-insurance",
                client_grant_id="grant-proof-agent",
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    payload = result.model_dump(mode="json")
    assert [group["group_type"] for group in payload["evidence_groups"]] == [
        "relevance_ranked",
        "structured",
    ]
    relevance = payload["evidence_groups"][0]["candidate_evidence"]
    assert len(relevance) == 1
    assert relevance[0]["knowledge_source_version_id"] == (
        document.knowledge_source_version_id
    )
    assert relevance[0]["citation_locator"] == {
        "kind": "text_lines",
        "start_line": 2,
        "end_line": 2,
    }
    assert "极端天气" in relevance[0]["content"]["text"]
    assert {lane["lane"] for lane in relevance[0]["ranking"]["lane_contributions"]} == {
        "lexical",
        "sparse",
        "dense",
    }

    structured = payload["evidence_groups"][1]["candidate_evidence"]
    assert len(structured) == 1
    assert structured[0]["knowledge_source_version_id"] == dataset.knowledge_source_version_id
    assert structured[0]["content"]["structured_data"]["fields"] == [
        {"field": "claim_year", "value_type": "integer", "value": 2025},
        {"field": "claim_total", "value_type": "decimal", "value": "12345.67"},
        {"field": "currency", "value_type": "string", "value": "CNY"},
    ]
    assert structured[0]["citation_locator"]["record_ids"] == [dataset.record_ids[1]]
    assert result.retrieval_lineage.knowledge_base_release_id == (
        release.knowledge_base_release_id
    )
    assert result.retrieval_lineage.access_scope_digest == f"sha256:{'a' * 64}"

    bounded_request = request.model_copy(
        update={
            "execution_budget": request.execution_budget.model_copy(
                update={"max_candidates": 1}
            )
        }
    )
    bounded = engine.retrieve(
        AdmittedKnowledgeQuery(
            request=bounded_request,
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-insurance",
                client_grant_id="grant-proof-agent",
                effective_access_scope_digest=f"sha256:{'a' * 64}",
            ),
        )
    )

    assert sum(
        len(group.candidate_evidence) for group in bounded.evidence_groups
    ) == 1
