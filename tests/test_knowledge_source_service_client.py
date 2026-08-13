from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.capabilities.knowledge.source_service_client import (
    KnowledgeSourceServiceClient,
)
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
)
from proof_agent.control.knowledge.retrieval_service import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalService,
)
from proof_agent.control.policy.engine import PolicyEngine
from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.errors import ProofAgentError
from proof_agent.observability.audit.trace import TraceWriter


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _result_payload() -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query-result.v1",
        "evidence_groups": [
            {
                "evidence_group_id": "relevance-group-1",
                "group_type": "relevance_ranked",
                "ordering": {"kind": "relevance", "final_rank_field": "fused_rank"},
                "candidate_evidence": [
                    {
                        "candidate_evidence_id": "candidate-doc-1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                        "knowledge_base_version_id": "base-version-1",
                        "knowledge_base_release_id": "release-1",
                        "knowledge_source_id": "source-doc-1",
                        "knowledge_source_version_id": "source-doc-version-1",
                        "evidence_unit_id": "unit-1",
                        "content": {"media_type": "text/plain", "text": "极端天气。"},
                        "content_hash": _digest("a"),
                        "citation_locator": {
                            "kind": "text_lines",
                            "start_line": 2,
                            "end_line": 2,
                        },
                        "context_evidence_units": [],
                        "ranking": {
                            "kind": "relevance",
                            "lane_contributions": [
                                {
                                    "lane": "lexical",
                                    "native_score": 3.0,
                                    "lane_rank": 1,
                                    "weight": 1.0,
                                    "rrf_contribution": 0.01639,
                                }
                            ],
                            "fused_rank": 1,
                            "reranked_rank": None,
                        },
                        "retrieval_lineage": {
                            "retrieval_round": 1,
                            "plan_revision": 1,
                            "index_identity": "index-1",
                            "query_digest": _digest("b"),
                            "access_scope_digest": _digest("c"),
                        },
                    }
                ],
            },
            {
                "evidence_group_id": "structured-group-1",
                "group_type": "structured",
                "ordering": {"kind": "typed", "fields": ["claim_year asc"]},
                "candidate_evidence": [
                    {
                        "candidate_evidence_id": "candidate-row-1",
                        "knowledge_space_id": "space-1",
                        "knowledge_base_id": "base-1",
                        "knowledge_base_version_id": "base-version-1",
                        "knowledge_base_release_id": "release-1",
                        "knowledge_source_id": "source-table-1",
                        "knowledge_source_version_id": "source-table-version-1",
                        "evidence_unit_id": "row-unit-1",
                        "content": {
                            "media_type": (
                                "application/vnd.knowledge.structured-record+json"
                            ),
                            "text": "claim_year=2025, claim_total=12345.67",
                            "structured_data": {
                                "schema_revision_id": "schema-1",
                                "fields": [
                                    {
                                        "field": "claim_year",
                                        "value_type": "integer",
                                        "value": 2025,
                                    },
                                    {
                                        "field": "claim_total",
                                        "value_type": "decimal",
                                        "value": "12345.67",
                                    },
                                ],
                            },
                        },
                        "content_hash": _digest("d"),
                        "citation_locator": {
                            "kind": "dataset_records",
                            "dataset_revision_id": "dataset-1",
                            "record_ids": ["record-1"],
                            "typed_query_digest": _digest("e"),
                            "input_set_digest": _digest("f"),
                        },
                        "context_evidence_units": [],
                        "ranking": {"kind": "structured", "structured_order": 1},
                        "retrieval_lineage": {
                            "retrieval_round": 1,
                            "plan_revision": 1,
                            "index_identity": "dataset-1",
                            "query_digest": _digest("e"),
                            "access_scope_digest": _digest("c"),
                        },
                    }
                ],
            },
        ],
        "query_plan_summary": {
            "plan_revision": 1,
            "planned_lanes": ["lexical", "structured"],
            "structured_query_count": 1,
            "plan_digest": _digest("1"),
        },
        "execution_summary": {
            "strategy": "single_pass",
            "rounds": 1,
            "stop_reason": "single_pass_complete",
            "degraded": False,
            "budget_usage": {
                "rounds": 1,
                "model_calls": 0,
                "candidates": 2,
                "model_tokens": 0,
                "duration_ms": 20,
            },
        },
        "retrieval_lineage": {
            "knowledge_base_release_id": "release-1",
            "release_manifest_digest": _digest("2"),
            "access_scope_digest": _digest("c"),
            "plan_revision_digests": [_digest("1")],
        },
    }


