"""Integration tests for the global approval queue API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proof_agent.contracts.dashboard import RunIndex
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.api.app import create_app


@pytest.fixture
def app(tmp_path: Path):
    return create_app(history_dir=tmp_path / "history")


@pytest.fixture
def client(app):
    return TestClient(app)


def _seed_pending_approval(
    app,
    *,
    run_id: str,
    approval_id: str,
    question: str,
    expires_at: str,
    agent_id: str | None = "enterprise_qa",
) -> None:
    from proof_agent.observability.storage.run_store import RunStore

    store: RunStore = app.state.store
    index = RunIndex(
        run_id=run_id,
        question=question,
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        agent_id=agent_id,
        agent_version_id="version_1",
        created_at="2026-06-10T10:00:00Z",
        updated_at="2026-06-10T10:00:10Z",
    )
    store.write_run_meta(index)
    run_dir = store.create_run_dir(run_id)
    events = [
        {
            "schema_version": "trace.v1",
            "run_id": run_id,
            "event_id": f"evt_{run_id}_1",
            "sequence": 1,
            "timestamp": "2026-06-10T10:00:00Z",
            "event_type": "pending_approval_created",
            "span_id": "span_pending_approval_created",
            "status": "waiting",
            "payload": {
                "run_id": run_id,
                "thread_id": f"thread_{run_id}",
                "approval_id": approval_id,
                "action_id": "act_customer_lookup",
                "tool_name": "customer_lookup",
                "parameters": {"customer_id": "C-100", "policy_id": "P-200"},
                "policy_decision": "require_approval",
                "checkpoint_id": f"checkpoint_{run_id}",
                "status": "requested",
                "created_at": "2026-06-10T10:00:00Z",
                "expires_at": expires_at,
            },
            "redaction": {"applied": False, "fields": []},
        }
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")


def test_list_approvals_returns_pending_approval_projection_sorted_by_expiry(client, app) -> None:
    _seed_pending_approval(
        app,
        run_id="run_later",
        approval_id="appr_later",
        question="Later approval",
        expires_at="2099-06-10T10:05:00Z",
    )
    _seed_pending_approval(
        app,
        run_id="run_earlier",
        approval_id="appr_earlier",
        question="Earlier approval",
        expires_at="2099-06-10T10:01:00Z",
    )

    resp = client.get("/api/approvals")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"] == {"total": 2, "limit": 50, "offset": 0}
    assert [item["approval_id"] for item in body["data"]] == ["appr_earlier", "appr_later"]
    first = body["data"][0]
    assert first == {
        "run_id": "run_earlier",
        "approval_id": "appr_earlier",
        "tool_name": "customer_lookup",
        "action_id": "act_customer_lookup",
        "question": "Earlier approval",
        "agent_id": "enterprise_qa",
        "agent_version_id": "version_1",
        "run_purpose": "production",
        "created_at": "2026-06-10T10:00:00Z",
        "expires_at": "2099-06-10T10:01:00Z",
        "expired": False,
        "parameter_keys": ["customer_id", "policy_id"],
        "parameter_count": 2,
        "links": {"run_detail": "/api/runs/run_earlier"},
    }
    assert "parameters" not in first


def test_list_approvals_marks_expired_without_writing_trace(client, app) -> None:
    _seed_pending_approval(
        app,
        run_id="run_expired",
        approval_id="appr_expired",
        question="Expired approval",
        expires_at="2000-01-01T00:00:00Z",
    )
    before = client.get("/api/runs/run_expired/trace").json()["event_count"]

    resp = client.get("/api/approvals")

    assert resp.status_code == 200
    item = resp.json()["data"][0]
    assert item["approval_id"] == "appr_expired"
    assert item["expired"] is True
    after_trace = client.get("/api/runs/run_expired/trace").json()
    assert after_trace["event_count"] == before
    assert [event["event_type"] for event in after_trace["events"]] == [
        "pending_approval_created"
    ]


def test_list_approvals_paginates_after_filtering(client, app) -> None:
    for index, approval_id in enumerate(("appr_1", "appr_2", "appr_3"), start=1):
        _seed_pending_approval(
            app,
            run_id=f"run_{index}",
            approval_id=approval_id,
            question=f"Approval {index}",
            expires_at=f"2099-06-10T10:0{index}:00Z",
        )

    resp = client.get("/api/approvals?limit=1&offset=1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["meta"] == {"total": 3, "limit": 1, "offset": 1}
    assert [item["approval_id"] for item in body["data"]] == ["appr_2"]


def test_list_approvals_rejects_invalid_pagination(client) -> None:
    resp = client.get("/api/approvals?limit=0")

    assert resp.status_code == 422
