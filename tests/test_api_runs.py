"""Integration tests for /api/runs endpoints via FastAPI TestClient."""

import json
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


def _seed_pending_approval(
    app,
    run_id: str,
    approval_id: str,
    *,
    created_at: str = "2026-05-10T14:32:18Z",
    expires_at: str = "2099-05-10T14:33:18Z",
) -> None:
    """Seed a run with one unresolved PendingApproval trace snapshot."""

    from proof_agent.observability.storage.run_store import RunStore

    store: RunStore = app.state.store
    index = RunIndex(
        run_id=run_id,
        question="Look up customer policy status before answering.",
        outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
        created_at="2026-05-10T14:32:18Z",
        updated_at="2026-05-10T14:32:19Z",
    )
    store.write_run_meta(index)
    run_dir = store.create_run_dir(run_id)
    events = [
        {
            "schema_version": "trace.v1",
            "run_id": run_id,
            "event_id": "evt_0001",
            "sequence": 1,
            "timestamp": "2026-05-10T14:32:18Z",
            "event_type": "approval_requested",
            "span_id": "span_approval_requested",
            "status": "waiting",
            "payload": {
                "approval_id": approval_id,
                "tool_name": "customer_lookup",
            },
            "redaction": {"applied": False, "fields": []},
        },
        {
            "schema_version": "trace.v1",
            "run_id": run_id,
            "event_id": "evt_0002",
            "sequence": 2,
            "timestamp": "2026-05-10T14:32:18Z",
            "event_type": "pending_approval_created",
            "span_id": "span_pending_approval_created",
            "status": "waiting",
            "payload": {
                "run_id": run_id,
                "thread_id": "thread_test",
                "approval_id": approval_id,
                "action_id": "act_customer_lookup",
                "tool_name": "customer_lookup",
                "parameters": {"customer_id": "C-100"},
                "policy_decision": {
                    "decision": "require_approval",
                    "policy_rule_id": "tool_requires_approval",
                    "reason": "Customer lookup is approval-gated.",
                },
                "checkpoint_id": "checkpoint_test",
                "status": "pending",
                "created_at": created_at,
                "expires_at": expires_at,
            },
            "redaction": {"applied": False, "fields": []},
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
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


def test_approve_pending_approval_appends_trace_event_and_clears_projection(
    client,
    app,
) -> None:
    _seed_pending_approval(app, "run_pending", "appr_customer_lookup")

    resp = client.post("/api/runs/run_pending/approvals/appr_customer_lookup/approve")

    assert resp.status_code == 200
    body = resp.json()
    assert body["approval_state"]["state"] == "granted"
    assert body["approval_state"]["approval_id"] == "appr_customer_lookup"
    assert body["pending_approvals"] == []

    trace = client.get("/api/runs/run_pending/trace").json()
    last_event = trace["events"][-1]
    assert last_event["event_type"] == "approval_granted"
    assert last_event["payload"]["approval_id"] == "appr_customer_lookup"
    assert last_event["payload"]["tool_name"] == "customer_lookup"
    assert last_event["payload"]["actor"] == "local-user"


def test_approval_resolution_ignores_frontend_supplied_actor(client, app) -> None:
    _seed_pending_approval(app, "run_pending", "appr_customer_lookup")

    resp = client.post(
        "/api/runs/run_pending/approvals/appr_customer_lookup/approve",
        json={"actor": "customer-user"},
    )

    assert resp.status_code == 200
    trace = client.get("/api/runs/run_pending/trace").json()
    last_event = trace["events"][-1]
    assert last_event["payload"]["actor"] == "local-user"


def test_deny_pending_approval_appends_trace_event_and_clears_projection(
    client,
    app,
) -> None:
    _seed_pending_approval(app, "run_pending", "appr_customer_lookup")

    resp = client.post("/api/runs/run_pending/approvals/appr_customer_lookup/deny")

    assert resp.status_code == 200
    body = resp.json()
    assert body["approval_state"]["state"] == "denied"
    assert body["approval_state"]["approval_id"] == "appr_customer_lookup"
    assert body["pending_approvals"] == []


def test_resolving_unknown_pending_approval_returns_404(client, app) -> None:
    _seed_pending_approval(app, "run_pending", "appr_customer_lookup")

    resp = client.post("/api/runs/run_pending/approvals/appr_missing/approve")

    assert resp.status_code == 404


def test_resolving_already_terminal_pending_approval_returns_409(client, app) -> None:
    _seed_pending_approval(app, "run_pending", "appr_customer_lookup")
    first = client.post("/api/runs/run_pending/approvals/appr_customer_lookup/deny")
    assert first.status_code == 200

    second = client.post("/api/runs/run_pending/approvals/appr_customer_lookup/approve")

    assert second.status_code == 409


def test_approving_expired_pending_approval_records_timeout_without_tool_resume(client, app) -> None:
    _seed_pending_approval(
        app,
        "run_pending",
        "appr_customer_lookup",
        expires_at="2000-01-01T00:00:00Z",
    )

    resp = client.post("/api/runs/run_pending/approvals/appr_customer_lookup/approve")

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Approval expired: appr_customer_lookup"

    detail = client.get("/api/runs/run_pending").json()
    assert detail["approval_state"]["state"] == "timed_out"
    assert detail["approval_state"]["approval_id"] == "appr_customer_lookup"
    assert detail["pending_approvals"] == []

    trace = client.get("/api/runs/run_pending/trace").json()
    event_types = [event["event_type"] for event in trace["events"]]
    assert event_types.count("approval_timeout") == 1
    assert "approval_granted" not in event_types
    assert "tool_result" not in event_types


def test_global_approval_queue_lists_newest_pending_approvals_first(client, app) -> None:
    _seed_pending_approval(
        app,
        "run_older",
        "appr_older",
        created_at="2026-05-10T14:00:00Z",
        expires_at="2099-05-10T14:01:00Z",
    )
    _seed_pending_approval(
        app,
        "run_newer",
        "appr_newer",
        created_at="2026-05-10T15:00:00Z",
        expires_at="2099-05-10T15:01:00Z",
    )

    resp = client.get("/api/approvals")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["approval_id"] for item in body["data"]] == ["appr_newer", "appr_older"]
