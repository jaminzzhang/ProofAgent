"""Regression coverage for the typed ISSUE-007 evidence API boundary."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from proof_agent.contracts import ReceiptOutcome, RunDetail
from proof_agent.delivery.api import _run_response
from proof_agent.delivery.customer_api import _safe_sources
from proof_agent.observability.api.serializers import serialize_run_detail


def _chunk(**updates: Any) -> Any:
    from proof_agent.contracts import DashboardEvidenceChunk

    values = {
        "index": 7,
        "source": "policy://travel#meals",
        "status": "accepted",
        "evidence_id": "evidence_meals",
        "source_id": "ks_travel",
        "binding_id": "binding_travel",
        "provider_native_score": 0.91,
        "admission_score": 0.84,
        "fusion_rank": 1,
        "citation": "travel-policy.md#meals:L10-L18",
    }
    values.update(updates)
    return DashboardEvidenceChunk(**values)


def _detail(chunk: Any) -> RunDetail:
    return RunDetail(
        run_id="run_evidence",
        question="Travel meals?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-07-11T00:00:00Z",
        updated_at="2026-07-11T00:00:01Z",
        evidence_chunks=(chunk,),
    )


def test_dashboard_evidence_contract_is_frozen_and_bounds_index_for_javascript() -> None:
    chunk = _chunk()

    with pytest.raises(ValidationError):
        chunk.index = 8

    with pytest.raises(ValidationError):
        _chunk(index=9_007_199_254_740_992)


def test_run_detail_serializes_evidence_projection_explicitly_to_plain_json() -> None:
    serialized = serialize_run_detail(_detail(_chunk()))

    assert serialized["evidence_chunks"] == [
        {
            "index": 7,
            "source": "policy://travel#meals",
            "status": "accepted",
            "evidence_id": "evidence_meals",
            "source_id": "ks_travel",
            "source_version_id": None,
            "binding_id": "binding_travel",
            "provider_name": None,
            "document_id": None,
            "revision_id": None,
            "chunk_id": None,
            "admission_score": 0.84,
            "provider_native_score": 0.91,
            "fusion_rank": 1.0,
            "citation": "travel-policy.md#meals:L10-L18",
        }
    ]
    assert json.loads(json.dumps(serialized))["evidence_chunks"] == serialized["evidence_chunks"]


def test_chat_run_response_preserves_typed_evidence_fields_as_plain_payload() -> None:
    detail = _detail(_chunk())

    response = _run_response(
        agent_id="enterprise_qa",
        detail=detail,
        manifest=SimpleNamespace(response=None),
        final_output="Meals are reimbursed.",
    )

    assert response["evidence"][0]["index"] == 7
    assert response["evidence"][0]["source"] == "policy://travel#meals"
    assert response["evidence"][0]["citation"] == "travel-policy.md#meals:L10-L18"
    assert response["evidence"][0]["provider_native_score"] == 0.91
    assert "content" not in response["evidence"][0]
    json.dumps(response)


def test_customer_safe_source_projection_accepts_typed_evidence() -> None:
    detail = _detail(
        _chunk(
            source="travel-policy.md",
            source_id=None,
            binding_id=None,
            citation="travel-policy.md#meals:L10-L18",
        )
    )

    assert _safe_sources(detail) == ("travel-policy.md",)
