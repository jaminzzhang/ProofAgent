from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select

from postgres_fixtures import TEST_AGENT_ID, TEST_AGENT_VERSION_ID, seed_agent_version
from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
    PostgresRunQueueRepository,
)
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.artifacts.filesystem import FilesystemArtifactStore
from proof_agent.control.artifacts.finalization import (
    ArtifactBundleFinalizer,
    ArtifactMemberPayload,
)
from proof_agent.contracts.artifacts import ArtifactKind, ArtifactOwner
from proof_agent.contracts.conversation import ContextAdmission, ConversationRecord, ConversationTurn
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import run_attempts, runs
from proof_agent.contracts.ports.run_queue import (
    RunClaimRejectedError,
    RunConversationBusyError,
    RunIdempotencyConflictError,
    RunQueueOverloadedError,
)
from proof_agent.contracts.run_execution import RunExecutionSnapshot, RunRequest
from proof_agent.contracts.run_execution import (
    RunFailure,
    RunFailureCode,
    RunLifecycleState,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

NOW = datetime(2026, 7, 15, tzinfo=UTC)
DIGEST = "a" * 64
PERMISSION_VERSION = "019ba001-1111-7000-8000-000000000099"


def _request(index: int, *, operator: str = "operator-1", key: str | None = None) -> RunRequest:
    return RunRequest(
        run_id=f"019ba001-1111-7000-8000-{index:012d}",
        operator_subject=operator,
        idempotency_key=key or f"submit-{index}",
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        question=f"question {index}",
        permission_mapping_version_id=PERMISSION_VERSION,
        permission_epoch=7,
        submitted_at=NOW + timedelta(milliseconds=index),
    )


def _snapshot(
    request: RunRequest,
    attempt_id: str,
    attempt_number: int,
    frozen_at: datetime,
) -> RunExecutionSnapshot:
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
        egress_policy_version_id=PERMISSION_VERSION,
        egress_policy_sha256=DIGEST,
        permission_mapping_version_id=request.permission_mapping_version_id,
        permission_mapping_sha256=DIGEST,
        permission_epoch=request.permission_epoch,
        institution_authorization_sha256=request.institution_authorization_sha256,
        tool_configuration_sha256=DIGEST,
        secret_handle_ids=("model/primary",),
        frozen_at=frozen_at,
    )


def _repository(engine: Engine) -> PostgresRunQueueRepository:
    return PostgresRunQueueRepository(engine)


def test_admission_is_idempotent_and_conflicting_repeat_does_not_mutate(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    request = _request(100)

    first, created = repository.admit(request)
    repeated, repeated_created = repository.admit(
        request.model_copy(
            update={
                "run_id": "019ba001-1111-7000-8000-000000000101",
                "submitted_at": request.submitted_at + timedelta(seconds=1),
            }
        )
    )

    assert created is True
    assert repeated_created is False
    assert repeated == first
    with pytest.raises(RunIdempotencyConflictError):
        repository.admit(request.model_copy(update={"question": "different"}))
    with postgres_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(runs)).scalar_one() == 1


def test_admission_enforces_exactly_fifty_queued_rows_atomically(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    for index in range(1, 51):
        repository.admit(_request(index))

    with pytest.raises(RunQueueOverloadedError) as caught:
        repository.admit(_request(51))

    assert caught.value.capacity == 50
    with postgres_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(runs)).scalar_one() == 50


def test_claim_requires_current_active_role_and_higher_epoch_fences_old_owner(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    repository.admit(_request(1))
    first = repository.activate_role(slot=1, executor_id="executor-blue", now=NOW)
    second = repository.activate_role(
        slot=2,
        executor_id="executor-green",
        now=NOW + timedelta(seconds=1),
    )

    assert second.activation_epoch > first.activation_epoch
    with pytest.raises(RunClaimRejectedError):
        repository.claim_next(
            slot=1,
            executor_id="executor-blue",
            activation_epoch=first.activation_epoch,
            now=NOW + timedelta(seconds=2),
            lease_seconds=15,
            deadline_seconds=120,
            snapshot_factory=_snapshot,
        )
    claim = repository.claim_next(
        slot=2,
        executor_id="executor-green",
        activation_epoch=second.activation_epoch,
        now=NOW + timedelta(seconds=2),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    assert claim.run_request.run_id == _request(1).run_id


def test_concurrent_claims_never_exceed_five_or_double_claim(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    for index in range(1, 11):
        repository.admit(_request(index, operator=f"operator-{index}"))
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)

    def claim_one(index: int):
        return _repository(postgres_engine).claim_next(
            slot=1,
            executor_id="executor",
            activation_epoch=activation.activation_epoch,
            now=NOW + timedelta(seconds=index),
            lease_seconds=15,
            deadline_seconds=120,
            snapshot_factory=_snapshot,
        )

    with ThreadPoolExecutor(max_workers=10) as pool:
        claims = list(pool.map(claim_one, range(1, 11)))

    claimed = [claim for claim in claims if claim is not None]
    assert len(claimed) == 5
    assert len({claim.run_request.run_id for claim in claimed}) == 5
    with postgres_engine.connect() as connection:
        assert connection.execute(select(func.count()).select_from(run_attempts)).scalar_one() == 5
        assert (
            connection.execute(
                select(func.count()).select_from(runs).where(runs.c.state == "queued")
            ).scalar_one()
            == 5
        )


def test_claim_fairness_rotates_operators_before_second_request(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    repository.admit(_request(1, operator="operator-a"))
    repository.admit(_request(2, operator="operator-a"))
    repository.admit(_request(3, operator="operator-b"))
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)

    first = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    second = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=2),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )

    assert first is not None and first.run_request.operator_subject == "operator-a"
    assert second is not None and second.run_request.operator_subject == "operator-b"


