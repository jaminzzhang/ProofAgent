from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event
import time
from typing import Protocol
from uuid import uuid4

from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactOwner
from proof_agent.contracts.conversation import ConversationTurn
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.ports.run_queue import (
    RunClaimRejectedError,
    RunExecutionSnapshotFactory,
    RunQueueRepository,
)
from proof_agent.contracts.run_execution import (
    RoleActivation,
    RunClaim,
    RunFailure,
    RunFailureCode,
    RunLifecycleState,
)


class RunExecutionCancelled(RuntimeError):
    pass


class RunExecutionTimedOut(RuntimeError):
    pass


CancellationCheck = Callable[[], None]


@dataclass(frozen=True)
class RunWorkResult:
    members: tuple[ArtifactMemberPayload, ...]
    receipt_outcome: ReceiptOutcome | None = None
    conversation_turn: ConversationTurn | None = None
    expected_conversation_turn_count: int | None = None


class RunWorkHandler(Protocol):
    def __call__(
        self,
        claim: RunClaim,
        cancellation_check: CancellationCheck,
    ) -> RunWorkResult | tuple[ArtifactMemberPayload, ...]: ...


class RunExecutor:
    """Same-image bounded supervisor for claimed governed Run Attempts."""

    def __init__(
        self,
        *,
        repository: RunQueueRepository,
        snapshot_factory: RunExecutionSnapshotFactory,
        handler: RunWorkHandler,
        artifact_finalizer: ArtifactBundleFinalizer,
        executor_id: str,
        slot: int = 1,
        concurrency: int = 5,
        poll_interval_seconds: float = 0.2,
        heartbeat_interval_seconds: int = 5,
        lease_seconds: int = 15,
        deadline_seconds: int = 120,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] | None = None,
        manifest_id_factory: Callable[[], str] | None = None,
        claim_guard: Callable[[], bool] | None = None,
    ) -> None:
        if not 1 <= concurrency <= 5:
            raise ValueError("Run Executor concurrency must be between one and five")
        if not 0.05 <= poll_interval_seconds <= 5:
            raise ValueError("Run Executor poll interval is outside the safe envelope")
        if not 1 <= heartbeat_interval_seconds < lease_seconds:
            raise ValueError("Run Executor heartbeat must be shorter than its lease")
        if not lease_seconds < deadline_seconds <= 120:
            raise ValueError("Run Executor deadline must be at most 120 seconds")
        self._repository = repository
        self._snapshot_factory = snapshot_factory
        self._handler = handler
        self._artifact_finalizer = artifact_finalizer
        self._executor_id = executor_id
        self._slot = slot
        self._concurrency = concurrency
        self._poll_interval_seconds = poll_interval_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._lease_seconds = lease_seconds
        self._deadline_seconds = deadline_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper or time.sleep
        self._manifest_id_factory = manifest_id_factory or (lambda: str(uuid4()))
        self._claim_guard = claim_guard or (lambda: True)
        self._activation: RoleActivation | None = None
        self._stop = Event()

    def activate(self) -> RoleActivation:
        activation = self._repository.activate_role(
            slot=self._slot,
            executor_id=self._executor_id,
            now=self._now(),
        )
        self._activation = activation
        return activation

    def stop(self) -> None:
        self._stop.set()

    def run_until_idle(self, *, idle_polls: int = 2) -> int:
        """Process available work and return only after bounded idle confirmation."""

        if idle_polls < 1:
            raise ValueError("Run Executor idle polls must be positive")
        activation = self._activation or self.activate()
        completed = 0
        empty_polls = 0
        active: dict[Future[None], tuple[RunClaim, datetime]] = {}
        with ThreadPoolExecutor(
            max_workers=self._concurrency,
            thread_name_prefix="proofagent-run",
        ) as pool:
            while active or not self._stop.is_set():
                now = self._now()
                self._repository.reap_expired_leases(now=now)
                for future, (running_claim, last_heartbeat) in tuple(active.items()):
                    if future.done():
                        future.result()
                        del active[future]
                        completed += 1
                        continue
                    if (now - last_heartbeat).total_seconds() < self._heartbeat_interval_seconds:
                        continue
                    try:
                        renewed = self._repository.heartbeat(
                            running_claim,
                            now=now,
                            lease_seconds=self._lease_seconds,
                        )
                    except RunClaimRejectedError:
                        continue
                    active[future] = (renewed, now)

                claimed_any = False
                while (
                    not self._stop.is_set()
                    and len(active) < self._concurrency
                    and self._claim_guard()
                ):
                    claim = self._repository.claim_next(
                        slot=self._slot,
                        executor_id=self._executor_id,
                        activation_epoch=activation.activation_epoch,
                        now=self._now(),
                        lease_seconds=self._lease_seconds,
                        deadline_seconds=self._deadline_seconds,
                        snapshot_factory=self._snapshot_factory,
                    )
                    if claim is None:
                        break
                    claimed_any = True
                    future = pool.submit(self._execute_claim, claim)
                    active[future] = (claim, self._now())
                if self._stop.is_set() and not active:
                    break
                if active or claimed_any:
                    empty_polls = 0
                else:
                    empty_polls += 1
                    if empty_polls >= idle_polls:
                        break
                self._sleeper(self._poll_interval_seconds)
        return completed

    def serve(self) -> None:
        """Poll until stopped; intended for the dedicated Run Executor process role."""

        while not self._stop.is_set():
            self.run_until_idle(idle_polls=1)
            if not self._stop.is_set():
                self._sleeper(self._poll_interval_seconds)

    def _execute_claim(self, claim: RunClaim) -> None:
        finalizing = False

        def cancellation_check() -> None:
            self._check_cancellation_or_deadline(claim)

        try:
            cancellation_check()
            handled = self._handler(claim, cancellation_check)
            if isinstance(handled, RunWorkResult):
                members = handled.members
                receipt_outcome = handled.receipt_outcome
                conversation_turn = handled.conversation_turn
                expected_conversation_turn_count = (
                    handled.expected_conversation_turn_count
                )
            else:
                members = handled
                receipt_outcome = None
                conversation_turn = None
                expected_conversation_turn_count = None
            cancellation_check()
            finalized_claim = self._repository.mark_finalizing(claim, now=self._now())
            finalizing = True
            prepared = self._artifact_finalizer.prepare(
                owner=ArtifactOwner(
                    owner_type="run_attempt",
                    owner_id=claim.attempt.attempt_id,
                ),
                manifest_id=self._manifest_id_factory(),
                members=members,
                cancellation_check=cancellation_check,
            )
            cancellation_check()
            self._repository.commit_success(
                finalized_claim,
                manifest=prepared.manifest,
                manifest_ref=prepared.manifest_ref,
                now=self._now(),
                receipt_outcome=receipt_outcome,
                conversation_turn=conversation_turn,
                expected_conversation_turn_count=expected_conversation_turn_count,
            )
        except RunExecutionCancelled:
            self._terminal_best_effort(
                claim,
                target=RunLifecycleState.CANCELLED,
                code=RunFailureCode.CANCELLED,
            )
        except RunExecutionTimedOut:
            self._terminal_best_effort(
                claim,
                target=RunLifecycleState.TIMED_OUT,
                code=RunFailureCode.DEADLINE_EXCEEDED,
            )
        except RunClaimRejectedError:
            current = self._repository.get(claim.run_request.run_id)
            if current is not None and current.state is RunLifecycleState.CANCEL_REQUESTED:
                self._terminal_best_effort(
                    claim,
                    target=RunLifecycleState.CANCELLED,
                    code=RunFailureCode.CANCELLED,
                )
        except Exception:
            self._terminal_best_effort(
                claim,
                target=RunLifecycleState.FAILED,
                code=(
                    RunFailureCode.FINALIZATION_FAILED
                    if finalizing
                    else RunFailureCode.EXECUTION_FAILED
                ),
            )

    def _check_cancellation_or_deadline(self, claim: RunClaim) -> None:
        now = self._now()
        if now >= claim.attempt.deadline_at:
            raise RunExecutionTimedOut("Run Attempt deadline exceeded")
        current = self._repository.get(claim.run_request.run_id)
        if current is None:
            raise RunClaimRejectedError("Run disappeared during execution")
        if current.state in {
            RunLifecycleState.CANCEL_REQUESTED,
            RunLifecycleState.CANCELLED,
        }:
            raise RunExecutionCancelled("Run cancellation requested")
        if current.state.is_terminal:
            raise RunClaimRejectedError("Run is already terminal")

    def _terminal_best_effort(
        self,
        claim: RunClaim,
        *,
        target: RunLifecycleState,
        code: RunFailureCode,
    ) -> None:
        try:
            self._repository.commit_terminal_failure(
                claim,
                target=target,
                failure=RunFailure(code=code),
                now=self._now(),
            )
        except (RunClaimRejectedError, ValueError):
            return

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise ValueError("Run Executor clock must be timezone-aware")
        return value


__all__ = [
    "CancellationCheck",
    "RunExecutionCancelled",
    "RunExecutionTimedOut",
    "RunExecutor",
    "RunWorkHandler",
    "RunWorkResult",
]
