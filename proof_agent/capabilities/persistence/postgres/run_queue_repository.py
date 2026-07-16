from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from secrets import token_urlsafe
from uuid import uuid4
import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    timestamp_text,
    uuid_value,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    run_attempts,
    run_executor_activations,
    run_operator_fairness,
    runs,
)
from proof_agent.capabilities.persistence.postgres.artifact_repository import (
    PostgresArtifactReferenceRepository,
)
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactManifest,
    ArtifactObjectVersion,
)
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.conversation import ConversationTurn
from proof_agent.contracts.persistence import RunMetadataRecord
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.ports.run_queue import (
    RunClaimRejectedError,
    RunConversationBusyError,
    RunExecutionSnapshotFactory,
    RunIdempotencyConflictError,
    RunQueueOverloadedError,
)
from proof_agent.contracts.run_execution import (
    RoleActivation,
    RoleActivationState,
    RunAttempt,
    RunClaim,
    RunFailure,
    RunFailureCode,
    RunLifecycleState,
    RunQueueRecord,
    RunRequest,
    RunResultAvailability,
    assert_run_transition,
)


MAX_QUEUED_RUNS = 50
MAX_ACTIVE_ATTEMPTS = 5
MAX_ATTEMPT_DEADLINE_SECONDS = 120
_QUEUE_LOCK = 0x5052415155455545
_ACTIVATION_LOCK = 0x5052414143544956
_ACTIVE_STATES = (
    RunLifecycleState.RUNNING.value,
    RunLifecycleState.FINALIZING.value,
    RunLifecycleState.CANCEL_REQUESTED.value,
)


