"""Durable public command boundary for Formal Production Agent publication."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from proof_agent.contracts import (
    AuditActorFacts,
    FormalProductionAgentCandidate,
    FormalProductionAgentPublicationCommandReceipt,
    FormalProductionAgentPublicationCommandRequest,
    FormalProductionAgentPublicationCommandResult,
    FormalProductionAgentPublicationCommandState,
    ProductionKssBindingProfile,
)
from proof_agent.contracts.persistence import (
    FormalProductionAgentPublicationExecutionClaim,
    FormalProductionAgentPublicationCommandRecord,
    FormalProductionAgentPublicationCommandReservation,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
    complete_formal_publication_command_success,
)
from proof_agent.contracts.ports import (
    ConfigurationUnitOfWork,
    FormalProductionAgentPublicationCommandRepository,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateRejected,
)
from proof_agent.control.formal_production_agent_online_smoke import (
    FormalProductionAgentOnlineSmokeRejected,
)
from proof_agent.control.formal_production_agent_phase_f import (
    FormalProductionAgentPhaseFRejected,
)
from proof_agent.control.formal_production_agent_publication import (
    FormalProductionAgentPublicationRejected,
    FormalProductionAgentPublisher,
)
from proof_agent.control.formal_production_agent_reference_staging import (
    FormalProductionAgentReferenceStagingRejected,
)

_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class _CommandUnitOfWork(ConfigurationUnitOfWork, Protocol):
    @property
    def formal_publication_commands(
        self,
    ) -> FormalProductionAgentPublicationCommandRepository: ...


class FormalProductionAgentPublicationCommandRejected(RuntimeError):
    """Stable rejection before a durable command result can be returned."""

    def __init__(self, *, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


class FormalProductionAgentPublicationCommandService:
    """Reserve once, publish outside the reservation transaction, and replay."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], _CommandUnitOfWork],
        publisher: FormalProductionAgentPublisher,
        binding_profile: ProductionKssBindingProfile,
        identifier_factory: Callable[[], str] = lambda: str(uuid4()),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        execution_owner: str | None = None,
        lease_duration: timedelta = timedelta(minutes=15),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._publisher = publisher
        self._binding_profile = binding_profile
        self._identifier_factory = identifier_factory
        self._clock = clock
        self._execution_owner = _execution_owner(execution_owner or str(uuid4()))
        self._lease_duration = _lease_duration(lease_duration)

    def preflight(
        self,
        *,
        agent_id: str,
        draft_id: str,
        draft_revision: int,
    ) -> FormalProductionAgentCandidate:
        """Assemble a deployment-bound candidate without reserving a command."""

        return self._publisher.preflight(
            agent_id=agent_id,
            draft_id=draft_id,
            draft_revision=draft_revision,
            binding_profile=self._binding_profile,
        )

    def publish(
        self,
        *,
        agent_id: str,
        draft_id: str,
        request: FormalProductionAgentPublicationCommandRequest,
        idempotency_key: str,
        actor: AuditActorFacts,
    ) -> FormalProductionAgentPublicationCommandResult:
        key = _validate_idempotency_key(idempotency_key)
        request_sha256 = _request_sha256(
            agent_id=agent_id,
            draft_id=draft_id,
            request=request,
        )
        started_at = _aware_timestamp(self._clock())
        record = FormalProductionAgentPublicationCommandRecord(
            actor_subject=actor.subject,
            idempotency_key=key,
            receipt=FormalProductionAgentPublicationCommandReceipt(
                command_id=_nonblank_identifier(self._identifier_factory()),
                state=FormalProductionAgentPublicationCommandState.IN_PROGRESS,
                agent_id=agent_id,
                draft_id=draft_id,
                draft_revision=request.draft_revision,
                request_sha256=request_sha256,
                started_at=_timestamp(started_at),
            ),
            execution_claim=FormalProductionAgentPublicationExecutionClaim(
                fencing_token=1,
                owner_id=self._execution_owner,
                lease_expires_at=_timestamp(started_at + self._lease_duration),
            ),
        )
        reservation = self._reserve(record)
        existing = reservation.record
        if existing.receipt.request_sha256 != request_sha256:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_idempotency_conflict",
                detail="The idempotency key is already bound to a different request.",
            )
        if not reservation.acquired:
            return FormalProductionAgentPublicationCommandResult(
                receipt=existing.receipt,
                replayed=True,
            )
        replayed = not reservation.created
        active_record = existing

        try:
            candidate = self._publisher.preflight(
                agent_id=agent_id,
                draft_id=draft_id,
                draft_revision=request.draft_revision,
                binding_profile=self._binding_profile,
            )
            active_record = self._checkpoint_candidate(active_record, candidate=candidate)
            publication = self._publisher.publish_checkpointed_candidate(
                candidate=candidate,
                evidence=request.evidence,
                smoke_question=request.smoke_question,
                actor=actor,
                command_record=active_record,
            )
            completed = complete_formal_publication_command_success(active_record, publication)
            return FormalProductionAgentPublicationCommandResult(
                receipt=completed.receipt,
                replayed=replayed,
            )
        except (
            FormalProductionAgentCandidateRejected,
            FormalProductionAgentPhaseFRejected,
            FormalProductionAgentReferenceStagingRejected,
            FormalProductionAgentOnlineSmokeRejected,
            FormalProductionAgentPublicationRejected,
        ) as exc:
            return self._complete_failure(
                active_record,
                failure_code=exc.code,
                replayed=replayed,
            )
        except Exception:
            return self._complete_failure(
                active_record,
                failure_code="formal_publication_command_unavailable",
                replayed=replayed,
            )

    def get_receipt(
        self,
        *,
        agent_id: str,
        draft_id: str,
        command_id: str,
        actor: AuditActorFacts,
    ) -> FormalProductionAgentPublicationCommandReceipt:
        """Read one trace-safe receipt owned by the exact requesting actor."""

        exact_command_id = _query_command_id(command_id)
        try:
            with self._unit_of_work_factory() as uow:
                found = uow.formal_publication_commands.find_owned(
                    command_id=exact_command_id,
                    actor_subject=actor.subject,
                )
                record = (
                    None
                    if found is None
                    else FormalProductionAgentPublicationCommandRecord.model_validate(
                        found.model_dump(mode="python")
                    )
                )
        except Exception as exc:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_command_storage_unavailable",
                detail="Formal publication command storage is unavailable.",
            ) from exc
        if record is None:
            raise _command_not_found()
        receipt = record.receipt
        if record.actor_subject != actor.subject or receipt.command_id != exact_command_id:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_command_storage_unavailable",
                detail="Formal publication command storage is inconsistent.",
            )
        if receipt.agent_id != agent_id or receipt.draft_id != draft_id:
            raise _command_not_found()
        return receipt

    def _reserve(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandReservation:
        try:
            with self._unit_of_work_factory() as uow:
                reservation = uow.formal_publication_commands.reserve(
                    record,
                    lease_duration=self._lease_duration,
                )
                validated = FormalProductionAgentPublicationCommandReservation.model_validate(
                    reservation.model_dump(mode="python")
                )
                if (
                    validated.record.actor_subject != record.actor_subject
                    or validated.record.idempotency_key != record.idempotency_key
                ):
                    raise PersistenceInvariantError("formal command reservation identity mismatch")
                if validated.created and not validated.acquired:
                    raise PersistenceInvariantError(
                        "new formal command reservation was not acquired"
                    )
                if validated.acquired:
                    claim = validated.record.execution_claim
                    if claim is None or claim.owner_id != self._execution_owner:
                        raise PersistenceInvariantError(
                            "formal command reservation execution claim mismatch"
                        )
                uow.commit()
            return validated
        except PersistenceIdempotencyConflictError as exc:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_idempotency_conflict",
                detail="The idempotency key is already bound to a different request.",
            ) from exc
        except FormalProductionAgentPublicationCommandRejected:
            raise
        except Exception as exc:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_command_storage_unavailable",
                detail="Formal publication command storage is unavailable.",
            ) from exc

    def _checkpoint_candidate(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        candidate: FormalProductionAgentCandidate,
    ) -> FormalProductionAgentPublicationCommandRecord:
        try:
            with self._unit_of_work_factory() as uow:
                checkpointed = uow.formal_publication_commands.checkpoint_candidate(
                    record,
                    formal_candidate_sha256=candidate.formal_candidate_sha256,
                    knowledge_release_candidate_sha256=(
                        candidate.knowledge_release_candidate_sha256
                    ),
                )
                validated = FormalProductionAgentPublicationCommandRecord.model_validate(
                    checkpointed.model_dump(mode="python")
                )
                if (
                    validated.actor_subject != record.actor_subject
                    or validated.idempotency_key != record.idempotency_key
                    or validated.receipt != record.receipt
                    or validated.execution_claim != record.execution_claim
                ):
                    raise PersistenceInvariantError(
                        "formal command candidate checkpoint identity mismatch"
                    )
                uow.commit()
        except Exception as exc:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_command_storage_unavailable",
                detail="Formal publication command storage is unavailable.",
            ) from exc
        checkpoint = validated.candidate_checkpoint
        if (
            checkpoint is None
            or checkpoint.formal_candidate_sha256 != candidate.formal_candidate_sha256
            or checkpoint.knowledge_release_candidate_sha256
            != candidate.knowledge_release_candidate_sha256
        ):
            raise FormalProductionAgentCandidateRejected(
                code="formal_publication_candidate_checkpoint_conflict",
                detail="The durable Formal Candidate checkpoint does not match.",
            )
        return validated

    def _complete_failure(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        failure_code: str,
        replayed: bool,
    ) -> FormalProductionAgentPublicationCommandResult:
        failed = record.model_copy(
            update={
                "receipt": record.receipt.model_copy(
                    update={
                        "state": FormalProductionAgentPublicationCommandState.FAILED,
                        "completed_at": _timestamp(self._clock()),
                        "failure_code": failure_code,
                    }
                )
            }
        )
        try:
            with self._unit_of_work_factory() as uow:
                completed = uow.formal_publication_commands.complete(failed)
                validated = FormalProductionAgentPublicationCommandRecord.model_validate(
                    completed.model_dump(mode="python")
                )
                uow.commit()
        except Exception as exc:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_command_storage_unavailable",
                detail="Formal publication command storage is unavailable.",
            ) from exc
        return FormalProductionAgentPublicationCommandResult(
            receipt=validated.receipt,
            replayed=replayed or validated != failed,
        )


