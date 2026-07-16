from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.contracts.ports.run_queue import RunQueueRepository
from proof_agent.contracts.run_execution import RunQueueRecord, RunRequest
from proof_agent.delivery.published_agents import PublishedAgent


class RunSubmissionRejectedError(ValueError):
    """Submission failed before the durable queue was mutated."""


class RunSubmissionService:
    """Fast admission boundary: validate the frozen Agent identity and persist QUEUED."""

    def __init__(
        self,
        repository: RunQueueRepository,
        *,
        clock: Callable[[], datetime] | None = None,
        run_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))
        self._run_id_factory = run_id_factory or (lambda: str(uuid4()))

    def submit(
        self,
        *,
        published_agent: PublishedAgent,
        question: str,
        operator_subject: str,
        idempotency_key: str,
        permission_mapping_version_id: str | None,
        permission_epoch: int,
        institution_authorization: InstitutionAuthorizationContext | None = None,
        conversation_id: str | None = None,
        conversation_turn_count: int | None = None,
        allow_untrusted_web_supplement: bool = False,
        run_purpose: RunPurpose = RunPurpose.PRODUCTION,
    ) -> tuple[RunQueueRecord, bool]:
        if published_agent.agent_version_id is None:
            raise RunSubmissionRejectedError(
                "Run admission requires an immutable Published Agent Version"
            )
        if permission_mapping_version_id is None or permission_epoch < 1:
            raise RunSubmissionRejectedError(
                "Run admission requires the authenticated permission authority version"
            )
        now = self._clock()
        if now.utcoffset() is None:
            raise RunSubmissionRejectedError("Run admission clock must be timezone-aware")
        request = RunRequest(
            run_id=self._run_id_factory(),
            operator_subject=operator_subject,
            idempotency_key=idempotency_key,
            run_purpose=run_purpose,
            agent_id=published_agent.agent_id,
            agent_version_id=published_agent.agent_version_id,
            question=question,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
            conversation_id=conversation_id,
            conversation_turn_count=conversation_turn_count,
            permission_mapping_version_id=permission_mapping_version_id,
            permission_epoch=permission_epoch,
            institution_authorization=(
                institution_authorization or InstitutionAuthorizationContext()
            ),
            submitted_at=now,
        )
        return self._repository.admit(request)


__all__ = ["RunSubmissionRejectedError", "RunSubmissionService"]