class PostgresRunQueueRepository:
    """Transactional authority for bounded admission and fenced fair claims."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    def admit(self, request: RunRequest) -> tuple[RunQueueRecord, bool]:
        request_sha256 = request.canonical_sha256()
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            existing = connection.execute(
                self._record_select().where(
                    runs.c.submitted_by == request.operator_subject,
                    runs.c.idempotency_key == request.idempotency_key,
                )
            ).mappings().one_or_none()
            if existing is not None:
                if existing["request_sha256"] != request_sha256:
                    raise RunIdempotencyConflictError(
                        "Idempotency key is already bound to another request"
                    )
                return self._record_from_row(existing), False
            queued_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(runs)
                .where(runs.c.state == RunLifecycleState.QUEUED.value)
            ).scalar_one()
            if int(queued_count) >= MAX_QUEUED_RUNS:
                raise RunQueueOverloadedError(capacity=MAX_QUEUED_RUNS)
            if request.conversation_id is not None:
                active_conversation = connection.execute(
                    sa.select(runs.c.run_id)
                    .where(
                        runs.c.conversation_id
                        == uuid_value(request.conversation_id, field="conversation_id"),
                        runs.c.state.in_(
                            (
                                RunLifecycleState.QUEUED.value,
                                *_ACTIVE_STATES,
                            )
                        ),
                    )
                    .limit(1)
                ).scalar_one_or_none()
                if active_conversation is not None:
                    raise RunConversationBusyError(
                        "Conversation already has a non-terminal Run"
                    )
            queue_record = RunQueueRecord(
                request=request,
                request_sha256=request_sha256,
                state=RunLifecycleState.QUEUED,
                state_version=1,
                enqueued_at=request.submitted_at,
                updated_at=request.submitted_at,
            )
            metadata = self._metadata(queue_record)
            connection.execute(
                sa.insert(runs).values(
                    run_id=uuid_value(request.run_id, field="run_id"),
                    state=queue_record.state.value,
                    state_version=queue_record.state_version,
                    run_purpose=request.run_purpose.value,
                    agent_id=request.agent_id,
                    agent_version_id=uuid_value(
                        request.agent_version_id, field="agent_version_id"
                    ),
                    submitted_by=request.operator_subject,
                    request_sha256=request_sha256,
                    idempotency_key=request.idempotency_key,
                    conversation_id=(
                        None
                        if request.conversation_id is None
                        else uuid_value(request.conversation_id, field="conversation_id")
                    ),
                    request_json=request.model_dump(mode="json"),
                    enqueued_at=request.submitted_at,
                    started_at=None,
                    completed_at=None,
                    result_available=False,
                    artifact_manifest_id=None,
                    receipt_outcome=None,
                    terminal_failure_json=None,
                    run_metadata_json=model_json(metadata),
                    created_at=request.submitted_at,
                    updated_at=request.submitted_at,
                )
            )
            return queue_record, True

    def get(self, run_id: str) -> RunQueueRecord | None:
        with read_connection(self._connection_source) as connection:
            row = connection.execute(
                self._record_select().where(
                    runs.c.run_id == uuid_value(run_id, field="run_id")
                )
            ).mappings().one_or_none()
        return None if row is None else self._record_from_row(row)

    def list(self, *, limit: int = 100) -> Sequence[RunQueueRecord]:
        if not 1 <= limit <= 500:
            raise ValueError("Run list limit must be between 1 and 500")
        with read_connection(self._connection_source) as connection:
            rows = connection.execute(
                self._record_select()
                .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
                .limit(limit)
            ).mappings().all()
        return tuple(self._record_from_row(row) for row in rows)

    def list_page(
        self,
        *,
        limit: int,
        offset: int,
        run_purpose: RunPurpose | None = None,
        search: str | None = None,
        states: Sequence[RunLifecycleState] = (),
        receipt_outcome: ReceiptOutcome | None = None,
    ) -> tuple[Sequence[RunQueueRecord], int]:
        if not 1 <= limit <= 200:
            raise ValueError("Run page limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("Run page offset cannot be negative")
        if search is not None and (not search or len(search) > 256 or "\x00" in search):
            raise ValueError("Run search is invalid")
        conditions: list[sa.ColumnElement[bool]] = []
        if run_purpose is not None:
            conditions.append(runs.c.run_purpose == run_purpose.value)
        if states:
            conditions.append(runs.c.state.in_(tuple(state.value for state in states)))
        if receipt_outcome is not None:
            conditions.append(runs.c.receipt_outcome == receipt_outcome.value)
        if search is not None:
            escaped = (
                search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            conditions.append(
                sa.or_(
                    sa.cast(runs.c.run_id, sa.Text()).ilike(pattern, escape="\\"),
                    runs.c.agent_id.ilike(pattern, escape="\\"),
                    runs.c.request_json["question"].astext.ilike(pattern, escape="\\"),
                )
            )
        record_query = self._record_select()
        count_query = sa.select(sa.func.count()).select_from(runs)
        if conditions:
            record_query = record_query.where(*conditions)
            count_query = count_query.where(*conditions)
        with read_connection(self._connection_source) as connection:
            total = int(connection.execute(count_query).scalar_one())
            rows = connection.execute(
                record_query
                .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
                .limit(limit)
                .offset(offset)
            ).mappings().all()
        return tuple(self._record_from_row(row) for row in rows), total

    def activate_role(
        self,
        *,
        slot: int,
        executor_id: str,
        now: datetime,
    ) -> RoleActivation:
        if slot not in {1, 2}:
            raise ValueError("Run Executor slot must be 1 or 2")
        if not executor_id or len(executor_id) > 255:
            raise ValueError("Run Executor id is invalid")
        self._require_aware(now)
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _ACTIVATION_LOCK)
            current_epoch = connection.execute(
                sa.select(sa.func.coalesce(sa.func.max(run_executor_activations.c.activation_epoch), 0))
            ).scalar_one()
            next_epoch = int(current_epoch) + 1
            connection.execute(
                sa.update(run_executor_activations)
                .where(run_executor_activations.c.state == RoleActivationState.ACTIVE.value)
                .values(
                    state=RoleActivationState.STANDBY.value,
                    executor_id=None,
                    updated_at=now,
                )
            )
            connection.execute(
                postgres_insert(run_executor_activations)
                .values(
                    slot=slot,
                    state=RoleActivationState.ACTIVE.value,
                    activation_epoch=next_epoch,
                    executor_id=executor_id,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[run_executor_activations.c.slot],
                    set_={
                        "state": RoleActivationState.ACTIVE.value,
                        "activation_epoch": next_epoch,
                        "executor_id": executor_id,
                        "updated_at": now,
                    },
                )
            )
        return RoleActivation(
            slot=slot,
            state=RoleActivationState.ACTIVE,
            activation_epoch=next_epoch,
            executor_id=executor_id,
            updated_at=now,
        )

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
    ) -> RunClaim | None:
        self._require_aware(now)
        if not 1 <= lease_seconds <= MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError("Run lease seconds are outside the supported envelope")
        if not 1 <= deadline_seconds <= MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError("Run deadline seconds are outside the supported envelope")
        if lease_seconds >= deadline_seconds:
            raise ValueError("Run lease must be shorter than the Attempt deadline")
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            self._require_active_role(
                connection,
                slot=slot,
                executor_id=executor_id,
                activation_epoch=activation_epoch,
            )
            active_count = connection.execute(
                sa.select(sa.func.count())
                .select_from(run_attempts)
                .where(run_attempts.c.state.in_(_ACTIVE_STATES))
            ).scalar_one()
            if int(active_count) >= MAX_ACTIVE_ATTEMPTS:
                return None
            row = connection.execute(self._fair_claim_select()).mappings().one_or_none()
            if row is None:
                return None
            request = RunRequest.model_validate(row["request_json"])
            attempt_id = str(uuid4())
            attempt_number = int(
                connection.execute(
                    sa.select(sa.func.coalesce(sa.func.max(run_attempts.c.attempt_number), 0))
                    .where(run_attempts.c.run_id == row["run_id"])
                ).scalar_one()
            ) + 1
            fencing_epoch = int(
                connection.execute(sa.text("SELECT nextval('run_fencing_epoch_seq')")).scalar_one()
            )
            snapshot = snapshot_factory(request, attempt_id, attempt_number, now)
            if (
                snapshot.run_id != request.run_id
                or snapshot.attempt_id != attempt_id
                or snapshot.attempt_number != attempt_number
            ):
                raise ValueError("Snapshot authority returned a mismatched Run identity")
            claim_token = "claim_" + token_urlsafe(32)
            attempt = RunAttempt(
                attempt_id=attempt_id,
                run_id=request.run_id,
                attempt_number=attempt_number,
                state=RunLifecycleState.RUNNING,
                state_version=1,
                claim_token=claim_token,
                fencing_epoch=fencing_epoch,
                activation_epoch=activation_epoch,
                executor_id=executor_id,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                deadline_at=now + timedelta(seconds=deadline_seconds),
                snapshot=snapshot,
                snapshot_sha256=snapshot.canonical_sha256(),
                created_at=now,
                updated_at=now,
            )
            connection.execute(
                sa.insert(run_attempts).values(
                    attempt_id=uuid_value(attempt_id, field="attempt_id"),
                    run_id=row["run_id"],
                    attempt_number=attempt_number,
                    state=attempt.state.value,
                    state_version=attempt.state_version,
                    fencing_token=fencing_epoch,
                    claim_token=claim_token,
                    activation_epoch=activation_epoch,
                    executor_id=executor_id,
                    lease_owner=executor_id,
                    heartbeat_at=attempt.heartbeat_at,
                    lease_expires_at=attempt.lease_expires_at,
                    deadline_at=attempt.deadline_at,
                    snapshot_json=snapshot.model_dump(mode="json"),
                    snapshot_sha256=attempt.snapshot_sha256,
                    result_available=False,
                    artifact_manifest_id=None,
                    receipt_outcome=None,
                    terminal_failure_json=None,
                    attempt_json=attempt.model_dump(mode="json"),
                    created_at=now,
                    updated_at=now,
                )
            )
            running_record = RunQueueRecord(
                request=request,
                request_sha256=str(row["request_sha256"]),
                state=RunLifecycleState.RUNNING,
                state_version=int(row["state_version"]) + 1,
                result=RunResultAvailability(),
                enqueued_at=row["enqueued_at"],
                started_at=now,
                updated_at=now,
            )
            updated = connection.execute(
                sa.update(runs)
                .where(
                    runs.c.run_id == row["run_id"],
                    runs.c.state == RunLifecycleState.QUEUED.value,
                    runs.c.state_version == row["state_version"],
                )
                .values(
                    state=RunLifecycleState.RUNNING.value,
                    state_version=running_record.state_version,
                    started_at=now,
                    updated_at=now,
                    run_metadata_json=model_json(self._metadata(running_record)),
                )
            )
            if updated.rowcount != 1:
                raise RunClaimRejectedError("Queued Run changed during its claim")
            connection.execute(
                postgres_insert(run_operator_fairness)
                .values(
                    operator_subject=request.operator_subject,
                    last_claimed_at=now,
                    claim_count=1,
                )
                .on_conflict_do_update(
                    index_elements=[run_operator_fairness.c.operator_subject],
                    set_={
                        "last_claimed_at": now,
                        "claim_count": run_operator_fairness.c.claim_count + 1,
                    },
                )
            )
            return RunClaim(run_request=request, attempt=attempt)

    def heartbeat(
        self,
        claim: RunClaim,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> RunClaim:
        self._require_aware(now)
        if not 1 <= lease_seconds <= MAX_ATTEMPT_DEADLINE_SECONDS:
            raise ValueError("Run lease seconds are outside the supported envelope")
        with write_connection(self._connection_source) as connection:
            row = self._lock_owned_attempt(connection, claim, now=now)
            attempt = self._attempt_from_row(row)
            lease_expires_at = min(
                now + timedelta(seconds=lease_seconds),
                attempt.deadline_at,
            )
            if lease_expires_at <= now:
                raise RunClaimRejectedError("Run Attempt deadline has expired")
            renewed = attempt.model_copy(
                update={
                    "heartbeat_at": now,
                    "lease_expires_at": lease_expires_at,
                    "updated_at": now,
                }
            )
            self._write_attempt(connection, renewed, expected_state_version=attempt.state_version)
        return RunClaim(run_request=claim.run_request, attempt=renewed)

    def mark_finalizing(self, claim: RunClaim, *, now: datetime) -> RunClaim:
        self._require_aware(now)
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            row = self._lock_owned_attempt(connection, claim, now=now)
            attempt = self._attempt_from_row(row)
            assert_run_transition(attempt.state, RunLifecycleState.FINALIZING)
            finalizing_attempt = attempt.model_copy(
                update={
                    "state": RunLifecycleState.FINALIZING,
                    "state_version": attempt.state_version + 1,
                    "updated_at": now,
                }
            )
            self._write_attempt(
                connection,
                finalizing_attempt,
                expected_state_version=attempt.state_version,
            )
            run_record = self._locked_run_record(connection, claim.run_request.run_id)
            if run_record.state is not RunLifecycleState.RUNNING:
                raise RunClaimRejectedError("Run is no longer running")
            finalizing_run = run_record.model_copy(
                update={
                    "state": RunLifecycleState.FINALIZING,
                    "state_version": run_record.state_version + 1,
                    "updated_at": now,
                }
            )
            self._write_run(
                connection,
                finalizing_run,
                expected_state=RunLifecycleState.RUNNING,
                expected_state_version=run_record.state_version,
            )
        return RunClaim(run_request=claim.run_request, attempt=finalizing_attempt)

    def request_cancel(
        self,
        *,
        run_id: str,
        operator_subject: str,
        now: datetime,
    ) -> RunQueueRecord:
        self._require_aware(now)
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            current = self._locked_run_record(connection, run_id)
            if current.request.operator_subject != operator_subject:
                raise RunClaimRejectedError("Run is not owned by this operator")
            if current.state.is_terminal or current.state is RunLifecycleState.CANCEL_REQUESTED:
                return current
            if current.state is RunLifecycleState.QUEUED:
                assert_run_transition(current.state, RunLifecycleState.CANCELLED)
                cancelled = current.model_copy(
                    update={
                        "state": RunLifecycleState.CANCELLED,
                        "state_version": current.state_version + 1,
                        "failure": RunFailure(code=RunFailureCode.CANCELLED),
                        "completed_at": now,
                        "updated_at": now,
                    }
                )
                self._write_run(
                    connection,
                    cancelled,
                    expected_state=current.state,
                    expected_state_version=current.state_version,
                )
                return cancelled
            if current.state not in {
                RunLifecycleState.RUNNING,
                RunLifecycleState.FINALIZING,
            }:
                raise RunClaimRejectedError("Run cannot be cancelled from its current state")
            attempt_row = connection.execute(
                sa.select(run_attempts)
                .where(
                    run_attempts.c.run_id == uuid_value(run_id, field="run_id"),
                    run_attempts.c.state == current.state.value,
                )
                .order_by(run_attempts.c.attempt_number.desc())
                .limit(1)
                .with_for_update()
            ).mappings().one_or_none()
            if attempt_row is None:
                raise RunClaimRejectedError("Run has no cancellable Attempt")
            attempt = self._attempt_from_row(attempt_row)
            assert_run_transition(attempt.state, RunLifecycleState.CANCEL_REQUESTED)
            cancel_attempt = attempt.model_copy(
                update={
                    "state": RunLifecycleState.CANCEL_REQUESTED,
                    "state_version": attempt.state_version + 1,
                    "updated_at": now,
                }
            )
            self._write_attempt(
                connection,
                cancel_attempt,
                expected_state_version=attempt.state_version,
            )
            cancel_run = current.model_copy(
                update={
                    "state": RunLifecycleState.CANCEL_REQUESTED,
                    "state_version": current.state_version + 1,
                    "updated_at": now,
                }
            )
            self._write_run(
                connection,
                cancel_run,
                expected_state=current.state,
                expected_state_version=current.state_version,
            )
            return cancel_run

    def commit_terminal_failure(
        self,
        claim: RunClaim,
        *,
        target: RunLifecycleState,
        failure: RunFailure,
        now: datetime,
    ) -> RunQueueRecord:
        if target not in {
            RunLifecycleState.FAILED,
            RunLifecycleState.TIMED_OUT,
            RunLifecycleState.CANCELLED,
        }:
            raise ValueError("Terminal failure target is invalid")
        self._require_aware(now)
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            row = self._lock_owned_attempt(
                connection,
                claim,
                now=now,
                allow_deadline_expired=(target is RunLifecycleState.TIMED_OUT),
            )
            attempt = self._attempt_from_row(row)
            assert_run_transition(attempt.state, target)
            terminal_attempt = attempt.model_copy(
                update={
                    "state": target,
                    "state_version": attempt.state_version + 1,
                    "result": RunResultAvailability(),
                    "failure": failure,
                    "updated_at": now,
                }
            )
            self._write_attempt(
                connection,
                terminal_attempt,
                expected_state_version=attempt.state_version,
            )
            run_record = self._locked_run_record(connection, claim.run_request.run_id)
            assert_run_transition(run_record.state, target)
            terminal_run = run_record.model_copy(
                update={
                    "state": target,
                    "state_version": run_record.state_version + 1,
                    "result": RunResultAvailability(),
                    "failure": failure,
                    "completed_at": now,
                    "updated_at": now,
                }
            )
            self._write_run(
                connection,
                terminal_run,
                expected_state=run_record.state,
                expected_state_version=run_record.state_version,
            )
            return terminal_run

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
    ) -> RunQueueRecord:
        """Atomically bind exact artifacts and commit a still-live successful Attempt."""

        self._require_aware(now)
        if manifest_ref.kind is not ArtifactKind.ARTIFACT_MANIFEST:
            raise ValueError("Run success requires an artifact manifest object")
        if (
            manifest.owner.owner_type != "run_attempt"
            or manifest.owner.owner_id != claim.attempt.attempt_id
            or manifest_ref.owner != manifest.owner
        ):
            raise ValueError("Run artifact manifest owner does not match the Attempt")
        conversation_id = claim.run_request.conversation_id
        if conversation_id is None:
            if conversation_turn is not None or expected_conversation_turn_count is not None:
                raise ValueError("Conversation Turn cannot be attached to a standalone Run")
        else:
            if (
                conversation_turn is None
                or expected_conversation_turn_count is None
                or claim.run_request.conversation_turn_count
                != expected_conversation_turn_count
            ):
                raise ValueError("Conversation Run success requires its frozen Turn append")
            if (
                conversation_turn.run_id != claim.run_request.run_id
                or conversation_turn.agent_id != claim.run_request.agent_id
                or conversation_turn.question != claim.run_request.question
            ):
                raise ValueError("Conversation Turn does not match the frozen Run request")
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            row = self._lock_owned_attempt(connection, claim, now=now)
            attempt = self._attempt_from_row(row)
            if attempt.state is not RunLifecycleState.FINALIZING:
                raise RunClaimRejectedError("Only a finalizing Attempt can succeed")
            run_record = self._locked_run_record(connection, claim.run_request.run_id)
            if run_record.state is not RunLifecycleState.FINALIZING:
                raise RunClaimRejectedError("Run is no longer finalizing")
            binding = PostgresArtifactReferenceRepository(connection).commit_visible_manifest(
                manifest,
                manifest_ref=manifest_ref,
            )
            if not binding.result_available:
                raise RunClaimRejectedError("Artifact authority did not expose the result")
            result = RunResultAvailability(
                result_available=True,
                artifact_manifest_id=manifest.manifest_id,
                receipt_outcome=receipt_outcome,
            )
            terminal_attempt = attempt.model_copy(
                update={
                    "state": RunLifecycleState.SUCCEEDED,
                    "state_version": attempt.state_version + 1,
                    "result": result,
                    "failure": None,
                    "updated_at": now,
                }
            )
            self._write_attempt(
                connection,
                terminal_attempt,
                expected_state_version=attempt.state_version,
            )
            terminal_run = run_record.model_copy(
                update={
                    "state": RunLifecycleState.SUCCEEDED,
                    "state_version": run_record.state_version + 1,
                    "result": result,
                    "failure": None,
                    "completed_at": now,
                    "updated_at": now,
                }
            )
            self._write_run(
                connection,
                terminal_run,
                expected_state=RunLifecycleState.FINALIZING,
                expected_state_version=run_record.state_version,
            )
            if conversation_id is not None:
                assert conversation_turn is not None
                assert expected_conversation_turn_count is not None
                PostgresConversationRepository(connection).append_turn(
                    conversation_id,
                    conversation_turn,
                    expected_turn_count=expected_conversation_turn_count,
                )
            return terminal_run

    def reap_expired_leases(self, *, now: datetime) -> int:
        self._require_aware(now)
        reaped = 0
        with write_connection(self._connection_source) as connection:
            self._advisory_lock(connection, _QUEUE_LOCK)
            rows = connection.execute(
                sa.select(run_attempts)
                .where(
                    run_attempts.c.state.in_(_ACTIVE_STATES),
                    run_attempts.c.lease_expires_at <= now,
                )
                .order_by(run_attempts.c.lease_expires_at.asc())
                .with_for_update(skip_locked=True)
            ).mappings().all()
            for row in rows:
                attempt = self._attempt_from_row(row)
                failure = RunFailure(code=RunFailureCode.EXECUTOR_LOST)
                terminal_attempt = attempt.model_copy(
                    update={
                        "state": RunLifecycleState.FAILED,
                        "state_version": attempt.state_version + 1,
                        "result": RunResultAvailability(),
                        "failure": failure,
                        "updated_at": now,
                    }
                )
                self._write_attempt(
                    connection,
                    terminal_attempt,
                    expected_state_version=attempt.state_version,
                )
                run_record = self._locked_run_record(connection, attempt.run_id)
                if run_record.state not in {
                    RunLifecycleState.RUNNING,
                    RunLifecycleState.FINALIZING,
                    RunLifecycleState.CANCEL_REQUESTED,
                }:
                    raise RunClaimRejectedError(
                        "Expired Attempt disagrees with durable Run state"
                    )
                terminal_run = run_record.model_copy(
                    update={
                        "state": RunLifecycleState.FAILED,
                        "state_version": run_record.state_version + 1,
                        "result": RunResultAvailability(),
                        "failure": failure,
                        "completed_at": now,
                        "updated_at": now,
                    }
                )
                self._write_run(
                    connection,
                    terminal_run,
                    expected_state=run_record.state,
                    expected_state_version=run_record.state_version,
                )
                reaped += 1
        return reaped

    @staticmethod
    def _advisory_lock(connection: sa.Connection, key: int) -> None:
        connection.execute(sa.select(sa.func.pg_advisory_xact_lock(key)))

    @staticmethod
    def _require_active_role(
        connection: sa.Connection,
        *,
        slot: int,
        executor_id: str,
        activation_epoch: int,
    ) -> None:
        active = connection.execute(
            sa.select(run_executor_activations).where(
                run_executor_activations.c.slot == slot,
                run_executor_activations.c.state == RoleActivationState.ACTIVE.value,
                run_executor_activations.c.executor_id == executor_id,
                run_executor_activations.c.activation_epoch == activation_epoch,
            )
        ).first()
        if active is None:
            raise RunClaimRejectedError("Run Executor role is not active at this epoch")

    def _lock_owned_attempt(
        self,
        connection: sa.Connection,
        claim: RunClaim,
        *,
        now: datetime,
        allow_deadline_expired: bool = False,
    ) -> sa.RowMapping:
        self._require_active_role(
            connection,
            slot=self._active_slot_for_claim(connection, claim),
            executor_id=claim.attempt.executor_id,
            activation_epoch=claim.attempt.activation_epoch,
        )
        row = connection.execute(
            sa.select(run_attempts)
            .where(run_attempts.c.attempt_id == uuid_value(claim.attempt.attempt_id, field="attempt_id"))
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise RunClaimRejectedError("Run Attempt does not exist")
        if (
            str(row["run_id"]) != claim.attempt.run_id
            or row["claim_token"] != claim.attempt.claim_token
            or int(row["fencing_token"]) != claim.attempt.fencing_epoch
            or int(row["activation_epoch"]) != claim.attempt.activation_epoch
            or row["executor_id"] != claim.attempt.executor_id
        ):
            raise RunClaimRejectedError("Run Attempt claim is stale or fenced")
        if row["state"] not in _ACTIVE_STATES:
            raise RunClaimRejectedError("Run Attempt is already terminal")
        if row["lease_expires_at"] <= now:
            raise RunClaimRejectedError("Run Attempt lease has expired")
        if not allow_deadline_expired and row["deadline_at"] <= now:
            raise RunClaimRejectedError("Run Attempt deadline has expired")
        return row

    @staticmethod
    def _active_slot_for_claim(connection: sa.Connection, claim: RunClaim) -> int:
        slot = connection.execute(
            sa.select(run_executor_activations.c.slot).where(
                run_executor_activations.c.state == RoleActivationState.ACTIVE.value,
                run_executor_activations.c.activation_epoch == claim.attempt.activation_epoch,
                run_executor_activations.c.executor_id == claim.attempt.executor_id,
            )
        ).scalar_one_or_none()
        if slot is None:
            raise RunClaimRejectedError("Run Executor activation is stale")
        return int(slot)

    @staticmethod
    def _attempt_from_row(row: sa.RowMapping) -> RunAttempt:
        return RunAttempt.model_validate(row["attempt_json"])

    @staticmethod
    def _write_attempt(
        connection: sa.Connection,
        attempt: RunAttempt,
        *,
        expected_state_version: int,
    ) -> None:
        updated = connection.execute(
            sa.update(run_attempts)
            .where(
                run_attempts.c.attempt_id == uuid_value(attempt.attempt_id, field="attempt_id"),
                run_attempts.c.state_version == expected_state_version,
                run_attempts.c.claim_token == attempt.claim_token,
                run_attempts.c.fencing_token == attempt.fencing_epoch,
                run_attempts.c.activation_epoch == attempt.activation_epoch,
            )
            .values(
                state=attempt.state.value,
                state_version=attempt.state_version,
                heartbeat_at=attempt.heartbeat_at,
                lease_expires_at=attempt.lease_expires_at,
                result_available=attempt.result.result_available,
                artifact_manifest_id=(
                    None
                    if attempt.result.artifact_manifest_id is None
                    else uuid_value(
                        attempt.result.artifact_manifest_id,
                        field="artifact_manifest_id",
                    )
                ),
                receipt_outcome=(
                    None
                    if attempt.result.receipt_outcome is None
                    else attempt.result.receipt_outcome.value
                ),
                terminal_failure_json=(
                    None
                    if attempt.failure is None
                    else attempt.failure.model_dump(mode="json")
                ),
                attempt_json=attempt.model_dump(mode="json"),
                updated_at=attempt.updated_at,
            )
        )
        if updated.rowcount != 1:
            raise RunClaimRejectedError("Run Attempt conditional update was fenced")

    def _locked_run_record(
        self, connection: sa.Connection, run_id: str
    ) -> RunQueueRecord:
        row = connection.execute(
            self._record_select()
            .where(runs.c.run_id == uuid_value(run_id, field="run_id"))
            .with_for_update()
        ).mappings().one_or_none()
        if row is None:
            raise RunClaimRejectedError("Run does not exist")
        return self._record_from_row(row)

    def _write_run(
        self,
        connection: sa.Connection,
        record: RunQueueRecord,
        *,
        expected_state: RunLifecycleState,
        expected_state_version: int,
    ) -> None:
        updated = connection.execute(
            sa.update(runs)
            .where(
                runs.c.run_id == uuid_value(record.request.run_id, field="run_id"),
                runs.c.state == expected_state.value,
                runs.c.state_version == expected_state_version,
            )
            .values(
                state=record.state.value,
                state_version=record.state_version,
                started_at=record.started_at,
                completed_at=record.completed_at,
                result_available=record.result.result_available,
                artifact_manifest_id=(
                    None
                    if record.result.artifact_manifest_id is None
                    else uuid_value(
                        record.result.artifact_manifest_id,
                        field="artifact_manifest_id",
                    )
                ),
                receipt_outcome=(
                    None
                    if record.result.receipt_outcome is None
                    else record.result.receipt_outcome.value
                ),
                terminal_failure_json=(
                    None
                    if record.failure is None
                    else record.failure.model_dump(mode="json")
                ),
                run_metadata_json=model_json(self._metadata(record)),
                updated_at=record.updated_at,
            )
        )
        if updated.rowcount != 1:
            raise RunClaimRejectedError("Run conditional update was fenced")
        connection.execute(
            sa.select(
                sa.func.pg_notify(
                    "proofagent_run_progress",
                    json.dumps(
                        {
                            "run_id": record.request.run_id,
                            "state": record.state.value,
                            "state_version": record.state_version,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
        )

    @staticmethod
    def _fair_claim_select() -> sa.Select[tuple[object, ...]]:
        candidate = runs.alias("candidate_run")
        earlier = runs.alias("earlier_operator_run")
        no_earlier_operator_head = ~sa.exists(
            sa.select(sa.literal(1)).where(
                earlier.c.state == RunLifecycleState.QUEUED.value,
                earlier.c.submitted_by == candidate.c.submitted_by,
                sa.tuple_(earlier.c.created_at, earlier.c.run_id)
                < sa.tuple_(candidate.c.created_at, candidate.c.run_id),
            )
        )
        return (
            sa.select(candidate)
            .outerjoin(
                run_operator_fairness,
                run_operator_fairness.c.operator_subject == candidate.c.submitted_by,
            )
            .where(
                candidate.c.state == RunLifecycleState.QUEUED.value,
                no_earlier_operator_head,
            )
            .order_by(
                run_operator_fairness.c.last_claimed_at.asc().nullsfirst(),
                candidate.c.created_at.asc(),
                candidate.c.run_id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True, of=candidate)
        )

    @staticmethod
    def _record_select() -> sa.Select[tuple[object, ...]]:
        return sa.select(
            runs.c.run_id,
            runs.c.state,
            runs.c.state_version,
            runs.c.request_sha256,
            runs.c.request_json,
            runs.c.enqueued_at,
            runs.c.started_at,
            runs.c.completed_at,
            runs.c.result_available,
            runs.c.artifact_manifest_id,
            runs.c.receipt_outcome,
            runs.c.terminal_failure_json,
            runs.c.updated_at,
        )

    @staticmethod
    def _record_from_row(row: sa.RowMapping) -> RunQueueRecord:
        return RunQueueRecord(
            request=RunRequest.model_validate(row["request_json"]),
            request_sha256=str(row["request_sha256"]),
            state=RunLifecycleState(row["state"]),
            state_version=int(row["state_version"]),
            result=RunResultAvailability(
                result_available=bool(row["result_available"]),
                artifact_manifest_id=(
                    None
                    if row["artifact_manifest_id"] is None
                    else str(row["artifact_manifest_id"])
                ),
                receipt_outcome=(
                    None
                    if row["receipt_outcome"] is None
                    else ReceiptOutcome(row["receipt_outcome"])
                ),
            ),
            failure=row["terminal_failure_json"],
            enqueued_at=row["enqueued_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _metadata(record: RunQueueRecord) -> RunMetadataRecord:
        return RunMetadataRecord(
            run_id=record.request.run_id,
            state=record.state,
            state_version=record.state_version,
            run_purpose=RunPurpose(record.request.run_purpose),
            agent_id=record.request.agent_id,
            agent_version_id=record.request.agent_version_id,
            submitted_by=record.request.operator_subject,
            created_at=timestamp_text(record.enqueued_at),
            updated_at=timestamp_text(record.updated_at),
            error_code=(None if record.failure is None else record.failure.code.value),
        )

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.utcoffset() is None:
            raise ValueError("Run queue timestamp must be timezone-aware")


__all__ = [
    "MAX_ACTIVE_ATTEMPTS",
    "MAX_ATTEMPT_DEADLINE_SECONDS",
    "MAX_QUEUED_RUNS",
    "PostgresRunQueueRepository",
]
