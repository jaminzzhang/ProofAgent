"""Task admission and outbox publication into the existing governed Run queue."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import Engine

from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
)
from proof_agent.contracts.ports.run_queue import RunQueueRepository
from proof_agent.contracts.ports.workflow_tasks import WorkflowTaskRepository
from proof_agent.contracts.published_agent import PublishedAgent
from proof_agent.contracts.workflow_task import (
    GoalContract,
    ResumeIntent,
    TaskOwner,
    WorkflowTaskSnapshot,
)
from proof_agent.control.workflow.task_service import WorkflowTaskService
from proof_agent.delivery.run_submission_service import RunSubmissionService


class TaskExecutionService:
    def __init__(
        self,
        repository: WorkflowTaskRepository,
        *,
        engine: Engine | None = None,
        queue: RunQueueRepository | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine
        self.queue = queue

    @contextmanager
    def transaction(self) -> Iterator[tuple[WorkflowTaskRepository, RunQueueRepository | None]]:
        if self.engine is None:
            yield self.repository, self.queue
            return
        from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
            PostgresRunQueueRepository,
        )
        from proof_agent.capabilities.persistence.postgres.workflow_task_repository import (
            PostgresWorkflowTaskRepository,
        )

        with self.engine.begin() as connection:
            yield PostgresWorkflowTaskRepository(connection), PostgresRunQueueRepository(connection)

    def create(
        self,
        *,
        goal: GoalContract,
        owner: TaskOwner,
        request_sha256: str,
        published_agent: PublishedAgent,
        now: datetime,
        admission: dict[str, Any],
        conversation_id: str | None = None,
        conversation_turn_count: int | None = None,
        allow_untrusted_web_supplement: bool = False,
    ) -> tuple[WorkflowTaskSnapshot, bool]:
        run_id = str(uuid5(NAMESPACE_URL, f"{goal.task_id}:initial"))
        with self.transaction() as (repository, queue):
            service = WorkflowTaskService(repository)
            existing = repository.get(goal.task_id, owner=owner)
            if existing is not None:
                if existing.creation_request_sha256 != request_sha256:
                    raise PersistenceIdempotencyConflictError(
                        "task creation key was reused for another request"
                    )
                return existing, False
            try:
                snapshot = service.create(
                    goal,
                    owner=owner,
                    now=now,
                    latest_run_id=run_id,
                    creation_request_sha256=request_sha256,
                    conversation_id=conversation_id,
                    allow_untrusted_web_supplement=allow_untrusted_web_supplement,
                )
            except PersistenceConflictError:
                existing = service.get(goal.task_id, owner=owner)
                if existing.creation_request_sha256 != request_sha256:
                    raise PersistenceIdempotencyConflictError(
                        "task creation key was reused for another request"
                    ) from None
                return existing, False
            if queue is not None:
                self._submit(
                    queue,
                    snapshot,
                    published_agent,
                    now=now,
                    idempotency_key=f"task-initial:{goal.task_id}",
                    admission=admission,
                    conversation_turn_count=conversation_turn_count,
                )
            return snapshot, True

    def dispatch(
        self,
        intent: ResumeIntent,
        *,
        owner: TaskOwner,
        published_agent: PublishedAgent,
        now: datetime,
        admission: dict[str, Any],
        conversation_turn_count: int | None = None,
    ) -> WorkflowTaskSnapshot:
        run_id = str(uuid5(NAMESPACE_URL, intent.intent_id))
        with self.transaction() as (repository, queue):
            service = WorkflowTaskService(repository)
            current = service.get(intent.task_id, owner=owner)
            if current.latest_run_id == run_id:
                return current
            if (
                current.goal.revision != intent.goal_revision
                or current.phase != "active"
                or intent.owner != owner
            ):
                raise PersistenceInvariantError("resume intent no longer matches its task")
            if current.version != intent.snapshot_version:
                raise PersistenceInvariantError(
                    "resume intent does not own the current task version"
                )
            snapshot = service.bind_run(
                intent.task_id, run_id, owner=owner, expected_version=current.version, now=now
            )
            if queue is not None:
                self._submit(
                    queue,
                    snapshot,
                    published_agent,
                    now=now,
                    idempotency_key=intent.intent_id,
                    admission=admission,
                    conversation_turn_count=conversation_turn_count,
                )
                repository.mark_resume_dispatched(intent.intent_id, owner=owner, run_id=run_id)
            return snapshot

    @staticmethod
    def _submit(
        queue: RunQueueRepository,
        snapshot: WorkflowTaskSnapshot,
        published_agent: PublishedAgent,
        *,
        now: datetime,
        idempotency_key: str,
        admission: dict[str, Any],
        conversation_turn_count: int | None,
    ) -> None:
        if published_agent.agent_version_id != snapshot.owner.agent_version:
            raise PersistenceInvariantError(
                "task execution requires its frozen Published Agent Version"
            )
        assert snapshot.latest_run_id is not None
        RunSubmissionService(
            queue, clock=lambda: now, run_id_factory=lambda: snapshot.latest_run_id or ""
        ).submit(
            published_agent=published_agent,
            question=snapshot.goal.objective,
            operator_subject=snapshot.owner.actor_subject,
            idempotency_key=idempotency_key,
            conversation_id=snapshot.conversation_id,
            conversation_turn_count=conversation_turn_count,
            allow_untrusted_web_supplement=snapshot.allow_untrusted_web_supplement,
            task_id=snapshot.goal.task_id,
            expected_task_version=snapshot.version,
            task_snapshot_sha256=snapshot.digest(),
            **admission,
        )
