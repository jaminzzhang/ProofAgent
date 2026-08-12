from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest


def _valid_request_payload() -> dict[str, Any]:
    return {
        "knowledge_base_release_id": "release-opaque-id",
        "question": "2025 年理赔总额及其主要增长原因是什么？",
        "strategy": "agentic",
        "query_constraints": {
            "as_of": "2025-12-31T23:59:59+08:00",
            "filters": [],
            "structured_queries": [],
        },
        "access_narrowing_context": {
            "assertion_token": "signed-opaque-assertion",
        },
        "execution_budget": {
            "max_rounds": 3,
            "max_model_calls": 6,
            "max_candidates": 200,
            "max_model_tokens": 12_000,
            "max_duration_ms": 30_000,
        },
        "deadline_at": "2026-08-11T10:30:00Z",
    }


def test_create_knowledge_query_request_accepts_the_exact_v1_shape() -> None:
    request = CreateKnowledgeQueryRequest.model_validate(_valid_request_payload())

    assert request.model_dump(mode="json") == {
        "knowledge_base_release_id": "release-opaque-id",
        "question": "2025 年理赔总额及其主要增长原因是什么？",
        "strategy": "agentic",
        "query_constraints": {
            "as_of": "2025-12-31T23:59:59+08:00",
            "filters": [],
            "structured_queries": [],
        },
        "access_narrowing_context": {
            "assertion_token": "signed-opaque-assertion",
        },
        "execution_budget": {
            "max_rounds": 3,
            "max_model_calls": 6,
            "max_candidates": 200,
            "max_model_tokens": 12_000,
            "max_duration_ms": 30_000,
        },
        "deadline_at": "2026-08-11T10:30:00Z",
    }


def test_create_knowledge_query_request_rejects_unknown_top_level_fields() -> None:
    payload = _valid_request_payload()
    payload["knowledge_space_id"] = "caller-controlled-space"

    with pytest.raises(ValidationError):
        CreateKnowledgeQueryRequest.model_validate(payload)


def test_create_knowledge_query_request_allows_omitting_access_narrowing_context() -> None:
    payload = _valid_request_payload()
    del payload["access_narrowing_context"]

    request = CreateKnowledgeQueryRequest.model_validate(payload)

    assert request.access_narrowing_context is None


def test_create_knowledge_query_request_rejects_unknown_nested_fields() -> None:
    payload = _valid_request_payload()
    payload["query_constraints"]["backend_query"] = "SELECT * FROM private_table"
    payload["access_narrowing_context"]["knowledge_space_id"] = "caller-space"
    payload["execution_budget"]["max_cost"] = 1

    with pytest.raises(ValidationError) as captured:
        CreateKnowledgeQueryRequest.model_validate(payload)

    assert {error["loc"] for error in captured.value.errors()} == {
        ("query_constraints", "backend_query"),
        ("access_narrowing_context", "knowledge_space_id"),
        ("execution_budget", "max_cost"),
    }


def test_create_knowledge_query_request_rejects_naive_constraint_and_deadline_times() -> None:
    payload = _valid_request_payload()
    payload["query_constraints"]["as_of"] = "2025-12-31T23:59:59"
    payload["deadline_at"] = "2026-08-11T10:30:00"

    with pytest.raises(ValidationError) as captured:
        CreateKnowledgeQueryRequest.model_validate(payload)

    assert {error["loc"] for error in captured.value.errors()} == {
        ("query_constraints", "as_of"),
        ("deadline_at",),
    }


def test_create_knowledge_query_request_requires_positive_execution_budget_limits() -> None:
    payload = _valid_request_payload()
    payload["execution_budget"] = {
        "max_rounds": 0,
        "max_model_calls": -1,
        "max_candidates": 0,
        "max_model_tokens": -1,
        "max_duration_ms": 0,
    }

    with pytest.raises(ValidationError) as captured:
        CreateKnowledgeQueryRequest.model_validate(payload)

    assert {error["loc"] for error in captured.value.errors()} == {
        ("execution_budget", "max_rounds"),
        ("execution_budget", "max_model_calls"),
        ("execution_budget", "max_candidates"),
        ("execution_budget", "max_model_tokens"),
        ("execution_budget", "max_duration_ms"),
    }


def test_create_knowledge_query_request_rejects_blank_release_question_and_assertion() -> None:
    payload = _valid_request_payload()
    payload["knowledge_base_release_id"] = ""
    payload["question"] = "   "
    payload["access_narrowing_context"]["assertion_token"] = ""

    with pytest.raises(ValidationError) as captured:
        CreateKnowledgeQueryRequest.model_validate(payload)

    assert {error["loc"] for error in captured.value.errors()} == {
        ("knowledge_base_release_id",),
        ("question",),
        ("access_narrowing_context", "assertion_token"),
    }


def test_create_knowledge_query_request_defaults_to_single_pass_strategy() -> None:
    payload = _valid_request_payload()
    del payload["strategy"]

    request = CreateKnowledgeQueryRequest.model_validate(payload)

    assert request.strategy == "single_pass"


def test_create_knowledge_query_request_defaults_to_empty_typed_constraints() -> None:
    payload = _valid_request_payload()
    del payload["query_constraints"]

    request = CreateKnowledgeQueryRequest.model_validate(payload)

    assert request.query_constraints.as_of is None
    assert request.query_constraints.filters == ()
    assert request.query_constraints.structured_queries == ()


def test_create_knowledge_query_request_rejects_backend_native_filter_objects() -> None:
    payload = _valid_request_payload()
    payload["query_constraints"]["filters"] = [
        {"backend_query": {"term": {"private_acl": "*"}}}
    ]

    with pytest.raises(ValidationError):
        CreateKnowledgeQueryRequest.model_validate(payload)
