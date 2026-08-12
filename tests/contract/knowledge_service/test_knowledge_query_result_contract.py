from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_source_service.contracts.knowledge_query import KnowledgeQuery
from knowledge_source_service.contracts.results import KnowledgeQueryResult


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _mixed_result_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query-result.v1",
        "evidence_groups": [
            {
                "evidence_group_id": "relevance-group-1",
                "group_type": "relevance_ranked",
                "ordering": {
                    "kind": "relevance",
                    "final_rank_field": "fused_rank",
                },
                "candidate_evidence": [],
            },
            {
                "evidence_group_id": "structured-group-1",
                "group_type": "structured",
                "ordering": {
                    "kind": "typed",
                    "fields": ["claim_year asc"],
                },
                "candidate_evidence": [],
            },
        ],
        "query_plan_summary": {
            "plan_revision": 1,
            "planned_lanes": ["lexical", "sparse", "dense", "structured"],
            "structured_query_count": 1,
            "plan_digest": _digest("a"),
        },
        "execution_summary": {
            "strategy": "agentic",
            "rounds": 2,
            "stop_reason": "coverage_complete",
            "degraded": False,
            "budget_usage": {
                "rounds": 2,
                "model_calls": 4,
                "candidates": 40,
                "model_tokens": 2_000,
                "duration_ms": 2_500,
            },
        },
        "retrieval_lineage": {
            "knowledge_base_release_id": "release-opaque-id",
            "release_manifest_digest": _digest("b"),
            "access_scope_digest": _digest("c"),
            "plan_revision_digests": [_digest("d"), _digest("e")],
        },
    }


def _relevance_candidate() -> dict[str, Any]:
    return {
        "candidate_evidence_id": "candidate-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "knowledge_base_version_id": "base-version-1",
        "knowledge_base_release_id": "release-opaque-id",
        "knowledge_source_id": "source-1",
        "knowledge_source_version_id": "source-version-1",
        "evidence_unit_id": "evidence-unit-1",
        "content": {
            "media_type": "text/plain",
            "text": "理赔总额同比增长 12%。",
        },
        "content_hash": _digest("f"),
        "citation_locator": {
            "kind": "text_lines",
            "start_line": 10,
            "end_line": 12,
        },
        "context_evidence_units": [],
        "ranking": {
            "kind": "relevance",
            "lane_contributions": [
                {
                    "lane": "lexical",
                    "native_score": 7.25,
                    "lane_rank": 1,
                    "weight": 1.0,
                    "rrf_contribution": 0.01639,
                },
                {
                    "lane": "dense",
                    "native_score": 0.83,
                    "lane_rank": 2,
                    "weight": 0.8,
                    "rrf_contribution": 0.0129,
                },
            ],
            "fused_rank": 1,
            "reranked_rank": 1,
        },
        "retrieval_lineage": {
            "retrieval_round": 1,
            "plan_revision": 1,
            "index_identity": "knowledge-index-1",
            "query_digest": _digest("1"),
            "access_scope_digest": _digest("c"),
        },
    }


def _structured_candidate() -> dict[str, Any]:
    return {
        "candidate_evidence_id": "candidate-structured-1",
        "knowledge_space_id": "space-1",
        "knowledge_base_id": "base-1",
        "knowledge_base_version_id": "base-version-1",
        "knowledge_base_release_id": "release-opaque-id",
        "knowledge_source_id": "source-tabular-1",
        "knowledge_source_version_id": "source-tabular-version-1",
        "evidence_unit_id": "dataset-record-unit-1",
        "content": {
            "media_type": "application/vnd.knowledge.structured-record+json",
            "text": "claim_year=2025, claim_total=12345.67",
            "structured_data": {
                "schema_revision_id": "dataset-schema-1",
                "fields": [
                    {"field": "claim_year", "value_type": "integer", "value": 2025},
                    {
                        "field": "claim_total",
                        "value_type": "decimal",
                        "value": "12345.67",
                    },
                ],
            },
        },
        "content_hash": _digest("3"),
        "citation_locator": {
            "kind": "dataset_records",
            "dataset_revision_id": "dataset-revision-1",
            "record_ids": ["claim-record-2025"],
            "typed_query_digest": _digest("4"),
            "input_set_digest": _digest("5"),
        },
        "context_evidence_units": [],
        "ranking": {
            "kind": "structured",
            "structured_order": 1,
        },
        "retrieval_lineage": {
            "retrieval_round": 1,
            "plan_revision": 1,
            "index_identity": "dataset-index-1",
            "query_digest": _digest("4"),
            "access_scope_digest": _digest("c"),
        },
    }


def _succeeded_query_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query.v1",
        "knowledge_query_id": "query-1",
        "knowledge_base_release_id": "release-opaque-id",
        "state": "succeeded",
        "submitted_at": "2026-08-11T10:29:10Z",
        "started_at": "2026-08-11T10:29:11Z",
        "completed_at": "2026-08-11T10:29:18Z",
        "deadline_at": "2026-08-11T10:30:00Z",
        "cancel_requested_at": None,
        "result_availability": "available",
        "result_expires_at": "2026-08-12T10:29:18Z",
        "result": _mixed_result_payload(),
        "problem": None,
        "links": {
            "self": "/v1/knowledge-queries/query-1",
            "cancel": "/v1/knowledge-queries/query-1:cancel",
        },
    }