def _query_resource(*, state: str, result: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": "knowledge-query.v1",
        "knowledge_query_id": "query-1",
        "knowledge_base_release_id": "release-1",
        "state": state,
        "submitted_at": "2026-08-12T09:00:00Z",
        "started_at": "2026-08-12T09:00:01Z" if state == "succeeded" else None,
        "completed_at": "2026-08-12T09:00:02Z" if state == "succeeded" else None,
        "deadline_at": "2026-08-12T09:01:00Z",
        "cancel_requested_at": None,
        "result_availability": "available" if state == "succeeded" else "pending",
        "result_expires_at": "2026-08-13T09:00:02Z" if state == "succeeded" else None,
        "result": result,
        "problem": None,
        "links": {
            "self": "/v1/knowledge-queries/query-1",
            "cancel": "/v1/knowledge-queries/query-1:cancel",
        },
    }


class ScriptedGuardedHttpClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = [
            GuardedHttpResponse(
                status_code=202,
                headers={"Location": "/v1/knowledge-queries/query-1", "Retry-After": "0"},
                body=json.dumps(_query_resource(state="queued", result=None)).encode(),
            ),
            GuardedHttpResponse(
                status_code=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps(
                    _query_resource(state="succeeded", result=_result_payload())
                ).encode(),
            ),
        ]

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Any = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses.pop(0)


def test_client_creates_polls_and_preserves_typed_candidate_evidence() -> None:
    http = ScriptedGuardedHttpClient()
    client = KnowledgeSourceServiceClient(
        endpoint="https://knowledge.internal",
        http_client=http,
        authorization_header_factory=lambda: "Bearer service-client-token",
        sleep=lambda _seconds: None,
        max_polls=2,
    )
    request = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-1:retrieval-1:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "理赔增长原因和 2025 年理赔总额",
            "strategy": "single_pass",
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
            "deadline_at": datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
        }
    )

    result = client.query(request)

    assert [call["method"] for call in http.calls] == ["POST", "GET"]
    assert http.calls[0]["url"] == "https://knowledge.internal/v1/knowledge-queries"
    assert http.calls[1]["url"] == (
        "https://knowledge.internal/v1/knowledge-queries/query-1"
    )
    assert http.calls[0]["headers"]["Idempotency-Key"] == request.idempotency_key
    assert result.knowledge_query_id == "query-1"
    assert result.retrieval_lineage.knowledge_base_release_id == "release-1"
    relevance = result.evidence_groups[0].candidate_evidence[0]
    assert relevance.knowledge_source_version_id == "source-doc-version-1"
    assert relevance.content_hash == _digest("a")
    assert relevance.citation_locator.start_line == 2
    assert not hasattr(relevance, "admission_score")
    structured = result.evidence_groups[1].candidate_evidence[0]
    assert structured.content.structured_data.fields[1].value == "12345.67"
    assert structured.citation_locator.record_ids == ("record-1",)


def test_proof_agent_contract_preserves_structured_aggregate_citation() -> None:
    payload = _result_payload()
    candidate = payload["evidence_groups"][1]["candidate_evidence"][0]
    candidate["content"]["media_type"] = (
        "application/vnd.knowledge.structured-aggregate+json"
    )
    candidate["citation_locator"] = {
        "kind": "dataset_aggregate",
        "dataset_revision_id": "dataset-1",
        "typed_query_digest": _digest("e"),
        "input_predicate_digest": _digest("7"),
        "input_record_count": 25,
        "input_set_digest": _digest("f"),
    }

    result = KnowledgeCandidateResult.model_validate(
        {"knowledge_query_id": "query-1", **payload}
    )

    citation = result.evidence_groups[1].candidate_evidence[0].citation_locator
    assert citation.kind == "dataset_aggregate"
    assert citation.input_record_count == 25


