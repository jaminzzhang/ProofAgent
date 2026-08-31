"""Durable public command boundary for Formal Production Agent publication."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

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
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._publisher = publisher
        self._binding_profile = binding_profile
        self._identifier_factory = identifier_factory
        self._clock = clock

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
                started_at=_timestamp(self._clock()),
            ),
        )
        reservation = self._reserve(record)
        existing = reservation.record
        if existing.receipt.request_sha256 != request_sha256:
            raise FormalProductionAgentPublicationCommandRejected(
                code="formal_publication_idempotency_conflict",
                detail="The idempotency key is already bound to a different request.",
            )
        if not reservation.created:
            return FormalProductionAgentPublicationCommandResult(
                receipt=existing.receipt,
                replayed=True,
            )

        try:
            publication = self._publisher.publish(
                agent_id=agent_id,
                draft_id=draft_id,
                draft_revision=request.draft_revision,
                binding_profile=self._binding_profile,
                evidence=request.evidence,
                smoke_question=request.smoke_question,
                actor=actor,
                command_record=existing,
            )
            completed = complete_formal_publication_command_success(existing, publication)
            return FormalProductionAgentPublicationCommandResult(
                receipt=completed.receipt,
                replayed=False,
            )
        except (
            FormalProductionAgentCandidateRejected,
            FormalProductionAgentPhaseFRejected,
            FormalProductionAgentReferenceStagingRejected,
            FormalProductionAgentOnlineSmokeRejected,
            FormalProductionAgentPublicationRejected,
        ) as exc:
            return self._complete_failure(existing, failure_code=exc.code)
        except Exception:
            return self._complete_failure(
                existing,
                failure_code="formal_publication_command_unavailable",
            )

    def _reserve(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
    ) -> FormalProductionAgentPublicationCommandReservation:
        try:
            with self._unit_of_work_factory() as uow:
                reservation = uow.formal_publication_commands.reserve(record)
                validated = FormalProductionAgentPublicationCommandReservation.model_validate(
                    reservation.model_dump(mode="python")
                )
                if (
                    validated.record.actor_subject != record.actor_subject
                    or validated.record.idempotency_key != record.idempotency_key
                ):
                    raise PersistenceInvariantError("formal command reservation identity mismatch")
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

    def _complete_failure(
        self,
        record: FormalProductionAgentPublicationCommandRecord,
        *,
        failure_code: str,
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
            replayed=validated != failed,
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


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise FormalProductionAgentPublicationCommandRejected(
            code="formal_publication_command_clock_invalid",
            detail="Formal publication command clock must be timezone-aware.",
        )
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "FormalProductionAgentPublicationCommandRejected",
    "FormalProductionAgentPublicationCommandService",
]