def test_heartbeat_renews_only_the_live_claim_and_activation_epoch(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    repository.admit(_request(1))
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None

    renewed = repository.heartbeat(
        claim,
        now=NOW + timedelta(seconds=5),
        lease_seconds=15,
    )
    assert renewed.attempt.lease_expires_at == NOW + timedelta(seconds=20)
    repository.activate_role(
        slot=2,
        executor_id="replacement",
        now=NOW + timedelta(seconds=6),
    )
    with pytest.raises(RunClaimRejectedError):
        repository.heartbeat(
            renewed,
            now=NOW + timedelta(seconds=7),
            lease_seconds=15,
        )


def test_queued_and_running_cancellation_are_atomic_and_idempotent(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    queued_request = _request(1)
    repository.admit(queued_request)

    cancelled = repository.request_cancel(
        run_id=queued_request.run_id,
        operator_subject=queued_request.operator_subject,
        now=NOW + timedelta(seconds=1),
    )
    repeated = repository.request_cancel(
        run_id=queued_request.run_id,
        operator_subject=queued_request.operator_subject,
        now=NOW + timedelta(seconds=2),
    )
    assert cancelled.state is RunLifecycleState.CANCELLED
    assert repeated == cancelled
    assert repository.claim_next is not None

    running_request = _request(2)
    repository.admit(running_request)
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    cancel_requested = repository.request_cancel(
        run_id=running_request.run_id,
        operator_subject=running_request.operator_subject,
        now=NOW + timedelta(seconds=2),
    )
    assert cancel_requested.state is RunLifecycleState.CANCEL_REQUESTED
    terminal = repository.commit_terminal_failure(
        claim,
        target=RunLifecycleState.CANCELLED,
        failure=RunFailure(code=RunFailureCode.CANCELLED),
        now=NOW + timedelta(seconds=3),
    )
    assert terminal.state is RunLifecycleState.CANCELLED
    assert terminal.result.result_available is False


def test_expired_lease_fails_without_replay_and_frees_exactly_one_slot(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    for index in range(1, 7):
        repository.admit(_request(index, operator=f"operator-{index}"))
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claims = [
        repository.claim_next(
            slot=1,
            executor_id="executor",
            activation_epoch=activation.activation_epoch,
            now=NOW + timedelta(milliseconds=index),
            lease_seconds=15,
            deadline_seconds=120,
            snapshot_factory=_snapshot,
        )
        for index in range(1, 6)
    ]
    assert all(claim is not None for claim in claims)
    assert (
        repository.claim_next(
            slot=1,
            executor_id="executor",
            activation_epoch=activation.activation_epoch,
            now=NOW + timedelta(seconds=2),
            lease_seconds=15,
            deadline_seconds=120,
            snapshot_factory=_snapshot,
        )
        is None
    )

    assert repository.reap_expired_leases(now=NOW + timedelta(seconds=16)) == 5
    replacement = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=17),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert replacement is not None
    with pytest.raises(RunClaimRejectedError):
        repository.commit_terminal_failure(
            claims[0],  # type: ignore[arg-type]
            target=RunLifecycleState.FAILED,
            failure=RunFailure(code=RunFailureCode.EXECUTION_FAILED),
            now=NOW + timedelta(seconds=18),
        )


def test_cancel_wins_against_finalization_and_blocks_stale_success_path(
    postgres_engine: Engine,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    request = _request(1)
    repository.admit(request)
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    finalizing = repository.mark_finalizing(claim, now=NOW + timedelta(seconds=2))
    cancellation = repository.request_cancel(
        run_id=request.run_id,
        operator_subject=request.operator_subject,
        now=NOW + timedelta(seconds=3),
    )

    assert cancellation.state is RunLifecycleState.CANCEL_REQUESTED
    with pytest.raises(ValueError, match="transition is not allowed"):
        repository.mark_finalizing(finalizing, now=NOW + timedelta(seconds=4))


def test_success_visibility_and_terminal_state_commit_in_one_postgres_transaction(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    request = _request(1)
    repository.admit(request)
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    finalizing = repository.mark_finalizing(claim, now=NOW + timedelta(seconds=2))
    artifact_repository = PostgresArtifactReferenceRepository(postgres_engine)
    finalizer = ArtifactBundleFinalizer(
        store=FilesystemArtifactStore(tmp_path, clock=lambda: NOW + timedelta(seconds=3)),
        repository=artifact_repository,
        clock=lambda: NOW + timedelta(seconds=3),
    )
    owner = ArtifactOwner(owner_type="run_attempt", owner_id=claim.attempt.attempt_id)
    prepared = finalizer.prepare(
        owner=owner,
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=(
            ArtifactMemberPayload(
                member_id="trace",
                kind=ArtifactKind.RUN_TRACE,
                content_type="application/json",
                content=b'{"event":"complete"}',
            ),
        ),
    )

    succeeded = repository.commit_success(
        finalizing,
        manifest=prepared.manifest,
        manifest_ref=prepared.manifest_ref,
        now=NOW + timedelta(seconds=4),
        receipt_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
    )

    assert succeeded.state is RunLifecycleState.SUCCEEDED
    assert succeeded.result.result_available is True
    assert succeeded.result.receipt_outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert artifact_repository.get_visible_binding(
        owner,
        now=NOW + timedelta(seconds=5),
    ) is not None


def test_cancelled_finalization_cannot_publish_prepared_artifacts(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    repository = _repository(postgres_engine)
    request = _request(1)
    repository.admit(request)
    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    finalizing = repository.mark_finalizing(claim, now=NOW + timedelta(seconds=2))
    artifact_repository = PostgresArtifactReferenceRepository(postgres_engine)
    prepared = ArtifactBundleFinalizer(
        store=FilesystemArtifactStore(tmp_path, clock=lambda: NOW + timedelta(seconds=3)),
        repository=artifact_repository,
        clock=lambda: NOW + timedelta(seconds=3),
    ).prepare(
        owner=ArtifactOwner(
            owner_type="run_attempt",
            owner_id=claim.attempt.attempt_id,
        ),
        manifest_id="019ba001-1111-7000-8000-000000000821",
        members=(
            ArtifactMemberPayload(
                member_id="receipt",
                kind=ArtifactKind.GOVERNANCE_RECEIPT,
                content_type="text/markdown",
                content=b"# Receipt",
            ),
        ),
    )
    repository.request_cancel(
        run_id=request.run_id,
        operator_subject=request.operator_subject,
        now=NOW + timedelta(seconds=4),
    )

    with pytest.raises(RunClaimRejectedError):
        repository.commit_success(
            finalizing,
            manifest=prepared.manifest,
            manifest_ref=prepared.manifest_ref,
            now=NOW + timedelta(seconds=5),
        )
    assert artifact_repository.get_visible_binding(
        prepared.manifest.owner,
        now=NOW + timedelta(seconds=6),
    ) is None


def test_conversation_single_flight_and_turn_append_commit_with_success(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    seed_agent_version(postgres_engine)
    conversation_id = "019ba001-1111-7000-8000-000000000071"
    conversations = PostgresConversationRepository(postgres_engine)
    conversations.create(
        ConversationRecord(
            conversation_id=conversation_id,
            agent_id=TEST_AGENT_ID,
            created_at=NOW.isoformat(),
            updated_at=NOW.isoformat(),
        )
    )
    repository = _repository(postgres_engine)
    request = RunRequest.model_validate(
        {
            **_request(1).model_dump(mode="json"),
            "conversation_id": conversation_id,
            "conversation_turn_count": 0,
        }
    )
    repository.admit(request)
    competing = RunRequest.model_validate(
        {
            **_request(2).model_dump(mode="json"),
            "conversation_id": conversation_id,
            "conversation_turn_count": 0,
        }
    )
    with pytest.raises(RunConversationBusyError):
        repository.admit(competing)

    activation = repository.activate_role(slot=1, executor_id="executor", now=NOW)
    claim = repository.claim_next(
        slot=1,
        executor_id="executor",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    finalizing = repository.mark_finalizing(claim, now=NOW + timedelta(seconds=2))
    prepared = ArtifactBundleFinalizer(
        store=FilesystemArtifactStore(tmp_path, clock=lambda: NOW + timedelta(seconds=3)),
        repository=PostgresArtifactReferenceRepository(postgres_engine),
        clock=lambda: NOW + timedelta(seconds=3),
    ).prepare(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id=claim.attempt.attempt_id),
        manifest_id="019ba001-1111-7000-8000-000000000872",
        members=(
            ArtifactMemberPayload(
                member_id="trace",
                kind=ArtifactKind.RUN_TRACE,
                content_type="application/json",
                content=b'{"event":"complete"}',
            ),
        ),
    )
    turn = ConversationTurn(
        turn_id="019ba001-1111-7000-8000-000000000073",
        run_id=request.run_id,
        agent_id=request.agent_id,
        question=request.question,
        final_output="等待期为30天。",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at=(NOW + timedelta(seconds=4)).isoformat(),
        context_admission=ContextAdmission(admitted=False),
    )

    repository.commit_success(
        finalizing,
        manifest=prepared.manifest,
        manifest_ref=prepared.manifest_ref,
        now=NOW + timedelta(seconds=4),
        receipt_outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        conversation_turn=turn,
        expected_conversation_turn_count=0,
    )

    persisted = conversations.get(conversation_id)
    assert persisted is not None
    assert persisted.turns == (turn,)