def _request_sha256(
    *,
    agent_id: str,
    draft_id: str,
    request: FormalProductionAgentPublicationCommandRequest,
) -> str:
    payload = {
        "agent_id": agent_id,
        "draft_id": draft_id,
        "request": request.model_dump(mode="json"),
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_idempotency_key(value: str) -> str:
    if not _IDEMPOTENCY_KEY.fullmatch(value):
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_idempotency_key_invalid",
            detail="A valid Idempotency-Key is required.",
        )
    return value


def _nonblank_identifier(value: str) -> str:
    if not value.strip() or len(value) > 128:
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_command_identifier_invalid",
            detail="The formal publication command identifier is invalid.",
        )
    return value


def _query_command_id(value: str) -> str:
    try:
        return str(UUID(value))
    except (AttributeError, ValueError):
        raise _command_not_found() from None


def _command_not_found() -> FormalProductionAgentPublicationCommandRejected:
    return FormalProductionAgentPublicationCommandRejected(
        code="formal_publication_command_not_found",
        detail="The formal publication command was not found.",
    )


def _execution_owner(value: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", normalized) is None:
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_command_execution_owner_invalid",
            detail="The formal publication command execution owner is invalid.",
        )
    return normalized


def _lease_duration(value: timedelta) -> timedelta:
    if value <= timedelta(0) or value > timedelta(hours=1):
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_command_lease_invalid",
            detail="The formal publication command lease duration is invalid.",
        )
    return value


def _aware_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_command_clock_invalid",
            detail="Formal publication command clock must be timezone-aware.",
        )
    return value.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    return _aware_timestamp(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "FormalProductionAgentPublicationCommandRejected",
    "FormalProductionAgentPublicationCommandService",
]
