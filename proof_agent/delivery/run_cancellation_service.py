from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from proof_agent.contracts.ports.run_queue import RunQueueRepository
from proof_agent.contracts.run_execution import RunQueueRecord


class RunCancellationService:
    def __init__(
        self,
        repository: RunQueueRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def cancel(self, *, run_id: str, operator_subject: str) -> RunQueueRecord:
        return self._repository.request_cancel(
            run_id=run_id,
            operator_subject=operator_subject,
            now=self._clock(),
        )


__all__ = ["RunCancellationService"]
