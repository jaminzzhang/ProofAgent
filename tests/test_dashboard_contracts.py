"""Tests for dashboard-facing contracts: RunSummary, RunDetail, RunIndex."""

import pytest
from pydantic import ValidationError

from proof_agent.contracts import ReceiptOutcome, RunDetail, RunIndex, RunSummary
from proof_agent.observability.api.serializers import serialize_run_detail


def test_run_summary_construction() -> None:
    summary = RunSummary(
        run_id="run_abc123",
        question="What is the discount policy?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    assert summary.run_id == "run_abc123"
    assert summary.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert summary.approval_status is None
    assert summary.error_code is None


def test_run_summary_with_optional_fields() -> None:
    from proof_agent.contracts import ApprovalStatus

    summary = RunSummary(
        run_id="run_def456",
        question="Check customer status",
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
        approval_status=ApprovalStatus.REQUESTED,
        error_code=None,
    )
    assert summary.approval_status == ApprovalStatus.REQUESTED


def test_run_summary_is_frozen() -> None:
    summary = RunSummary(
        run_id="run_abc123",
        question="What?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    with pytest.raises(ValidationError):
        summary.run_id = "changed"  # type: ignore[misc]


def test_run_detail_construction() -> None:
    detail = RunDetail(
        run_id="run_abc123",
        question="What is the discount policy?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
        trace_events=({"event_type": "run_started", "status": "ok"},),
        receipt_markdown="# Receipt\n\nOutcome: ANSWERED",
        evidence_chunks=({"source": "policy.md", "status": "accepted"},),
        policy_decisions=({"decision": "allow", "reason": "evidence sufficient"},),
        model_usage={"provider": "deterministic", "model": "demo"},
    )
    assert len(detail.trace_events) == 1
    assert detail.receipt_markdown.startswith("# Receipt")
    assert detail.approval_state is None
    assert detail.governance_details == {}


def test_run_detail_accepts_governance_details() -> None:
    detail = RunDetail(
        run_id="run_abc123",
        question="What is the travel meal rule?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
        governance_details={
            "reasoning_summary": {"selected_action": "plan_retrieval"},
            "review_results": [{"final_decision": "allow"}],
        },
    )

    assert detail.governance_details["reasoning_summary"]
    assert detail.governance_details["review_results"]


def test_serialize_run_detail_includes_governance_details() -> None:
    detail = RunDetail(
        run_id="run_abc123",
        question="What is the travel meal rule?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
        governance_details={"reasoning_summary": {"selected_action": "plan_retrieval"}},
    )

    serialized = serialize_run_detail(detail)

    assert serialized["governance_details"] == detail.governance_details


def test_run_detail_is_frozen() -> None:
    detail = RunDetail(
        run_id="run_abc123",
        question="What?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    with pytest.raises(ValidationError):
        detail.run_id = "changed"  # type: ignore[misc]


def test_run_index_construction() -> None:
    index = RunIndex(
        run_id="run_abc123",
        question="What is the discount policy?",
        outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
        error_code="PA_MODEL_001",
    )
    assert index.error_code == "PA_MODEL_001"


def test_run_index_is_frozen() -> None:
    index = RunIndex(
        run_id="run_abc123",
        question="What?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    with pytest.raises(ValidationError):
        index.run_id = "changed"  # type: ignore[misc]
