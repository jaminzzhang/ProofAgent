"""Integration tests for /api/stats endpoint."""

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


def _seed(app, run_id: str, outcome: ReceiptOutcome) -> None:
    from proof_agent.observability.storage.run_store import RunStore

    store: RunStore = app.state.store
    store.write_run_meta(RunIndex(
        run_id=run_id,
        question=f"Q for {run_id}",
        outcome=outcome,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    ))


def test_stats_empty(client, app) -> None:
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 0
    assert body["outcome_distribution"] == {}


def test_stats_with_runs(client, app) -> None:
    _seed(app, "run_001", ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    _seed(app, "run_002", ReceiptOutcome.ANSWERED_WITH_CITATIONS)
    _seed(app, "run_003", ReceiptOutcome.REFUSED_NO_EVIDENCE)

    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_runs"] == 3
    assert body["outcome_distribution"]["ANSWERED_WITH_CITATIONS"] == 2
    assert body["outcome_distribution"]["REFUSED_NO_EVIDENCE"] == 1
