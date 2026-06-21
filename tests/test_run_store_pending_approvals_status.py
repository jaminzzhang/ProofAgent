"""Tests for the pending approval queue's status (pending/expired) filter.

These pin the `list_pending_approvals(status=...)` contract: `total` and the
returned slice must reflect the scoped set so the dashboard pager stays
consistent. See CONTEXT.md "Approval Queue Status Vocabulary".
"""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from proof_agent.contracts.dashboard import RunIndex
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.storage.run_store import RunStore


def _write_run_meta(store: RunStore, run_id: str, question: str, created_at: str) -> None:
    store.write_run_meta(
        RunIndex(
            run_id=run_id,
            question=question,
            outcome=ReceiptOutcome.WAITING_FOR_APPROVAL,
            created_at=created_at,
            updated_at=created_at,
        )
    )


def _seed_pending_approval_run(
    store: RunStore,
    run_id: str,
    approval_id: str,
    expires_at: str,
    created_at: str = "2026-06-18T10:00:00Z",
    sequence: int = 10,
) -> None:
    """Write a run with a single unresolved pending approval at a given expiry."""
    run_dir = store.create_run_dir(run_id)
    (run_dir / "trace.jsonl").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "event_type": "pending_approval_created",
                "sequence": sequence,
                "timestamp": created_at,
                "payload": {
                    "approval_id": approval_id,
                    "tool_name": "customer_lookup",
                    "action_id": f"act_{approval_id}",
                    "expires_at": expires_at,
                    "created_at": created_at,
                    "parameters": {"customer_id": "CUST-001"},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")
    _write_run_meta(store, run_id, f"question {run_id}", created_at)


def _seed_resolved_approval_run(
    store: RunStore,
    run_id: str,
    approval_id: str,
    expires_at: str,
    created_at: str = "2026-06-18T09:00:00Z",
) -> None:
    """A run whose approval was granted — must NOT appear in the queue."""
    run_dir = store.create_run_dir(run_id)
    events = [
        {
            "run_id": run_id,
            "event_type": "pending_approval_created",
            "sequence": 1,
            "timestamp": created_at,
            "payload": {
                "approval_id": approval_id,
                "tool_name": "policy_lookup",
                "action_id": f"act_{approval_id}",
                "expires_at": expires_at,
                "created_at": created_at,
                "parameters": {},
            },
        },
        {
            "run_id": run_id,
            "event_type": "approval_granted",
            "sequence": 2,
            "timestamp": created_at,
            "payload": {"approval_id": approval_id, "tool_name": "policy_lookup"},
        },
    ]
    (run_dir / "trace.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )
    (run_dir / "governance_receipt.md").write_text("# Receipt", encoding="utf-8")
    _write_run_meta(store, run_id, f"question {run_id}", created_at)


def _timestamp(delta: timedelta) -> str:
    """Return a stable UTC timestamp relative to the test's actual run time."""
    return (datetime.now(UTC) + delta).isoformat().replace("+00:00", "Z")


def _future_expiry(days: int = 1) -> str:
    return _timestamp(timedelta(days=days))


def _past_expiry(days: int = 1) -> str:
    return _timestamp(-timedelta(days=days))


def test_status_all_returns_pending_and_expired_but_not_resolved(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    _seed_pending_approval_run(store, "run_pending", "appr_future", _future_expiry())
    _seed_pending_approval_run(store, "run_expired", "appr_past", _past_expiry())
    _seed_resolved_approval_run(store, "run_resolved", "appr_granted", _future_expiry())

    items, total = store.list_pending_approvals(status="all")
    assert total == 2
    ids = {item["run_id"] for item in items}
    assert ids == {"run_pending", "run_expired"}


def test_status_pending_excludes_expired(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    _seed_pending_approval_run(store, "run_pending", "appr_future", _future_expiry())
    _seed_pending_approval_run(store, "run_expired", "appr_past", _past_expiry())

    items, total = store.list_pending_approvals(status="pending")
    assert total == 1
    assert items[0]["run_id"] == "run_pending"
    assert items[0]["expired"] is False


def test_status_expired_excludes_pending(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    _seed_pending_approval_run(store, "run_pending", "appr_future", _future_expiry())
    _seed_pending_approval_run(store, "run_expired", "appr_past", _past_expiry())

    items, total = store.list_pending_approvals(status="expired")
    assert total == 1
    assert items[0]["run_id"] == "run_expired"
    assert items[0]["expired"] is True


def test_status_default_matches_all(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    _seed_pending_approval_run(store, "run_pending", "appr_future", _future_expiry())
    _seed_pending_approval_run(store, "run_expired", "appr_past", _past_expiry())

    items_default, total_default = store.list_pending_approvals()
    items_all, total_all = store.list_pending_approvals(status="all")
    assert total_default == total_all == 2
    assert {i["run_id"] for i in items_default} == {i["run_id"] for i in items_all}


def test_status_filter_respects_limit_and_offset(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    _seed_pending_approval_run(store, "run_a", "appr_a", _future_expiry(days=1), sequence=1)
    _seed_pending_approval_run(store, "run_b", "appr_b", _future_expiry(days=2), sequence=2)

    items, total = store.list_pending_approvals(status="pending", limit=1, offset=0)
    assert total == 2
    assert len(items) == 1

    items_page2, _ = store.list_pending_approvals(status="pending", limit=1, offset=1)
    assert len(items_page2) == 1
    assert items_page2[0]["run_id"] != items[0]["run_id"]
