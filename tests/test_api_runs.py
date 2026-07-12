"""Integration tests for /api/runs endpoints via FastAPI TestClient."""

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app
from proof_agent.contracts.dashboard import RunIndex
from proof_agent.contracts.receipt import ReceiptOutcome


@pytest.fixture
def app(tmp_path: Path):
    return create_app(history_dir=tmp_path / "history")


@pytest.fixture
def client(app):
    return TestClient(app)


def _seed(client_fixture, app, run_id: str, outcome: ReceiptOutcome, question: str) -> None:
    """Seed a run via the store directly."""
    from proof_agent.observability.storage.run_store import RunStore

    store: RunStore = app.state.store
    index = RunIndex(
        run_id=run_id,
        question=question,
        outcome=outcome,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)
    run_dir = store.create_run_dir(run_id)
    (run_dir / "trace.jsonl").write_text(
        '{"event_type":"run_started","run_id":"' + run_id + '"}\n', encoding="utf-8"
    )
    (run_dir / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")


def test_list_runs_empty(client, app) -> None:
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert body["meta"]["total"] == 0


def test_list_runs_with_data(client, app) -> None:
    _seed(client, app, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed(client, app, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    resp = client.get("/api/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 2
    assert len(body["data"]) == 2


def test_list_runs_filter_outcome(client, app) -> None:
    _seed(client, app, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q1")
    _seed(client, app, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "Q2")

    resp = client.get("/api/runs?outcome=ANSWERED_WITH_CITATIONS")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["run_id"] == "run_001"


def test_policy_denied_outcome_round_trips_through_run_api(client, app) -> None:
    _seed(client, app, "run_policy_denied", ReceiptOutcome.POLICY_DENIED, "Q")
    _seed(client, app, "run_answered", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q2")

    detail_resp = client.get("/api/runs/run_policy_denied")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["outcome"] == "POLICY_DENIED"

    list_resp = client.get("/api/runs?outcome=POLICY_DENIED")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["run_id"] == "run_policy_denied"
    assert body["data"][0]["outcome"] == "POLICY_DENIED"


def test_list_runs_search(client, app) -> None:
    _seed(client, app, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "discount policy")
    _seed(client, app, "run_002", ReceiptOutcome.REFUSED_NO_EVIDENCE, "remote work")

    resp = client.get("/api/runs?search=discount")
    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"]["total"] == 1


def test_get_run_detail(client, app) -> None:
    _seed(client, app, "run_abc", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Test question")

    resp = client.get("/api/runs/run_abc")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run_abc"
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert body["question"] == "Test question"


def test_get_run_detail_not_found(client, app) -> None:
    resp = client.get("/api/runs/run_nosuch")
    assert resp.status_code == 404


def test_get_run_trace(client, app) -> None:
    _seed(client, app, "run_trace", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q")

    resp = client.get("/api/runs/run_trace/trace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == "run_trace"
    assert body["event_count"] == 1


def test_get_run_receipt(client, app) -> None:
    _seed(client, app, "run_receipt", ReceiptOutcome.ANSWERED_WITH_CITATIONS, "Q")

    resp = client.get("/api/runs/run_receipt/receipt")
    assert resp.status_code == 200
    body = resp.json()
    assert body["receipt_markdown"] == "# Receipt"


def test_invalid_outcome_filter(client, app) -> None:
    resp = client.get("/api/runs?outcome=INVALID")
    assert resp.status_code == 400
