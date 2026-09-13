from __future__ import annotations

from datetime import datetime
from typing import Protocol

from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.workflow_task import ResumeIntent, TaskOwner, WorkflowTaskSnapshot


class WorkflowTaskRepository(Protocol):
    """Full snapshots are private mutable authority with atomic resume outbox writes."""

    def create(self, snapshot: WorkflowTaskSnapshot) -> None: ...

    def get(self, task_id: str, *, owner: TaskOwner) -> WorkflowTaskSnapshot | None: ...

    def compare_and_swap(
        self,
        snapshot: WorkflowTaskSnapshot,
        *,
        owner: TaskOwner,
        expected_version: int,
        resume_intent: ResumeIntent | None = None,
    ) -> None: ...

    def list_pending_resumes(
        self, *, owner: TaskOwner, limit: int = 100
    ) -> tuple[ResumeIntent, ...]: ...

    def mark_resume_dispatched(self, intent_id: str, *, owner: TaskOwner, run_id: str) -> None:
        """Call only after idempotent queue publication, or within its transaction."""
        ...

    def purge_expired(self, *, now: datetime) -> int: ...


def validate_swap(
    current: WorkflowTaskSnapshot,
    updated: WorkflowTaskSnapshot,
    *,
    owner: TaskOwner,
    expected_version: int,
    resume_intent: ResumeIntent | None = None,
) -> None:
    """Shared adapter invariant check, independent of a storage implementation."""
    if current.owner != owner or updated.owner != owner:
        raise PersistenceNotFoundError(
            resource_type="workflow_task", resource_id=current.goal.task_id
        )
    if current.version != expected_version:
        raise PersistenceConflictError(
            resource_type="workflow_task",
            resource_id=current.goal.task_id,
            expected_revision=expected_version,
            actual_revision=current.version,
        )
    if (
        updated.version != expected_version + 1
        or current.goal.task_id != updated.goal.task_id
        or updated.created_at != current.created_at
        or updated.raw_content_expires_at != current.raw_content_expires_at
        or updated.creation_request_sha256 != current.creation_request_sha256
        or updated.conversation_id != current.conversation_id
        or updated.allow_untrusted_web_supplement != current.allow_untrusted_web_supplement
        or updated.updated_at < current.updated_at
        or updated.goal.revision not in {current.goal.revision, current.goal.revision + 1}
    ):
        raise PersistenceInvariantError(
            "workflow task swap violates immutable identity or revision"
        )
    if updated.goal.revision == current.goal.revision and updated.goal != current.goal:
        raise PersistenceInvariantError("goal edits require a new goal revision")
    if current.phase in {"complete", "failed", "cancelled"}:
        raise PersistenceInvariantError("terminal workflow task cannot be changed")
    if updated.phase == "complete":
        satisfied = {
            item.criterion_id
            for item in updated.assessments
            if item.status == "satisfied" and item.goal_revision == updated.goal.revision
        }
        if not {
            item.criterion_id for item in updated.goal.acceptance_criteria if item.required
        }.issubset(satisfied):
            raise PersistenceInvariantError("required criteria have not been verified")
    for key in (
        "model_calls",
        "retrieval_calls",
        "tool_calls",
        "unknown_model_calls",
        "active_seconds",
    ):
        if getattr(updated.budget_usage, key) < getattr(current.budget_usage, key):
            raise PersistenceInvariantError("cumulative workflow budget cannot decrease")
    previous_tokens = current.budget_usage.tokens
    tokens = updated.budget_usage.tokens
    if (previous_tokens is None and tokens is not None) or (
        previous_tokens is not None and tokens is not None and tokens < previous_tokens
    ):
        raise PersistenceInvariantError("unknown or accumulated token usage cannot be reset")
    if len(updated.model_dump_json().encode()) > 524288:
        raise PersistenceInvariantError("workflow snapshot exceeds bounded storage size")
    if resume_intent is not None:
        if (
            resume_intent.task_id != updated.goal.task_id
            or resume_intent.owner != owner
            or resume_intent.goal_revision != updated.goal.revision
            or resume_intent.snapshot_version != updated.version
            or updated.phase != "active"
            or (
                resume_intent.kind == "question_answer"
                and not any(
                    q.request.question_id == resume_intent.question_id
                    and q.resume_intent_id == resume_intent.intent_id
                    and q.status == "answered"
                    for q in updated.questions
                )
            )
        ):
            raise PersistenceInvariantError(
                "resume intent must describe the exact committed answer"
            )
