from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from proof_agent.contracts.run_execution import (
    RoleActivation,
    RunClaim,
    RunExecutionSnapshot,
    RunQueueRecord,
    RunRequest,
    RunFailure,
    RunLifecycleState,
)
from proof_agent.contracts.artifacts import ArtifactManifest, ArtifactObjectVersion
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.conversation import ConversationTurn


class RunQueueOverloadedError(RuntimeError):
    """The durable queued capacity is full; admission did not mutate state."""

    def __init__(self, *, capacity: int, retry_after_seconds: int = 1) -> None:
        self.capacity = capacity
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Run queue capacity {capacity} is exhausted")


class RunIdempotencyConflictError(RuntimeError):
    """An operator reused an idempotency key for a different canonical request."""


class RunClaimRejectedError(RuntimeError):
    """The Executor no longer owns the active role or claimed Attempt."""


class RunConversationBusyError(RuntimeError):
    """A conversation already has one queued or active governed Run."""


RunExecutionSnapshotFactory = Callable[
    [RunRequest, str, int, datetime], RunExecutionSnapshot
]


class RunQueueRepository(Protocol):
    def admit(self, request: RunRequest) -> tuple[RunQueueRecord, bool]: ...

    def get(self, run_id: str) -> RunQueueRecord | None: ...

    def list(self, *, limit: int = 100) -> Sequence[RunQueueRecord]: ...

    def list_page(
        self,
        *,
        limit: int,
        offset: int,
        run_purpose: RunPurpose | None = None,
        search: str | None = None,
        states: Sequence[RunLifecycleState] = (),
        receipt_outcome: ReceiptOutcome | None = None,
    ) -> tuple[Sequence[RunQueueRecord], int]: ...

    def activate_role(
        self, *, slot: int, executor_id: str, now: datetime
    ) -> RoleActivation: ...

    def claim_next(
        self,
        *,
        slot: int,
        executor_id: str,
        activation_epoch: int,
        now: datetime,
        lease_seconds: int,
        deadline_seconds: int,
        snapshot_factory: RunExecutionSnapshotFactory,
    ) -> RunClaim | None: ...

    def heartbeat(
        self, claim: RunClaim, *, now: datetime, lease_seconds: int
    ) -> RunClaim: ...

    def mark_finalizing(self, claim: RunClaim, *, now: datetime) -> RunClaim: ...

    def request_cancel(
        self, *, run_id: str, operator_subject: str, now: datetime
    ) -> RunQueueRecord: ...

    def commit_terminal_failure(
        self,
        claim: RunClaim,
        *,
        target: RunLifecycleState,
        failure: RunFailure,
        now: datetime,
    ) -> RunQueueRecord: ...

    def commit_success(
        self,
        claim: RunClaim,
        *,
        manifest: ArtifactManifest,
        manifest_ref: ArtifactObjectVersion,
        now: datetime,
        receipt_outcome: ReceiptOutcome | None = None,
        conversation_turn: ConversationTurn | None = None,
        expected_conversation_turn_count: int | None = None,
    ) -> RunQueueRecord: ...

    def reap_expired_leases(self, *, now: datetime) -> int: ...


__all__ = [
    "RunClaimRejectedError",
    "RunConversationBusyError",
    "RunExecutionSnapshotFactory",
    "RunIdempotencyConflictError",
    "RunQueueOverloadedError",
    "RunQueueRepository",
]
