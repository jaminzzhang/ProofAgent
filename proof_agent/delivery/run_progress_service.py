from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
import asyncio
from datetime import UTC, datetime
import json
from typing import Literal

from proof_agent.contracts.ports.run_queue import RunQueueRepository
from proof_agent.contracts.run_execution import RunProgress, RunQueueRecord


DisconnectCheck = Callable[[], Awaitable[bool]]


class RunProgressService:
    """Reconnectable coarse progress: PostgreSQL state is the replay authority."""

    def __init__(
        self,
        repository: RunQueueRepository,
        *,
        poll_interval_seconds: float = 0.5,
        heartbeat_seconds: float = 15.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0.05 <= poll_interval_seconds <= 5:
            raise ValueError("Run progress poll interval is outside the safe envelope")
        if heartbeat_seconds < poll_interval_seconds:
            raise ValueError("Run progress heartbeat cannot be faster than polling")
        self._repository = repository
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def stream(
        self,
        *,
        run_id: str,
        disconnected: DisconnectCheck,
    ) -> AsyncIterator[str]:
        current = await asyncio.to_thread(self._repository.get, run_id)
        if current is None:
            raise LookupError(run_id)
        yield _event(current, event_kind="state_snapshot", occurred_at=self._clock())
        if current.state.is_terminal:
            return
        last_version = current.state_version
        heartbeat_elapsed = 0.0
        while True:
            await asyncio.sleep(self._poll_interval_seconds)
            if await disconnected():
                return
            heartbeat_elapsed += self._poll_interval_seconds
            latest = await asyncio.to_thread(self._repository.get, run_id)
            if latest is None:
                return
            if latest.state_version != last_version:
                yield _event(latest, event_kind="state_change", occurred_at=self._clock())
                last_version = latest.state_version
                heartbeat_elapsed = 0.0
            elif heartbeat_elapsed >= self._heartbeat_seconds:
                yield ": heartbeat\n\n"
                heartbeat_elapsed = 0.0
            if latest.state.is_terminal:
                return


def _event(
    record: RunQueueRecord,
    *,
    event_kind: Literal["state_snapshot", "state_change", "detail"],
    occurred_at: datetime,
) -> str:
    progress = RunProgress(
        run_id=record.request.run_id,
        state=record.state,
        state_version=record.state_version,
        event_kind=event_kind,
        safe_detail_code=(None if record.failure is None else record.failure.code.value),
        occurred_at=occurred_at,
    )
    data = json.dumps(
        progress.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"id: {progress.state_version}\n"
        f"event: {progress.event_kind}\n"
        f"data: {data}\n\n"
    )


__all__ = ["RunProgressService"]
