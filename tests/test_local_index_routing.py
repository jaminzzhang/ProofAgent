"""Tests for bounded Local Index snapshot document routing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from proof_agent.capabilities.knowledge.local_index_routing import (
    MAX_ROUTING_METADATA_SCALAR_CHARS,
    MAX_ROUTING_METADATA_SCALARS,
    MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES,
    route_snapshot_documents,
)
from proof_agent.capabilities.knowledge.local_index_snapshot import LocalIndexRuntimeDocument
from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.errors import ProofAgentError


class FakeRoutingModel:
    provider_name = "fake"
    model_name = "routing-model"

    def __init__(self, content: str = '{"selected_document_ids":[],"reason":"none"}') -> None:
        self.content = content
        self.requests: list[ModelRequest] = []
        self.error: Exception | None = None

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return None

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return ModelResponse(
            content=self.content,
            provider_name=self.provider_name,
            model_name=self.model_name,
        )


def _document(
    document_id: str,
    *,
    filename: str | None = None,
    routing_metadata: dict[str, object] | None = None,
) -> LocalIndexRuntimeDocument:
    return LocalIndexRuntimeDocument(
        document_id=document_id,
        revision_id=f"rev_{document_id}",
        filename=filename or f"{document_id}.md",
        content_type="text/markdown",
        content_hash="a" * 64,
        artifact_path=Path("/private/artifacts") / document_id,
        routing_metadata=routing_metadata or {},
    )


def _request_payload(model: FakeRoutingModel) -> dict[str, object]:
    assert len(model.requests) == 1
    assert model.requests[0].response_format == "json"
    system_message, user_message = model.requests[0].messages
    assert system_message.content.count("JSON object") == 1
    assert "selected_document_ids" in system_message.content
    assert "Do not echo the input JSON" in system_message.content
    return json.loads(user_message.content)


def test_document_router_selects_metadata_matches_without_model_when_within_budget() -> None:
    model = FakeRoutingModel('{"selected_document_ids":["doc_travel"],"reason":"wrong"}')

    result = route_snapshot_documents(
        "claim reimbursement",
        documents=(
            _document("doc_travel", filename="travel-policy.md"),
            _document(
                "doc_claims",
                filename="claims-guide.md",
                routing_metadata={"tags": ["claim"], "ignored": "must-not-leak"},
            ),
        ),
        routing_model=model,
        selection_budget=8,
        snapshot_id="kssnapshot_001",
    )

    assert model.requests == []
    assert [document.document_id for document in result.selected_documents] == ["doc_claims"]
    assert result.summary["document_candidates"] == [
        {
            "document_id": "doc_claims",
            "revision_id": "rev_doc_claims",
            "filename": "claims-guide.md",
            "routing_metadata_keys": ["tags"],
            "metadata_matched": True,
            "selection_reason": "metadata_match",
        }
    ]
    assert result.summary["selected_documents"] == [
        {
            "document_id": "doc_claims",
            "revision_id": "rev_doc_claims",
            "selection_reason": "metadata_match_selected",
        }
    ]
    assert result.summary["document_routing"]["selection_reason"] == (
        "metadata_match_selected"
    )


def test_document_router_matches_cjk_metadata_without_model() -> None:
    model = FakeRoutingModel('{"selected_document_ids":["doc_other"],"reason":"wrong"}')

    result = route_snapshot_documents(
        "我买平安御享一生终身寿险保单过期了怎么办",
        documents=(
            _document(
                "doc_policy",
                filename="policy.md",
                routing_metadata={"title": "平安御享一生终身寿险"},
            ),
            _document("doc_other", filename="general-faq.md"),
        ),
        routing_model=model,
        selection_budget=3,
        snapshot_id="kssnapshot_cjk",
    )

    assert model.requests == []
    assert [document.document_id for document in result.selected_documents] == ["doc_policy"]
    assert result.summary["document_candidates"][0]["metadata_matched"] is True
    assert result.summary["document_routing"]["selection_reason"] == (
        "metadata_match_selected"
    )


def test_document_router_sends_only_metadata_matches_when_match_count_exceeds_budget() -> None:
    model = FakeRoutingModel('{"selected_document_ids":["doc_claims"],"reason":"match"}')

    result = route_snapshot_documents(
        "claim reimbursement",
        documents=(
            _document(
                "doc_claims",
                filename="claims-guide.md",
                routing_metadata={"tags": ["claim"], "ignored": "must-not-leak"},
            ),
            _document(
                "doc_refunds",
                filename="refunds-guide.md",
                routing_metadata={"tags": ["claim"]},
            ),
            _document("doc_travel", filename="travel-policy.md"),
        ),
        routing_model=model,
        selection_budget=1,
        snapshot_id="kssnapshot_001",
    )

    payload = _request_payload(model)
    candidates = payload["document_candidates"]
    assert isinstance(candidates, list)
    assert [item["document_id"] for item in candidates] == [
        "doc_claims",
        "doc_refunds",
    ]
    assert candidates[0]["routing_metadata"] == {"tags": ["claim"]}
    assert [document.document_id for document in result.selected_documents] == ["doc_claims"]
    assert result.summary["document_candidates"][0]["metadata_matched"] is True


def test_document_router_falls_back_to_sorted_full_set_when_metadata_does_not_match() -> None:
    model = FakeRoutingModel()

    result = route_snapshot_documents(
        "invoice dispute",
        documents=(
            _document("doc_zeta", filename="travel-policy.md"),
            _document("doc_alpha", routing_metadata={"tags": ["claim"]}),
        ),
        routing_model=model,
        selection_budget=8,
        snapshot_id="kssnapshot_001",
    )

    payload = _request_payload(model)
    assert model.requests[0].timeout_seconds == 30.0
    assert [item["document_id"] for item in payload["document_candidates"]] == [
        "doc_alpha",
        "doc_zeta",
    ]
    assert result.summary["document_routing"]["selection_reason"] == "routing_empty"


def test_document_router_truncates_stable_candidate_page_and_records_summary() -> None:
    model = FakeRoutingModel('{"selected_document_ids":["doc_000"],"reason":"first"}')
    documents = tuple(_document(f"doc_{index:03d}") for index in reversed(range(101)))

    result = route_snapshot_documents(
        "unmatched",
        documents=documents,
        routing_model=model,
        selection_budget=3,
        snapshot_id="kssnapshot_001",
    )

    payload = _request_payload(model)
    assert len(payload["document_candidates"]) == MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES
    assert payload["document_candidates"][0]["document_id"] == "doc_000"
    assert payload["document_candidates"][-1]["document_id"] == "doc_099"
    assert result.summary["document_routing"] == {
        "snapshot_id": "kssnapshot_001",
        "candidate_count": 101,
        "routed_candidate_count": 100,
        "selected_count": 1,
        "candidate_truncated": True,
        "selection_budget": 3,
        "selection_reason": "routing_model_selected",
    }


def test_document_router_bounds_safe_filename_and_metadata_projection() -> None:
    values = [f"value-{index}" for index in range(MAX_ROUTING_METADATA_SCALARS + 3)]
    values[0] = "x" * (MAX_ROUTING_METADATA_SCALAR_CHARS + 10)
    model = FakeRoutingModel()
    document = _document(
        "doc_policy",
        filename="/private/contracts/policy.md",
        routing_metadata={
            "title": values,
            "description": {"nested": "claims"},
            "ignored": "must-not-leak",
        },
    )

    result = route_snapshot_documents(
        "unmatched",
        documents=(document,),
        routing_model=model,
        selection_budget=8,
        snapshot_id="kssnapshot_001",
    )

    payload = _request_payload(model)
    candidate = payload["document_candidates"][0]
    assert candidate["filename"] == "policy.md"
    assert set(candidate["routing_metadata"]) == {"title"}
    assert len(candidate["routing_metadata"]["title"]) == MAX_ROUTING_METADATA_SCALARS
    assert len(candidate["routing_metadata"]["title"][0]) == MAX_ROUTING_METADATA_SCALAR_CHARS
    serialized_summary = json.dumps(result.summary)
    assert "/private/contracts" not in serialized_summary
    assert "/private/artifacts" not in serialized_summary
    assert "must-not-leak" not in serialized_summary


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        '{"selected_document_ids":["doc_unknown"],"reason":"x"}',
        '{"selected_document_ids":["doc_a","doc_a"],"reason":"x"}',
        '{"selected_document_ids":["doc_a","doc_b"],"reason":"x"}',
        '{"selected_document_ids":[],"reason":"x","unexpected":true}',
    ],
)
def test_document_router_rejects_invalid_model_output(content: str) -> None:
    model = FakeRoutingModel(content)

    with pytest.raises(ProofAgentError) as exc:
        route_snapshot_documents(
            "query",
            documents=(_document("doc_a"), _document("doc_b")),
            routing_model=model,
            selection_budget=1,
            snapshot_id="kssnapshot_001",
        )

    assert exc.value.code == "PA_KNOWLEDGE_002"
    assert content not in str(exc.value)


def test_document_router_valid_empty_selection_is_trace_safe() -> None:
    model = FakeRoutingModel('{"selected_document_ids":[],"reason":"secret model reason"}')

    result = route_snapshot_documents(
        "query",
        documents=(_document("doc_a"),),
        routing_model=model,
        selection_budget=1,
        snapshot_id="kssnapshot_001",
    )

    assert result.selected_documents == ()
    assert result.summary["selected_documents"] == []
    assert result.summary["document_routing"]["selection_reason"] == "routing_empty"
    assert "secret model reason" not in json.dumps(result.summary)


def test_document_router_wraps_model_failure_without_leaking_exception_text() -> None:
    model = FakeRoutingModel()
    model.error = RuntimeError("credential-like model failure")

    with pytest.raises(ProofAgentError) as exc:
        route_snapshot_documents(
            "query",
            documents=(_document("doc_a"),),
            routing_model=model,
            selection_budget=1,
            snapshot_id="kssnapshot_001",
        )

    assert exc.value.code == "PA_KNOWLEDGE_002"
    assert "credential-like" not in str(exc.value)


def test_document_router_model_failure_preserves_bounded_candidate_summary() -> None:
    model = FakeRoutingModel()
    model.error = RuntimeError("credential-like model failure")
    documents = tuple(_document(f"doc_{index:03d}") for index in reversed(range(101)))

    with pytest.raises(ProofAgentError) as exc:
        route_snapshot_documents(
            "unmatched",
            documents=documents,
            routing_model=model,
            selection_budget=3,
            snapshot_id="kssnapshot_001",
        )

    summary = exc.value.summary
    assert len(summary["document_candidates"]) == MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES
    assert summary["document_routing"] == {
        "snapshot_id": "kssnapshot_001",
        "candidate_count": 101,
        "routed_candidate_count": 100,
        "selected_count": 0,
        "candidate_truncated": True,
        "selection_budget": 3,
        "selection_reason": "routing_model_failed",
        "error_code": "PA_KNOWLEDGE_002",
    }


def test_document_router_preserves_policy_denial_code_and_summary() -> None:
    model = FakeRoutingModel()
    policy_error = ProofAgentError(
        "PA_POLICY_001",
        "Knowledge routing model call was blocked by policy.",
        "Update policy or configure an allowed Source routing model.",
    )
    model.error = policy_error

    with pytest.raises(ProofAgentError) as exc:
        route_snapshot_documents(
            "unmatched",
            documents=(_document("doc_policy"),),
            routing_model=model,
            selection_budget=3,
            snapshot_id="kssnapshot_001",
        )

    assert exc.value.code == "PA_POLICY_001"
    summary = exc.value.summary
    assert summary["document_candidates"] == [
        {
            "document_id": "doc_policy",
            "revision_id": "rev_doc_policy",
            "filename": "doc_policy.md",
            "routing_metadata_keys": [],
            "metadata_matched": False,
            "selection_reason": "metadata_fallback",
        }
    ]
    assert summary["document_routing"]["selection_reason"] == "routing_model_failed"
    assert summary["document_routing"]["error_code"] == "PA_POLICY_001"
