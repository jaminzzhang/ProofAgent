"""PostgreSQL authority for task snapshots and transactional HIL recovery intents."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from proof_agent.capabilities.persistence.postgres._common import (
    ConnectionSource,
    model_json,
    read_connection,
    write_connection,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    workflow_task_resumes,
    workflow_tasks,
)
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.ports.workflow_tasks import validate_swap
from proof_agent.contracts.workflow_task import (
    ResumeIntent,
    TaskOwner,
    WorkflowTaskSnapshot,
    aware_time,
)


def _owner_clause(table: sa.Table, owner: TaskOwner) -> sa.ColumnElement[bool]:
    return sa.and_(
        table.c.actor_subject == owner.actor_subject,
        table.c.agent_id == owner.agent_id,
        table.c.agent_version == owner.agent_version,
    )


class PostgresWorkflowTaskRepository:
    """Engine writes own a transaction; Connection writes join the caller's transaction."""

    def __init__(self, connection_source: ConnectionSource) -> None:
        self._connection_source = connection_source

    @staticmethod
    def _decode(row: Mapping[Any, Any]) -> WorkflowTaskSnapshot:
        snapshot = WorkflowTaskSnapshot.model_validate(row["snapshot_json"])
        if (
            snapshot.digest() != row["snapshot_sha256"]
            or snapshot.version != row["version"]
            or snapshot.goal.revision != row["goal_revision"]
            or snapshot.schema_version != row["schema_version"]
            or snapshot.phase != row["phase"]
            or snapshot.owner.actor_subject != row["actor_subject"]
            or snapshot.owner.agent_id != row["agent_id"]
            or snapshot.owner.agent_version != row["agent_version"]
            or snapshot.raw_content_expires_at != row["raw_content_expires_at"]
        ):
            raise PersistenceInvariantError("workflow snapshot integrity mismatch")
        return snapshot

    def create(self, snapshot: WorkflowTaskSnapshot) -> None:
        if snapshot.version != 1 or snapshot.goal.revision != 1:
            raise PersistenceInvariantError("new workflow snapshot must start at version one")
        if len(snapshot.model_dump_json().encode()) > 524288:
            raise PersistenceInvariantError("workflow snapshot exceeds bounded storage size")
        with write_connection(self._connection_source) as connection:
            inserted = connection.execute(
                postgres_insert(workflow_tasks)
                .values(
                    task_id=snapshot.goal.task_id,
                    **snapshot.owner.model_dump(),
                    version=snapshot.version,
                    goal_revision=snapshot.goal.revision,
                    schema_version=snapshot.schema_version,
                    phase=snapshot.phase,
                    snapshot_json=model_json(snapshot),
                    snapshot_sha256=snapshot.digest(),
                    created_at=snapshot.created_at,
                    updated_at=snapshot.updated_at,
                    raw_content_expires_at=snapshot.raw_content_expires_at,
                )
                .on_conflict_do_nothing(index_elements=[workflow_tasks.c.task_id])
                .returning(workflow_tasks.c.task_id)
            ).scalar_one_or_none()
            if inserted is None:
                raise PersistenceConflictError(
                    resource_type="workflow_task",
                    resource_id=snapshot.goal.task_id,
                    expected_revision=0,
                    actual_revision=None,
                )

    def get(self, task_id: str, *, owner: TaskOwner) -> WorkflowTaskSnapshot | None:
        with read_connection(self._connection_source) as connection:
            row = (
                connection.execute(
                    sa.select(workflow_tasks).where(
                        workflow_tasks.c.task_id == task_id, _owner_clause(workflow_tasks, owner)
                    )
                )
                .mappings()
                .one_or_none()
            )
            return None if row is None else self._decode(row)

    def compare_and_swap(
        self,
        snapshot: WorkflowTaskSnapshot,
        *,
        owner: TaskOwner,
        expected_version: int,
        resume_intent: ResumeIntent | None = None,
    ) -> None:
        with write_connection(self._connection_source) as connection:
            row = (
                connection.execute(
                    sa.select(workflow_tasks)
                    .where(
                        workflow_tasks.c.task_id == snapshot.goal.task_id,
                        _owner_clause(workflow_tasks, owner),
                    )
                    .with_for_update()
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise PersistenceNotFoundError(
                    resource_type="workflow_task", resource_id=snapshot.goal.task_id
                )
            validate_swap(
                self._decode(row),
                snapshot,
                owner=owner,
                expected_version=expected_version,
                resume_intent=resume_intent,
            )
            connection.execute(
                sa.update(workflow_tasks)
                .where(
                    workflow_tasks.c.task_id == snapshot.goal.task_id,
                    workflow_tasks.c.version == expected_version,
                    _owner_clause(workflow_tasks, owner),
                )
                .values(
                    version=snapshot.version,
                    goal_revision=snapshot.goal.revision,
                    phase=snapshot.phase,
                    snapshot_json=model_json(snapshot),
                    snapshot_sha256=snapshot.digest(),
                    updated_at=snapshot.updated_at,
                )
            )
            if resume_intent is not None:
                connection.execute(
                    workflow_task_resumes.insert().values(
                        intent_id=resume_intent.intent_id,
                        task_id=resume_intent.task_id,
                        **owner.model_dump(),
                        goal_revision=resume_intent.goal_revision,
                        intent_json=model_json(resume_intent),
                        created_at=resume_intent.created_at,
                    )
                )

    def list_pending_resumes(
        self, *, owner: TaskOwner, limit: int = 100
    ) -> tuple[ResumeIntent, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("resume list limit must be between one and 500")
        with read_connection(self._connection_source) as connection:
            rows = (
                connection.execute(
                    sa.select(workflow_task_resumes.c.intent_json)
                    .where(
                        _owner_clause(workflow_task_resumes, owner),
                        workflow_task_resumes.c.run_id.is_(None),
                    )
                    .order_by(workflow_task_resumes.c.created_at, workflow_task_resumes.c.intent_id)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return tuple(ResumeIntent.model_validate(row) for row in rows)

    def mark_resume_dispatched(self, intent_id: str, *, owner: TaskOwner, run_id: str) -> None:
        if not run_id or len(run_id) > 128:
            raise ValueError("resume run id must be bounded")
        with write_connection(self._connection_source) as connection:
            row = connection.execute(
                sa.select(workflow_task_resumes.c.run_id)
                .where(
                    workflow_task_resumes.c.intent_id == intent_id,
                    _owner_clause(workflow_task_resumes, owner),
                )
                .with_for_update()
            ).one_or_none()
            if row is None:
                raise PersistenceNotFoundError(
                    resource_type="workflow_resume", resource_id=intent_id
                )
            if row.run_id is not None and row.run_id != run_id:
                raise PersistenceInvariantError("resume intent already belongs to a different run")
            connection.execute(
                sa.update(workflow_task_resumes)
                .where(
                    workflow_task_resumes.c.intent_id == intent_id,
                    _owner_clause(workflow_task_resumes, owner),
                )
                .values(run_id=run_id)
            )

    def purge_expired(self, *, now: datetime) -> int:
        aware_time(now)
        with write_connection(self._connection_source) as connection:
            return connection.execute(
                sa.delete(workflow_tasks).where(workflow_tasks.c.raw_content_expires_at <= now)
            ).rowcount
