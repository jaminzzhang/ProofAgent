"""Integration tests for /api/health endpoint."""

from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


@pytest.fixture
def client(tmp_path: Path):
    app = create_app(history_dir=tmp_path / "history")
    return TestClient(app)


def test_health_returns_ok(client) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "total_runs" in body


def test_health_reflects_zero_runs(client) -> None:
    resp = client.get("/api/health")
    assert resp.json()["total_runs"] == 0
