"""Development-only SQLite task authority; production composition must use PostgreSQL."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from threading import RLock
from collections.abc import Iterator

from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.workflow_task import ResumeIntent, TaskOwner, WorkflowTaskSnapshot
from proof_agent.contracts.ports.workflow_tasks import validate_swap


class FileWorkflowTaskRepository:
    """A local development file with transactional CAS and an atomic answer outbox."""

    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            destination = Path(path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.touch(mode=0o600, exist_ok=True)
            destination.chmod(0o600)
        self._connection = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._lock = RLock()
        self._connection.executescript("""
            PRAGMA busy_timeout=5000;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS workflow_tasks (
                task_id TEXT PRIMARY KEY, owner_json TEXT NOT NULL, version INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_task_resumes (
                intent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES workflow_tasks(task_id) ON DELETE CASCADE,
                owner_json TEXT NOT NULL, intent_json TEXT NOT NULL, run_id TEXT);
        """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    @staticmethod
    def _owner(owner: TaskOwner) -> str:
        return json.dumps(owner.model_dump(), sort_keys=True)

    @staticmethod
    def _decode(row: sqlite3.Row) -> WorkflowTaskSnapshot:
        snapshot = WorkflowTaskSnapshot.model_validate_json(row["snapshot_json"])
        if snapshot.digest() != row["snapshot_sha256"] or snapshot.version != row["version"]:
            raise PersistenceInvariantError("workflow snapshot integrity mismatch")
        return snapshot

    def create(self, snapshot: WorkflowTaskSnapshot) -> None:
        if snapshot.version != 1 or snapshot.goal.revision != 1:
            raise PersistenceInvariantError("new workflow snapshot must start at version one")
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO workflow_tasks VALUES (?,?,?,?,?,?)",
                (
                    snapshot.goal.task_id,
                    self._owner(snapshot.owner),
                    snapshot.version,
                    snapshot.model_dump_json(),
                    snapshot.digest(),
                    snapshot.raw_content_expires_at.astimezone(UTC).isoformat(),
                ),
            )
            if cursor.rowcount != 1:
                raise PersistenceConflictError(
                    resource_type="workflow_task",
                    resource_id=snapshot.goal.task_id,
                    expected_revision=0,
                    actual_revision=None,
                )

    def get(self, task_id: str, *, owner: TaskOwner) -> WorkflowTaskSnapshot | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM workflow_tasks WHERE task_id=? AND owner_json=?",
                (task_id, self._owner(owner)),
            ).fetchone()
            return None if row is None else self._decode(row)

    def compare_and_swap(
        self,
        snapshot: WorkflowTaskSnapshot,
        *,
        owner: TaskOwner,
        expected_version: int,
        resume_intent: ResumeIntent | None = None,
    ) -> None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM workflow_tasks WHERE task_id=? AND owner_json=?",
                (snapshot.goal.task_id, self._owner(owner)),
            ).fetchone()
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
                "UPDATE workflow_tasks SET version=?,snapshot_json=?,snapshot_sha256=? WHERE task_id=?",
                (
                    snapshot.version,
                    snapshot.model_dump_json(),
                    snapshot.digest(),
                    snapshot.goal.task_id,
                ),
            )
            if resume_intent is not None:
                connection.execute(
                    "INSERT INTO workflow_task_resumes VALUES (?,?,?,?,NULL)",
                    (
                        resume_intent.intent_id,
                        resume_intent.task_id,
                        self._owner(owner),
                        resume_intent.model_dump_json(),
                    ),
                )

    def list_pending_resumes(
        self, *, owner: TaskOwner, limit: int = 100
    ) -> tuple[ResumeIntent, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("resume list limit must be between one and 500")
        with self._lock:
            rows = self._connection.execute(
                "SELECT r.intent_json FROM workflow_task_resumes r JOIN workflow_tasks t ON t.task_id=r.task_id "
                "WHERE r.owner_json=? AND r.run_id IS NULL ORDER BY r.intent_id LIMIT ?",
                (self._owner(owner), limit),
            ).fetchall()
            return tuple(ResumeIntent.model_validate_json(row["intent_json"]) for row in rows)

    def mark_resume_dispatched(self, intent_id: str, *, owner: TaskOwner, run_id: str) -> None:
        if not run_id or len(run_id) > 128:
            raise ValueError("resume run id must be bounded")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT run_id FROM workflow_task_resumes WHERE intent_id=? AND owner_json=?",
                (intent_id, self._owner(owner)),
            ).fetchone()
            if row is None:
                raise PersistenceNotFoundError(
                    resource_type="workflow_resume", resource_id=intent_id
                )
            if row["run_id"] is not None and row["run_id"] != run_id:
                raise PersistenceInvariantError("resume intent already belongs to a different run")
            connection.execute(
                "UPDATE workflow_task_resumes SET run_id=? WHERE intent_id=?", (run_id, intent_id)
            )

    def purge_expired(self, *, now: datetime) -> int:
        with self._transaction() as connection:
            return connection.execute(
                "DELETE FROM workflow_tasks WHERE expires_at<=?", (now.astimezone(UTC).isoformat(),)
            ).rowcount

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class InMemoryWorkflowTaskRepository(FileWorkflowTaskRepository):
    def __init__(self) -> None:
        super().__init__(":memory:")
