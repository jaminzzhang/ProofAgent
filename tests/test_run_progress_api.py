from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from proof_agent.contracts.run_execution import (
    RunLifecycleState,
    RunQueueRecord,
    RunRequest,
)
from proof_agent.delivery.run_progress_service import RunProgressService


NOW = datetime(2026, 7, 15, tzinfo=UTC)
RUN_ID = "019ba001-1111-7000-8000-000000000010"


def _record(
    state: RunLifecycleState,
    version: int,
    *,
    completed: bool = False,
) -> RunQueueRecord:
    request = RunRequest(
        run_id=RUN_ID,
        operator_subject="operator-1",
        idempotency_key="submit-1",
        agent_id="agent_management_insurance_specialist",
        agent_version_id="019ba001-1111-7000-8000-000000000001",
        question="secret question must never enter SSE",
        permission_mapping_version_id="019ba001-1111-7000-8000-000000000099",
        permission_epoch=7,
        submitted_at=NOW,
    )
    return RunQueueRecord(
        request=request,
        request_sha256=request.canonical_sha256(),
        state=state,
        state_version=version,
        enqueued_at=NOW,
        started_at=(None if state is RunLifecycleState.QUEUED else NOW),
        completed_at=(NOW + timedelta(seconds=1) if completed else None),
        updated_at=NOW + timedelta(seconds=version),
    )


class Repository:
    def __init__(self, records: list[RunQueueRecord]) -> None:
        self.records = records
        self.calls = 0

    def get(self, run_id: str):
        assert run_id == RUN_ID
        index = min(self.calls, len(self.records) - 1)
        self.calls += 1
        return self.records[index]


def test_sse_immediately_snapshots_then_emits_coarse_terminal_and_closes() -> None:
    repository = Repository(
        [
            _record(RunLifecycleState.QUEUED, 1),
            _record(RunLifecycleState.CANCELLED, 2, completed=True),
        ]
    )
    service = RunProgressService(
        repository,  # type: ignore[arg-type]
        poll_interval_seconds=0.05,
        heartbeat_seconds=1,
        clock=lambda: NOW,
    )

    async def collect() -> list[str]:
        return [
            event
            async for event in service.stream(
                run_id=RUN_ID,
                disconnected=lambda: _false(),
            )
        ]

    events = asyncio.run(collect())

    assert "event: state_snapshot" in events[0]
    assert '"state":"queued"' in events[0]
    assert "event: state_change" in events[1]
    assert '"state":"cancelled"' in events[1]
    assert "secret question" not in "".join(events)


def test_reconnect_to_terminal_run_emits_one_current_snapshot() -> None:
    service = RunProgressService(
        Repository([_record(RunLifecycleState.CANCELLED, 2, completed=True)]),  # type: ignore[arg-type]
        poll_interval_seconds=0.05,
        heartbeat_seconds=1,
        clock=lambda: NOW,
    )

    async def collect() -> list[str]:
        return [
            event
            async for event in service.stream(
                run_id=RUN_ID,
                disconnected=lambda: _false(),
            )
        ]

    events = asyncio.run(collect())
    assert len(events) == 1
    assert "state_snapshot" in events[0]
    assert '"state":"cancelled"' in events[0]


async def _false() -> bool:
    return False