def test_proof_agent_query_preserves_bounded_structured_query_spec() -> None:
    query = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-1:retrieval-2:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "totals by region",
            "query_constraints": {
                "structured_queries": [
                    {
                        "dataset_revision_id": "dataset-1",
                        "group_by": ["region"],
                        "aggregations": [
                            {
                                "function": "sum",
                                "field": "claim_total",
                                "output_field": "total",
                            }
                        ],
                        "sort": [{"field": "total", "direction": "desc"}],
                        "limit": 20,
                    }
                ]
            },
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 20,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": "2026-08-12T09:01:00Z",
        }
    )

    spec = query.model_dump(mode="json")["query_constraints"][
        "structured_queries"
    ][0]
    assert spec["schema_version"] == "bounded-structured-query.v1"
    assert spec["aggregations"][0]["function"] == "sum"
    assert "backend_query" not in spec


class StaticCandidateService:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.requests: list[KnowledgeCandidateQuery] = []
        self._payload = payload or _result_payload()

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult:
        self.requests.append(request)
        return KnowledgeCandidateResult.model_validate(
            {"knowledge_query_id": "query-1", **self._payload}
        )


class StaticCandidateAdmissionScorer:
    scorer_id = "approved-test-scorer"
    scorer_revision = "approved-test-scorer.v1"

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.requests: list[tuple[KnowledgeCandidateQuery, KnowledgeCandidateResult]] = []

    def score_candidates(
        self,
        *,
        query: KnowledgeCandidateQuery,
        result: KnowledgeCandidateResult,
    ) -> dict[str, float]:
        self.requests.append((query, result))
        return self.scores


class ForbiddenLegacyProvider:
    provider_name = "legacy-must-not-run"
    capabilities = RetrievalCapabilities(supports_parallel_retrieval=True)

    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[Any, ...]:
        self.calls += 1
        raise AssertionError("local Knowledge fallback must not run")


def test_control_plane_routes_exact_query_without_flattening_structured_groups(
    tmp_path: Any,
) -> None:
    candidate_service = StaticCandidateService()
    legacy_provider = ForbiddenLegacyProvider()
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run-1"),
        policy=PolicyEngine(()),
        knowledge_provider=legacy_provider,
        knowledge_candidate_service=candidate_service,
    )
    candidate_query = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-1:retrieval-1:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "理赔增长原因和 2025 年理赔总额",
            "strategy": "single_pass",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
        }
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question=candidate_query.question,
            strategy="single_step",
            top_k=10,
            min_score=0.0,
            knowledge_candidate_query=candidate_query,
        )
    )

    assert candidate_service.requests == [candidate_query]
    assert legacy_provider.calls == 0
    assert result.candidate_result is not None
    assert [group.group_type for group in result.candidate_result.evidence_groups] == [
        "relevance_ranked",
        "structured",
    ]
    assert len(result.evidence) == 1
    assert result.evidence[0].status.value == "candidate"
    assert result.evidence[0].admission_score is None
    assert result.evidence[0].metadata["knowledge_candidate_group_type"] == (
        "relevance_ranked"
    )
    structured = result.candidate_result.evidence_groups[1].candidate_evidence[0]
    assert structured.content.structured_data.fields[0].value == 2025
    assert result.evidence_result.status == "failed"


def test_control_plane_applies_an_explicit_candidate_admission_scorer(
    tmp_path: Any,
) -> None:
    candidate_service = StaticCandidateService()
    admission_scorer = StaticCandidateAdmissionScorer({"candidate-doc-1": 0.84})
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run-1"),
        policy=PolicyEngine(()),
        knowledge_provider=ForbiddenLegacyProvider(),
        knowledge_candidate_service=candidate_service,
        knowledge_candidate_admission_scorer=admission_scorer,
    )
    candidate_query = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-1:retrieval-1:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "理赔增长原因和 2025 年理赔总额",
            "strategy": "single_pass",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
        }
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question=candidate_query.question,
            strategy="single_step",
            top_k=10,
            min_score=0.5,
            knowledge_candidate_query=candidate_query,
        )
    )

    assert len(admission_scorer.requests) == 1
    assert admission_scorer.requests[0][0] == candidate_query
    assert result.evidence[0].admission_score == 0.84
    assert result.evidence[0].metadata["admission_scorer"] == {
        "scorer_id": "approved-test-scorer",
        "scorer_revision": "approved-test-scorer.v1",
    }
    assert result.evidence_result.status == "passed"


