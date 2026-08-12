from __future__ import annotations

from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


def test_structured_query_groups_and_aggregates_with_typed_order_and_citation() -> None:
    catalog = InMemoryKnowledgeCatalog()
    dataset = catalog.add_csv_dataset(
        knowledge_space_id="space-analysis",
        knowledge_source_id="source-claims",
        content=(
            "region,claim_total,active\n"
            "east,100.25,true\n"
            "east,200.75,true\n"
            "west,50.00,true\n"
            "west,999.00,false\n"
        ),
        field_types={
            "region": "string",
            "claim_total": "decimal",
            "active": "boolean",
        },
    )
    release = catalog.publish_release(
        knowledge_space_id="space-analysis",
        knowledge_base_id="base-analysis",
        knowledge_source_version_ids=(dataset.knowledge_source_version_id,),
    )
    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "active claim totals by region",
            "query_constraints": {
                "structured_queries": [
                    {
                        "dataset_revision_id": dataset.dataset_revision_id,
                        "projections": [],
                        "filters": [
                            {"field": "active", "operator": "eq", "value": True}
                        ],
                        "group_by": ["region"],
                        "aggregations": [
                            {
                                "function": "sum",
                                "field": "claim_total",
                                "output_field": "total",
                            },
                            {
                                "function": "count",
                                "field": None,
                                "output_field": "claim_count",
                            },
                        ],
                        "sort": [
                            {
                                "field": "total",
                                "direction": "desc",
                                "nulls": "last",
                            }
                        ],
                        "limit": 10,
                    }
                ]
            },
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 100,
                "max_duration_ms": 1000,
            },
            "deadline_at": "2026-08-12T04:00:00Z",
        }
    )

    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=request,
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-analysis",
                client_grant_id="grant-analysis",
                effective_access_scope_digest=f"sha256:{'d' * 64}",
            ),
        )
    )

    assert result.query_plan_summary.structured_query_count == 1
    group = result.evidence_groups[0]
    assert group.group_type == "structured"
    assert group.ordering.fields == ("total desc nulls last",)
    assert [
        [
            (field.field, field.value_type, field.value)
            for field in candidate.content.structured_data.fields
        ]
        for candidate in group.candidate_evidence
    ] == [
        [
            ("region", "string", "east"),
            ("total", "decimal", "301.00"),
            ("claim_count", "integer", 2),
        ],
        [
            ("region", "string", "west"),
            ("total", "decimal", "50.00"),
            ("claim_count", "integer", 1),
        ],
    ]
    citation = group.candidate_evidence[0].citation_locator
    assert citation.kind == "dataset_aggregate"
    assert citation.dataset_revision_id == dataset.dataset_revision_id
    assert citation.input_record_count == 2
    assert citation.input_set_digest.startswith("sha256:")


def test_legacy_structured_filter_compares_decimal_values_numerically() -> None:
    catalog = InMemoryKnowledgeCatalog()
    dataset = catalog.add_csv_dataset(
        knowledge_space_id="space-decimal",
        knowledge_source_id="source-decimal",
        content="amount\n2.00\n10.00\n",
        field_types={"amount": "decimal"},
    )
    release = catalog.publish_release(
        knowledge_space_id="space-decimal",
        knowledge_base_id="base-decimal",
        knowledge_source_version_ids=(dataset.knowledge_source_version_id,),
    )

    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "amount greater than nine",
                    "query_constraints": {
                        "filters": [
                            {"field": "amount", "operator": "gt", "value": "9.00"}
                        ]
                    },
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 100,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T04:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-decimal",
                client_grant_id="grant-decimal",
                effective_access_scope_digest=f"sha256:{'e' * 64}",
            ),
        )
    )

    values = result.evidence_groups[0].candidate_evidence[0].content.structured_data.fields
    assert values[0].value == "10.00"
