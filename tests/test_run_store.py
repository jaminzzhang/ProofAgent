"""Tests for RunStore: CRUD, filtering, pagination, stats."""

import json
from pathlib import Path

import pytest

from proof_agent.contracts.dashboard import RunIndex
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.storage.run_store import RunStore


@pytest.fixture
def store(tmp_path: Path) -> RunStore:
    """Create a RunStore with a temporary history directory."""
    return RunStore(tmp_path / "history")


def _write_trace(path: Path, run_id: str, events: list[dict]) -> None:
    """Write synthetic trace events as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({**e, "run_id": run_id}) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_receipt(path: Path, content: str = "# Receipt\nOutcome: ANSWERED") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _seed_run(store: RunStore, run_id: str, outcome: ReceiptOutcome, question: str) -> RunIndex:
    """Create a minimal run directory with trace, receipt, and metadata."""
    run_dir = store.create_run_dir(run_id)
    _write_trace(
        run_dir / "trace.jsonl",
        run_id,
        [
            {"event_type": "run_started", "sequence": 1, "timestamp": "2026-05-10T14:32:18Z"},
            {"event_type": "final_output", "sequence": 2, "timestamp": "2026-05-10T14:32:19Z",
             "payload": {"outcome": outcome.value, "question": question}},
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    index = RunIndex(
        run_id=run_id,
        question=question,
        outcome=outcome,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)
    return index


def test_create_run_dir(store: RunStore) -> None:
    run_dir = store.create_run_dir("run_test001")
    assert run_dir.is_dir()
    assert run_dir.name == "run_test001"


def test_create_run_dir_idempotent(store: RunStore) -> None:
    store.create_run_dir("run_test001")
    store.create_run_dir("run_test001")  # should not raise


def test_write_and_load_run_meta(store: RunStore) -> None:
    index = RunIndex(
        run_id="run_abc123",
        question="What discount?",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)

    detail = store.get_run_detail("run_abc123")
    assert detail is not None
    assert detail.run_id == "run_abc123"
    assert detail.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS


def test_get_run_detail_nonexistent(store: RunStore) -> None:
    assert store.get_run_detail("run_nosuch") is None


def test_list_runs_empty(store: RunStore) -> None:
    runs, total = store.list_runs()
    assert total == 0
    assert runs == []


def test_list_runs_returns_seeded(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs()
    assert total == 2
    assert len(runs) == 2


def test_list_runs_filter_by_outcome(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs(outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    assert total == 1
    assert runs[0].run_id == "run_001"


def test_list_runs_search_by_question(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "discount policy")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "remote work")

    runs, total = store.list_runs(search="discount")
    assert total == 1
    assert runs[0].run_id == "run_001"


def test_list_runs_search_by_run_id(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    runs, total = store.list_runs(search="run_002")
    assert total == 1
    assert runs[0].run_id == "run_002"


def test_list_runs_pagination(store: RunStore) -> None:
    for i in range(5):
        _seed_run(store, f"run_{i:03d}", ReceiptOutcome.ANSWERED_WITH_CITATIONS, f"Q{i}")

    page1, total = store.list_runs(limit=2, offset=0)
    assert total == 5
    assert len(page1) == 2

    page2, _ = store.list_runs(limit=2, offset=2)
    assert len(page2) == 2

    page3, _ = store.list_runs(limit=2, offset=4)
    assert len(page3) == 1


def test_get_stats(store: RunStore) -> None:
    _seed_run(store, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed_run(store, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")
    _seed_run(store, "run_003", ReceiptOutcome.WAITING_FOR_APPROVAL, "Q3")

    stats = store.get_stats()
    assert stats["total_runs"] == 3
    assert stats["outcome_distribution"]["ANSWERED_WITH_CITATIONS"] == 1
    assert stats["outcome_distribution"]["REFUSED_NO_EVIDENCE"] == 1
    assert stats["outcome_distribution"]["WAITING_FOR_APPROVAL"] == 1


def test_save_run_artifacts(store: RunStore, tmp_path: Path) -> None:
    trace_src = tmp_path / "trace.jsonl"
    receipt_src = tmp_path / "governance_receipt.md"
    _write_trace(trace_src, "run_copied", [
        {"event_type": "run_started", "sequence": 1, "timestamp": "2026-05-10T14:32:18Z"},
    ])
    _write_receipt(receipt_src, "# Receipt\nCopied run")

    index = store.save_run_artifacts(
        "run_copied",
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Test question",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
    )
    assert index.run_id == "run_copied"

    detail = store.get_run_detail("run_copied")
    assert detail is not None
    assert detail.receipt_markdown.startswith("# Receipt")
    assert len(detail.trace_events) == 1


def test_get_run_detail_with_trace_events(store: RunStore) -> None:
    _seed_run(store, "run_detailed", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Detailed question")

    detail = store.get_run_detail("run_detailed")
    assert detail is not None
    assert len(detail.trace_events) == 2
    assert detail.trace_events[0]["event_type"] == "run_started"


def test_get_run_detail_extracts_evidence_summary(store: RunStore) -> None:
    run_dir = store.create_run_dir("run_evidence")
    _write_trace(
        run_dir / "trace.jsonl",
        "run_evidence",
        [
            {
                "event_type": "retrieval_result",
                "sequence": 1,
                "timestamp": "2026-05-10T14:32:18Z",
                "payload": {"sources": ["policy://travel#meals"], "chunk_count": 1},
            },
            {
                "event_type": "evidence_evaluation",
                "sequence": 2,
                "timestamp": "2026-05-10T14:32:19Z",
                "payload": {
                    "metadata": {
                        "evidence": [
                            {
                                "source": "policy://travel#meals",
                                "citation": "travel-policy.md#meals:L10-L18",
                                "score": 0.84,
                                "status": "accepted",
                            }
                        ]
                    }
                },
            },
            {
                "event_type": "final_output",
                "sequence": 3,
                "timestamp": "2026-05-10T14:32:20Z",
                "payload": {
                    "outcome": ReceiptOutcome.ANSWERED_WITH_CITATIONS.value,
                    "question": "Travel meals?",
                },
            },
        ],
    )
    _write_receipt(run_dir / "governance_receipt.md")
    store.write_run_meta(
        RunIndex(
            run_id="run_evidence",
            question="Travel meals?",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:20Z",
        )
    )

    detail = store.get_run_detail("run_evidence")

    assert detail is not None
    assert detail.evidence_chunks[0]["citation"] == "travel-policy.md#meals:L10-L18"
    assert "content" not in detail.evidence_chunks[0]