def test_control_plane_rejects_an_invalid_candidate_admission_score(
    tmp_path: Any,
) -> None:
    candidate_service = StaticCandidateService()
    admission_scorer = StaticCandidateAdmissionScorer({"candidate-doc-1": 1.01})
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run-1"),
        policy=PolicyEngine(()),
        knowledge_provider=ForbiddenLegacyProvider(),
        knowledge_candidate_service=candidate_service,
        knowledge_candidate_admission_scorer=admission_scorer,
    )
    candidate_query = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-1:retrieval-1:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "理赔增长原因和 2025 年理赔总额",
            "strategy": "single_pass",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
        }
    )

    with pytest.raises(ProofAgentError) as exc:
        service.retrieve(
            KnowledgeRetrievalRequest(
                question=candidate_query.question,
                strategy="single_step",
                top_k=10,
                min_score=0.5,
                knowledge_candidate_query=candidate_query,
            )
        )

    assert exc.value.code == "PA_KNOWLEDGE_001"
    assert "approved normalized range" in str(exc.value)


@pytest.mark.parametrize(
    ("locator", "fragment"),
    (
        ({"kind": "text_lines", "start_line": 2, "end_line": 3}, "text-lines=2-3"),
        ({"kind": "pdf_page", "page_number": 4}, "pdf-page=4"),
        (
            {"kind": "docx_paragraph", "paragraph_number": 5},
            "docx-paragraph=5",
        ),
        (
            {
                "kind": "docx_table_cell",
                "table_number": 2,
                "row_number": 3,
                "column_number": 4,
            },
            "docx-table-cell=2.3.4",
        ),
        (
            {"kind": "pptx_shape", "slide_number": 6, "shape_id": 17},
            "pptx-shape=6.17",
        ),
        (
            {"kind": "html_dom", "dom_path": "main/article[1]"},
            "html-dom=main%2Farticle%5B1%5D",
        ),
        (
            {
                "kind": "ocr_region",
                "page_number": 7,
                "bounding_box": {
                    "x_min": 10,
                    "y_min": 20,
                    "x_max": 110,
                    "y_max": 220,
                },
            },
            "ocr-region=7,10,20,110,220",
        ),
    ),
)
def test_control_plane_preserves_document_locator_in_candidate_citation(
    tmp_path: Any,
    locator: dict[str, Any],
    fragment: str,
) -> None:
    payload = _result_payload()
    payload["evidence_groups"][0]["candidate_evidence"][0][
        "citation_locator"
    ] = locator
    candidate_service = StaticCandidateService(payload)
    service = KnowledgeRetrievalService(
        trace=TraceWriter(tmp_path / "trace.jsonl", run_id="run-pdf"),
        policy=PolicyEngine(()),
        knowledge_provider=ForbiddenLegacyProvider(),
        knowledge_candidate_service=candidate_service,
    )
    candidate_query = KnowledgeCandidateQuery.model_validate(
        {
            "idempotency_key": "run-pdf:retrieval-1:attempt-1",
            "knowledge_base_release_id": "release-1",
            "question": "PDF policy",
            "execution_budget": {
                "max_rounds": 1,
                "max_model_calls": 1,
                "max_candidates": 10,
                "max_model_tokens": 1000,
                "max_duration_ms": 1000,
            },
            "deadline_at": datetime(2026, 8, 12, 9, 1, tzinfo=UTC),
        }
    )

    result = service.retrieve(
        KnowledgeRetrievalRequest(
            question="PDF policy",
            strategy="single_step",
            top_k=10,
            min_score=0.0,
            knowledge_candidate_query=candidate_query,
        )
    )

    assert result.evidence[0].citation == (
        "knowledge://space-1/release-1/source-doc-version-1/unit-1#" + fragment
    )