def test_mixed_result_keeps_relevance_and_structured_ordering_separate() -> None:
    payload = _mixed_result_payload()

    result = KnowledgeQueryResult.model_validate(payload)

    assert result.model_dump(mode="json") == payload


def test_relevance_candidate_requires_exact_source_version_provenance() -> None:
    payload = _mixed_result_payload()
    candidate = _relevance_candidate()
    del candidate["knowledge_source_version_id"]
    payload["evidence_groups"][0]["candidate_evidence"] = [candidate]

    with pytest.raises(ValidationError) as captured:
        KnowledgeQueryResult.model_validate(payload)

    assert any(
        error["loc"][-1] == "knowledge_source_version_id"
        for error in captured.value.errors()
    )


def test_context_evidence_unit_requires_its_own_citation_locator() -> None:
    payload = _mixed_result_payload()
    candidate = _relevance_candidate()
    candidate["context_evidence_units"] = [
        {
            "relation": "heading_path",
            "knowledge_source_id": "source-1",
            "knowledge_source_version_id": "source-version-1",
            "evidence_unit_id": "heading-unit-1",
            "content": {"media_type": "text/plain", "text": "年度理赔分析"},
            "content_hash": _digest("2"),
            "retrieval_lineage": {
                "retrieval_round": 1,
                "plan_revision": 1,
                "index_identity": "knowledge-index-1",
                "query_digest": _digest("1"),
                "access_scope_digest": _digest("c"),
            },
        }
    ]
    payload["evidence_groups"][0]["candidate_evidence"] = [candidate]

    with pytest.raises(ValidationError) as captured:
        KnowledgeQueryResult.model_validate(payload)

    assert any(error["loc"][-1] == "citation_locator" for error in captured.value.errors())


def test_structured_candidate_preserves_typed_values_and_structured_order() -> None:
    payload = _mixed_result_payload()
    payload["evidence_groups"][1]["candidate_evidence"] = [_structured_candidate()]

    result = KnowledgeQueryResult.model_validate(payload)

    assert result.model_dump(mode="json") == payload


def test_structured_field_values_must_match_their_declared_types() -> None:
    payload = _mixed_result_payload()
    candidate = _structured_candidate()
    candidate["content"]["structured_data"]["fields"] = [
        {"field": "text_value", "value_type": "string", "value": 1},
        {"field": "integer_value", "value_type": "integer", "value": "1"},
        {"field": "decimal_value", "value_type": "decimal", "value": 1.2},
        {"field": "boolean_value", "value_type": "boolean", "value": "true"},
        {"field": "date_value", "value_type": "date", "value": "2025-13-01"},
        {
            "field": "datetime_value",
            "value_type": "datetime",
            "value": "2025-01-01T00:00:00",
        },
        {"field": "null_value", "value_type": "null", "value": "not-null"},
    ]
    payload["evidence_groups"][1]["candidate_evidence"] = [candidate]

    with pytest.raises(ValidationError) as captured:
        KnowledgeQueryResult.model_validate(payload)

    invalid_fields = {
        error["input"].get("field")
        for error in captured.value.errors()
        if isinstance(error["input"], dict)
    }
    assert invalid_fields == {
        "text_value",
        "integer_value",
        "decimal_value",
        "boolean_value",
        "date_value",
        "datetime_value",
        "null_value",
    }


def test_result_rejects_candidate_from_another_knowledge_base_release() -> None:
    payload = _mixed_result_payload()
    candidate = _relevance_candidate()
    candidate["knowledge_base_release_id"] = "another-release"
    payload["evidence_groups"][0]["candidate_evidence"] = [candidate]

    with pytest.raises(ValidationError, match="exact result release"):
        KnowledgeQueryResult.model_validate(payload)


def test_succeeded_knowledge_query_exposes_one_typed_available_result() -> None:
    payload = _succeeded_query_payload()

    query = KnowledgeQuery.model_validate(payload)

    assert query.model_dump(mode="json") == payload


def test_non_succeeded_knowledge_query_cannot_expose_a_result() -> None:
    payload = _succeeded_query_payload()
    payload["state"] = "running"
    payload["completed_at"] = None
    payload["result_availability"] = "pending"

    with pytest.raises(ValidationError, match="only a succeeded available Query"):
        KnowledgeQuery.model_validate(payload)


def test_available_result_requires_content_and_a_retention_expiry() -> None:
    payload = _succeeded_query_payload()
    payload["result"] = None
    payload["result_expires_at"] = None

    with pytest.raises(ValidationError, match="available result requires content and expiry"):
        KnowledgeQuery.model_validate(payload)


def test_execution_state_rejects_an_incompatible_result_availability() -> None:
    payload = _succeeded_query_payload()
    payload.update(
        {
            "state": "cancelled",
            "cancel_requested_at": "2026-08-11T10:29:17Z",
            "result_availability": "expired",
            "result": None,
        }
    )

    with pytest.raises(ValidationError, match="result_availability is incompatible"):
        KnowledgeQuery.model_validate(payload)
