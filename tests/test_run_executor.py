from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from sqlalchemy import Engine

from postgres_fixtures import TEST_AGENT_ID, TEST_AGENT_VERSION_ID, seed_agent_version
from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
    PostgresRunQueueRepository,
)
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactKind
from proof_agent.contracts.run_execution import (
    RunExecutionSnapshot,
    RunLifecycleState,
    RunRequest,
)
from proof_agent.delivery.run_executor import RunExecutor


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

NOW = datetime(2026, 7, 15, tzinfo=UTC)
DIGEST = "a" * 64
AUTHORITY_VERSION = "019ba001-1111-7000-8000-000000000099"


def _request(index: int) -> RunRequest:
    return RunRequest(
        run_id=f"019ba001-1111-7000-8000-{index:012d}",
        operator_subject=f"operator-{index}",
        idempotency_key=f"submit-{index}",
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        question=f"question {index}",
        permission_mapping_version_id=AUTHORITY_VERSION,
        permission_epoch=7,
        submitted_at=NOW + timedelta(milliseconds=index),
    )


def _snapshot(request, attempt_id, attempt_number, frozen_at):
    return RunExecutionSnapshot(
        run_id=request.run_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        release_id="proofagent-2026.07.15",
        image_digest=DIGEST,
        agent_id=request.agent_id,
        agent_version_id=request.agent_version_id,
        agent_configuration_sha256=DIGEST,
        knowledge_configuration_sha256=DIGEST,
        model_configuration_sha256=DIGEST,
        egress_policy_version_id=AUTHORITY_VERSION,
        egress_policy_sha256=DIGEST,
        permission_mapping_version_id=request.permission_mapping_version_id,
        permission_mapping_sha256=DIGEST,
        permission_epoch=request.permission_epoch,
        institution_authorization_sha256=request.institution_authorization_sha256,
        tool_configuration_sha256=DIGEST,
        secret_handle_ids=(),
        frozen_at=frozen_at,
    )


def _finalizer(engine: Engine, root: Path) -> ArtifactBundleFinalizer:
    return ArtifactBundleFinalizer(
        store=FilesystemArtifactStore(root, clock=lambda: NOW + timedelta(seconds=3)),
        repository=PostgresArtifactReferenceRepository(engine),
        clock=lambda: NOW + timedelta(seconds=3),
    )


def _member(index: str) -> tuple[ArtifactMemberPayload, ...]:
    return (
        ArtifactMemberPayload(
            member_id="trace",
            kind=ArtifactKind.RUN_TRACE,
            content_type="application/json",
            content=f'{{"run":"{index}"}}'.encode(),
        ),
    )


def test_executor_processes_governed_result_to_atomic_visible_success(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    repository = PostgresRunQueueRepository(postgres_engine)
    for index in range(1, 4):
        repository.admit(_request(index))
    executor = RunExecutor(
        repository=repository,
        snapshot_factory=_snapshot,
        handler=lambda claim, check: (check(), _member(claim.attempt.attempt_id))[1],
        artifact_finalizer=_finalizer(postgres_engine, tmp_path),
        executor_id="executor-green",
        concurrency=3,
        poll_interval_seconds=0.05,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    assert executor.run_until_idle() == 3
    for index in range(1, 4):
        record = repository.get(_request(index).run_id)
        assert record is not None
        assert record.state is RunLifecycleState.SUCCEEDED
        assert record.result.result_available is True


def test_executor_never_starts_sixth_attempt_before_a_slot_is_released(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    repository = PostgresRunQueueRepository(postgres_engine)
    for index in range(1, 7):
        repository.admit(_request(index))
    release = Event()
    five_started = Event()
    lock = Lock()
    active = 0
    maximum = 0

    def handler(claim, check):
        nonlocal active, maximum
        check()
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 5:
                five_started.set()
        assert release.wait(timeout=5)
        with lock:
            active -= 1
        return _member(claim.attempt.attempt_id)

    executor = RunExecutor(
        repository=repository,
        snapshot_factory=_snapshot,
        handler=handler,
        artifact_finalizer=_finalizer(postgres_engine, tmp_path),
        executor_id="executor-green",
        concurrency=5,
        poll_interval_seconds=0.05,
    )
    thread = Thread(target=executor.run_until_idle)
    thread.start()
    assert five_started.wait(timeout=5)

    queued = [
        record
        for index in range(1, 7)
        if (record := repository.get(_request(index).run_id)) is not None
        and record.state is RunLifecycleState.QUEUED
    ]
    assert len(queued) == 1
    assert maximum == 5
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert all(
        repository.get(_request(index).run_id).state is RunLifecycleState.SUCCEEDED  # type: ignore[union-attr]
        for index in range(1, 7)
    )


def test_executor_sanitizes_handler_failure_to_stable_terminal_code(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    repository = PostgresRunQueueRepository(postgres_engine)
    request = _request(1)
    repository.admit(request)

    def fail(_claim, _check):
        raise RuntimeError("provider secret and body must not escape")

    executor = RunExecutor(
        repository=repository,
        snapshot_factory=_snapshot,
        handler=fail,
        artifact_finalizer=_finalizer(postgres_engine, tmp_path),
        executor_id="executor-green",
        concurrency=1,
        poll_interval_seconds=0.05,
    )
    assert executor.run_until_idle() == 1

    record = repository.get(request.run_id)
    assert record is not None
    assert record.state is RunLifecycleState.FAILED
    assert record.failure is not None
    assert record.failure.code.value == "PA_EXECUTION_FAILED"
    assert record.failure.safe_detail is None
