from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from time import sleep
from typing import Never

from proof_agent.contracts.run_execution import (
    RoleActivation,
    RoleActivationState,
    RunAttempt,
    RunClaim,
    RunExecutionSnapshot,
    RunLifecycleState,
    RunQueueRecord,
    RunRequest,
)
from proof_agent.delivery.run_executor import RunExecutor


NOW = datetime(2026, 7, 25, 10, tzinfo=UTC)
DIGEST = "a" * 64
RUN_ID = "019ba001-1111-7000-8000-000000000010"
ATTEMPT_ID = "019ba001-1111-7000-8000-000000000011"
VERSION_ID = "019ba001-1111-7000-8000-000000000012"


def _claim() -> RunClaim:
    request = RunRequest(
        run_id=RUN_ID,
        operator_subject="operator-1",
        idempotency_key="submit-1",
        agent_id="agent_management_insurance_specialist",
        agent_version_id=VERSION_ID,
        question="question",
        permission_mapping_version_id=VERSION_ID,
        permission_epoch=1,
        submitted_at=NOW,
    )
    snapshot = RunExecutionSnapshot(
        run_id=RUN_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        release_id="release-1",
        image_digest=DIGEST,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        agent_configuration_sha256=DIGEST,
        knowledge_configuration_sha256=DIGEST,
        model_configuration_sha256=DIGEST,
        egress_policy_version_id=VERSION_ID,
        egress_policy_sha256=DIGEST,
        permission_mapping_version_id=VERSION_ID,
        permission_mapping_sha256=DIGEST,
        permission_epoch=1,
        institution_authorization_sha256=request.institution_authorization_sha256,
        tool_configuration_sha256=DIGEST,
        frozen_at=NOW,
    )
    attempt = RunAttempt(
        attempt_id=ATTEMPT_ID,
        run_id=RUN_ID,
        attempt_number=1,
        state=RunLifecycleState.RUNNING,
        state_version=1,
        claim_token="claim_" + "x" * 32,
        fencing_epoch=1,
        activation_epoch=1,
        executor_id="executor-green",
        heartbeat_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=15),
        deadline_at=NOW + timedelta(seconds=120),
        snapshot=snapshot,
        snapshot_sha256=snapshot.canonical_sha256(),
        created_at=NOW,
        updated_at=NOW,
    )
    return RunClaim(run_request=request, attempt=attempt)


class AdvancingClock:
    def __init__(self) -> None:
        self._value = NOW
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            self._value += timedelta(milliseconds=100)
            return self._value


class DrainRepository:
    def __init__(self, claim: RunClaim) -> None:
        self.claim = claim
        self.record = RunQueueRecord(
            request=claim.run_request,
            request_sha256=claim.run_request.canonical_sha256(),
            state=RunLifecycleState.RUNNING,
            state_version=2,
            enqueued_at=claim.run_request.submitted_at,
            started_at=NOW,
            updated_at=NOW,
        )
        self.claim_calls = 0
        self.heartbeat_seen = Event()
        self.failure_committed = Event()

    def activate_role(self, **_kwargs: object) -> RoleActivation:
        return RoleActivation(
            slot=2,
            state=RoleActivationState.ACTIVE,
            activation_epoch=1,
            executor_id="executor-green",
            updated_at=NOW,
        )

    def claim_next(self, **_kwargs: object) -> RunClaim | None:
        self.claim_calls += 1
        return self.claim if self.claim_calls == 1 else None

    def heartbeat(self, claim: RunClaim, **_kwargs: object) -> RunClaim:
        self.heartbeat_seen.set()
        return claim

    def reap_expired_leases(self, **_kwargs: object) -> int:
        return 0

    def commit_terminal_failure(
        self, *_args: object, **_kwargs: object
    ) -> None:
        self.failure_committed.set()

    def get(self, _run_id: str) -> RunQueueRecord:
        return self.record


def test_stop_drains_inflight_attempt_with_heartbeats_and_no_new_claim() -> None:
    repository = DrainRepository(_claim())
    work_started = Event()
    release_work = Event()

    def handler(_claim: RunClaim, _check: Callable[[], None]) -> Never:
        work_started.set()
        assert release_work.wait(timeout=2)
        raise RuntimeError("finish through terminal failure path")

    executor = RunExecutor(
        repository=repository,  # type: ignore[arg-type]
        snapshot_factory=lambda *_args: (_ for _ in ()).throw(AssertionError()),
        handler=handler,  # type: ignore[arg-type]
        artifact_finalizer=object(),  # type: ignore[arg-type]
        executor_id="executor-green",
        slot=2,
        concurrency=1,
        poll_interval_seconds=0.05,
        heartbeat_interval_seconds=1,
        lease_seconds=15,
        deadline_seconds=120,
        clock=AdvancingClock(),
        sleeper=lambda _seconds: sleep(0.001),
    )
    failures: list[BaseException] = []

    def run() -> None:
        try:
            executor.run_until_idle()
        except BaseException as exc:
            failures.append(exc)

    thread = Thread(target=run)
    thread.start()
    assert work_started.wait(timeout=1), (
        failures,
        repository.claim_calls,
        thread.is_alive(),
        repository.failure_committed.is_set(),
    )

    executor.stop()
    assert repository.heartbeat_seen.wait(timeout=1)
    release_work.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert failures == []
    assert repository.failure_committed.is_set()
    assert repository.claim_calls == 1
