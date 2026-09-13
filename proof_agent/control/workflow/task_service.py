"""Task commands validated by the Control Plane before durable authority changes."""

from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any
from uuid import uuid4

from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.ports.workflow_tasks import WorkflowTaskRepository
from proof_agent.contracts.workflow_task import (
    AnswerSubmission,
    CriterionAssessment,
    GoalContract,
    QuestionRequest,
    QuestionState,
    ResumeIntent,
    TaskBudgetUsage,
    TaskOwner,
    TaskPhase,
    TypedAnswer,
    WorkflowTaskSnapshot,
    aware_time,
)


TERMINAL_PHASES = frozenset({"complete", "failed", "cancelled"})


def _changed(
    snapshot: WorkflowTaskSnapshot, *, now: datetime, **updates: Any
) -> WorkflowTaskSnapshot:
    return WorkflowTaskSnapshot.model_validate(
        {
            **snapshot.model_dump(mode="python"),
            **updates,
            "version": snapshot.version + 1,
            "updated_at": now,
        }
    )


def _blocked(questions: tuple[QuestionState, ...], revision: int) -> bool:
    return any(
        item.request.blocking
        and item.request.goal_revision == revision
        and item.status in {"pending", "expired"}
        for item in questions
    )


def reduce_question(
    snapshot: WorkflowTaskSnapshot, question: QuestionRequest, *, now: datetime
) -> WorkflowTaskSnapshot:
    if snapshot.phase in TERMINAL_PHASES or snapshot.phase == "paused":
        raise PersistenceInvariantError("task cannot ask in its current phase")
    if (
        question.task_id != snapshot.goal.task_id
        or question.goal_revision != snapshot.goal.revision
    ):
        raise PersistenceInvariantError("question must bind the current goal")
    if question.expires_at <= now or question.expires_at > snapshot.raw_content_expires_at:
        raise PersistenceInvariantError("question expiry must be inside the task retention window")
    if not set(question.affected_criteria).issubset(
        {c.criterion_id for c in snapshot.goal.acceptance_criteria}
    ):
        raise PersistenceInvariantError("question contains unknown acceptance criteria")
    if not question.blocking and any(
        f.name in snapshot.goal.required_context for f in question.fields
    ):
        raise PersistenceInvariantError("required context cannot become a nonblocking question")
    for existing in snapshot.questions:
        if (
            existing.request.goal_revision == question.goal_revision
            and existing.request.dedupe_key == question.dedupe_key
        ):
            left = existing.request.model_dump(
                exclude={"question_id", "expires_at", "checkpoint_ref", "stage"}
            )
            right = question.model_dump(
                exclude={"question_id", "expires_at", "checkpoint_ref", "stage"}
            )
            if left != right:
                raise PersistenceIdempotencyConflictError(
                    "question dedupe key was reused for different fields"
                )
            return snapshot
        if existing.request.question_id == question.question_id:
            raise PersistenceIdempotencyConflictError("question id was already used")
    return _changed(
        snapshot,
        now=now,
        questions=(*snapshot.questions, QuestionState(request=question, asked_at=now)),
        phase="waiting_for_input" if question.blocking else snapshot.phase,
    )


def reduce_answer(
    snapshot: WorkflowTaskSnapshot, answer: TypedAnswer, *, now: datetime, intent_id: str
) -> AnswerSubmission:
    if answer.expected_goal_revision != snapshot.goal.revision:
        raise PersistenceConflictError(
            resource_type="workflow_goal",
            resource_id=snapshot.goal.task_id,
            expected_revision=answer.expected_goal_revision,
            actual_revision=snapshot.goal.revision,
        )
    fingerprint = answer.fingerprint()
    for previous in snapshot.questions:
        if (
            previous.answer is not None
            and previous.answer.idempotency_key == answer.idempotency_key
        ):
            if previous.answer_fingerprint != fingerprint:
                raise PersistenceIdempotencyConflictError("answer idempotency key was reused")
            return AnswerSubmission(snapshot=snapshot, replayed=True)
    item = next(
        (q for q in snapshot.questions if q.request.question_id == answer.question_id), None
    )
    if item is None:
        raise PersistenceNotFoundError(
            resource_type="workflow_question", resource_id=answer.question_id
        )
    if item.status == "answered":
        if item.answer_fingerprint != fingerprint:
            raise PersistenceIdempotencyConflictError("question already has a different answer")
        return AnswerSubmission(snapshot=snapshot, replayed=True)
    if snapshot.phase in TERMINAL_PHASES or snapshot.phase == "paused":
        raise PersistenceInvariantError("task cannot accept answers in its current phase")
    if item.status != "pending" or item.request.expires_at <= now:
        raise PersistenceInvariantError("question is expired or superseded")
    fields = {field.name: field for field in item.request.fields}
    if set(answer.values) - set(fields) or any(
        f.required and f.name not in answer.values for f in fields.values()
    ):
        raise PersistenceInvariantError("answer fields do not match the question schema")
    expected_types = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
    }
    for name, value in answer.values.items():
        field = fields[name]
        if type(value) not in expected_types[field.value_type]:
            raise PersistenceInvariantError("answer value does not match its declared type")
        if isinstance(value, str) and (
            len(value) > field.max_length or (field.choices and value not in field.choices)
        ):
            raise PersistenceInvariantError("answer value violates its declared bounds")
    answered = QuestionState(
        request=item.request,
        asked_at=item.asked_at,
        status="answered",
        answer=answer,
        answer_fingerprint=fingerprint,
        answered_at=now,
    )
    questions = tuple(
        answered if q.request.question_id == answer.question_id else q for q in snapshot.questions
    )
    should_resume = snapshot.phase == "waiting_for_input" and not _blocked(
        questions, snapshot.goal.revision
    )
    intent = None
    if should_resume:
        answered = answered.model_copy(update={"resume_intent_id": intent_id})
        questions = tuple(
            answered if q.request.question_id == answer.question_id else q for q in questions
        )
        intent = ResumeIntent(
            intent_id=intent_id,
            task_id=snapshot.goal.task_id,
            owner=snapshot.owner,
            goal_revision=snapshot.goal.revision,
            snapshot_version=snapshot.version + 1,
            question_id=answer.question_id,
            checkpoint_ref=item.request.checkpoint_ref,
            created_at=now,
        )
    updated = _changed(
        snapshot, now=now, questions=questions, phase="active" if should_resume else snapshot.phase
    )
    return AnswerSubmission(snapshot=updated, resume_intent=intent)


class WorkflowTaskService:
    def __init__(self, repository: WorkflowTaskRepository) -> None:
        self.repository = repository

    def create(
        self,
        goal: GoalContract,
        *,
        owner: TaskOwner,
        now: datetime,
        latest_run_id: str | None = None,
        creation_request_sha256: str | None = None,
        conversation_id: str | None = None,
        allow_untrusted_web_supplement: bool = False,
    ) -> WorkflowTaskSnapshot:
        aware_time(now)
        if goal.revision != 1:
            raise PersistenceInvariantError("new tasks must start at goal revision one")
        from proof_agent.control.knowledge.answer_requirements import compile_goal_requirements
        goal = compile_goal_requirements(goal)
        snapshot = WorkflowTaskSnapshot(
            goal=goal,
            owner=owner,
            creation_request_sha256=creation_request_sha256,
            conversation_id=conversation_id,
            allow_untrusted_web_supplement=allow_untrusted_web_supplement,
            version=1,
            latest_run_id=latest_run_id,
            latest_run_goal_revision=1 if latest_run_id else None,
            created_at=now,
            updated_at=now,
            raw_content_expires_at=now + timedelta(days=90),
        )
        self.repository.create(snapshot)
        return snapshot

    def get(self, task_id: str, *, owner: TaskOwner) -> WorkflowTaskSnapshot:
        snapshot = self.repository.get(task_id, owner=owner)
        if snapshot is None:
            raise PersistenceNotFoundError(resource_type="workflow_task", resource_id=task_id)
        return snapshot

    def request_resume(
        self, task_id: str, *, owner: TaskOwner, expected_version: int, now: datetime
    ) -> ResumeIntent:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        if current.phase not in {"active", "paused"} or _blocked(
            current.questions, current.goal.revision
        ):
            raise PersistenceInvariantError(
                "task cannot continue with unanswered required questions"
            )
        updated = _changed(current, now=now, phase="active")
        identity = sha256(
            f"{task_id}:{current.goal.revision}:{current.version}".encode()
        ).hexdigest()
        intent = ResumeIntent(
            kind="continue",
            intent_id=f"continue-{identity}",
            task_id=task_id,
            owner=owner,
            goal_revision=current.goal.revision,
            snapshot_version=updated.version,
            checkpoint_ref=f"{current.latest_run_id or task_id}:{current.digest()}",
            created_at=now,
        )
        self.repository.compare_and_swap(
            updated, owner=owner, expected_version=current.version, resume_intent=intent
        )
        return intent

    def renew_expired_questions(self, task_id: str, *, owner: TaskOwner, expected_version: int,
                                now: datetime) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        if current.phase not in {"paused", "waiting_for_input"}:
            raise PersistenceInvariantError("question renewal requires a waiting or paused task")
        questions: list[QuestionState] = []
        renewed: list[QuestionState] = []
        for item in current.questions:
            if (item.request.goal_revision != current.goal.revision or item.status not in {"pending", "expired"}
                    or item.request.expires_at > now):
                questions.append(item)
                continue
            questions.append(QuestionState(request=item.request, asked_at=item.asked_at, status="superseded"))
            lifetime = timedelta(days=1) if item.asked_at is None else item.request.expires_at - item.asked_at
            lifetime = min(max(lifetime, timedelta(seconds=1)), timedelta(days=7))
            identity = sha256(f"{item.request.question_id}:{current.version}".encode()).hexdigest()
            request = QuestionRequest.model_validate({**item.request.model_dump(mode="python"),
                "question_id": f"q-renew-{identity[:32]}", "dedupe_key": identity,
                "checkpoint_ref": f"{current.latest_run_id or task_id}:{current.digest()}",
                "expires_at": min(now + lifetime, current.raw_content_expires_at)})
            renewed.append(QuestionState(request=request, asked_at=now))
        if not renewed:
            return current
        updated = _changed(current, now=now, questions=tuple([*questions, *renewed]), phase="waiting_for_input")
        self.repository.compare_and_swap(updated, owner=owner, expected_version=current.version)
        return updated

    def record_failed_run(
        self, task_id: str, run_id: str, *, owner: TaskOwner, now: datetime
    ) -> WorkflowTaskSnapshot:
        """A lost/failed execution has unknown consumption; it cannot silently reset a budget."""
        current = self.get(task_id, owner=owner)
        if (
            current.latest_run_id != run_id
            or current.phase in TERMINAL_PHASES
            or current.latest_run_goal_revision != current.goal.revision
            or (current.phase == "paused" and current.budget_usage.tokens is None)
        ):
            return current
        usage = current.budget_usage.model_copy(
            update={
                "tokens": None,
                "unknown_model_calls": current.budget_usage.unknown_model_calls + 1,
            }
        )
        updated = _changed(current, now=now, budget_usage=usage, phase="paused")
        self.repository.compare_and_swap(updated, owner=owner, expected_version=current.version)
        return updated

    def _current(
        self, task_id: str, *, owner: TaskOwner, expected_version: int, now: datetime
    ) -> WorkflowTaskSnapshot:
        aware_time(now)
        current = self.get(task_id, owner=owner)
        if current.version != expected_version:
            raise PersistenceConflictError(
                resource_type="workflow_task",
                resource_id=task_id,
                expected_revision=expected_version,
                actual_revision=current.version,
            )
        if now >= current.raw_content_expires_at:
            raise PersistenceInvariantError("workflow task retention has expired")
        if now < current.updated_at:
            raise PersistenceInvariantError("task command timestamp is stale")
        return current

    def ask(
        self,
        task_id: str,
        question: QuestionRequest,
        *,
        owner: TaskOwner,
        expected_version: int,
        now: datetime,
    ) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        updated = reduce_question(current, question, now=now)
        if updated is not current:
            self.repository.compare_and_swap(
                updated, owner=owner, expected_version=expected_version
            )
        return updated

    def answer(
        self, task_id: str, answer: TypedAnswer, *, owner: TaskOwner, now: datetime
    ) -> AnswerSubmission:
        aware_time(now)
        for _ in range(8):
            current = self.get(task_id, owner=owner)
            if now >= current.raw_content_expires_at or now < current.updated_at:
                raise PersistenceInvariantError("workflow task timestamp or retention is invalid")
            result = reduce_answer(current, answer, now=now, intent_id=f"resume-{uuid4().hex}")
            if result.replayed:
                return result
            try:
                self.repository.compare_and_swap(
                    result.snapshot,
                    owner=owner,
                    expected_version=current.version,
                    resume_intent=result.resume_intent,
                )
                return result
            except PersistenceConflictError:
                continue
        raise PersistenceConflictError(
            resource_type="workflow_task",
            resource_id=task_id,
            expected_revision=current.version,
            actual_revision=None,
        )

    def revise_goal(
        self,
        task_id: str,
        goal: GoalContract,
        *,
        owner: TaskOwner,
        expected_version: int,
        now: datetime,
    ) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        if (
            current.phase in TERMINAL_PHASES
            or goal.task_id != task_id
            or goal.revision != current.goal.revision + 1
        ):
            raise PersistenceInvariantError("goal revision must advance an unfinished task by one")
        from proof_agent.control.knowledge.answer_requirements import compile_goal_requirements
        goal = compile_goal_requirements(goal, previous_goal=current.goal)
        questions = tuple(
                QuestionState(request=q.request, asked_at=q.asked_at, status="superseded")
            if q.status in {"pending", "expired"}
            else q
            for q in current.questions
        )
        updated = _changed(
            current,
            now=now,
            goal=goal,
            questions=questions,
            assessments=(),
            phase="active" if current.phase == "waiting_for_input" else current.phase,
        )
        self.repository.compare_and_swap(updated, owner=owner, expected_version=expected_version)
        return updated

    def assess(
        self,
        task_id: str,
        assessments: tuple[CriterionAssessment, ...],
        *,
        owner: TaskOwner,
        expected_version: int,
        now: datetime,
        verified_proof_refs: tuple[str, ...],
    ) -> WorkflowTaskSnapshot:
        """Internal only: caller supplies proof references from successful Control Plane gates."""
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        if current.phase != "active":
            raise PersistenceInvariantError("only active tasks can accept verifier results")
        criteria = {
            criterion.criterion_id: criterion for criterion in current.goal.acceptance_criteria
        }
        merged = {item.criterion_id: item for item in current.assessments}
        for assessment in assessments:
            criterion = criteria.get(assessment.criterion_id)
            if (
                criterion is None
                or assessment.verifier != criterion.verifier
                or assessment.goal_revision != current.goal.revision
            ):
                raise PersistenceInvariantError("assessment must bind its current goal criterion")
            if assessment.status == "satisfied":
                if not set(assessment.proof_refs).issubset(verified_proof_refs):
                    raise PersistenceInvariantError(
                        "assessment includes an unverified proof reference"
                    )
                parameter = {
                    "source_support": criterion.query,
                    "verified_tool": criterion.tool_step_id,
                    "answer_coverage": criterion.expected_text,
                }[criterion.verifier]
                if parameter is None:
                    raise PersistenceInvariantError(
                        "criterion without verification basis must remain unassessed"
                    )
            merged[assessment.criterion_id] = assessment
        updated = _changed(current, now=now, assessments=tuple(merged.values()))
        self.repository.compare_and_swap(updated, owner=owner, expected_version=expected_version)
        return updated

    def transition(
        self,
        task_id: str,
        phase: TaskPhase,
        *,
        owner: TaskOwner,
        expected_version: int,
        now: datetime,
    ) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        allowed = {
            "active": {"paused", "complete", "failed", "cancelled"},
            "waiting_for_input": {"paused", "failed", "cancelled"},
            "paused": {"active", "waiting_for_input", "cancelled"},
        }
        if phase not in allowed.get(current.phase, set()):
            raise PersistenceInvariantError("invalid workflow task phase transition")
        if phase == "active" and _blocked(current.questions, current.goal.revision):
            raise PersistenceInvariantError("unanswered required questions prevent task resumption")
        if phase == "complete":
            satisfied = {
                a.criterion_id
                for a in current.assessments
                if a.status == "satisfied" and a.goal_revision == current.goal.revision
            }
            if not {
                c.criterion_id for c in current.goal.acceptance_criteria if c.required
            }.issubset(satisfied):
                raise PersistenceInvariantError(
                    "all required criteria need verification before completion"
                )
        updated = _changed(current, now=now, phase=phase)
        self.repository.compare_and_swap(updated, owner=owner, expected_version=expected_version)
        return updated

    def expire_questions(
        self, task_id: str, *, owner: TaskOwner, expected_version: int, now: datetime
    ) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        questions = tuple(
                QuestionState(request=q.request, asked_at=q.asked_at, status="expired")
            if q.status == "pending" and q.request.expires_at <= now
            else q
            for q in current.questions
        )
        if questions == current.questions:
            return current
        updated = _changed(current, now=now, questions=questions)
        self.repository.compare_and_swap(updated, owner=owner, expected_version=expected_version)
        return updated

    def bind_run(
        self,
        task_id: str,
        run_id: str,
        *,
        owner: TaskOwner,
        expected_version: int,
        now: datetime,
        usage_delta: TaskBudgetUsage | None = None,
    ) -> WorkflowTaskSnapshot:
        current = self._current(task_id, owner=owner, expected_version=expected_version, now=now)
        if current.phase in TERMINAL_PHASES:
            raise PersistenceInvariantError("terminal task cannot bind another run")
        previous = current.budget_usage
        delta = usage_delta or TaskBudgetUsage()
        usage = TaskBudgetUsage(
            model_calls=previous.model_calls + delta.model_calls,
            retrieval_calls=previous.retrieval_calls + delta.retrieval_calls,
            tool_calls=previous.tool_calls + delta.tool_calls,
            tokens=None
            if previous.tokens is None or delta.tokens is None
            else previous.tokens + delta.tokens,
            unknown_model_calls=previous.unknown_model_calls + delta.unknown_model_calls,
            active_seconds=previous.active_seconds + delta.active_seconds,
        )
        updated = _changed(
            current,
            now=now,
            latest_run_id=run_id,
            latest_run_goal_revision=current.goal.revision,
            budget_usage=usage,
        )
        self.repository.compare_and_swap(updated, owner=owner, expected_version=expected_version)
        return updated

    def apply_update(
        self,
        update: Any,
        *,
        owner: TaskOwner,
        now: datetime,
        run_id: str,
        expected_snapshot_sha256: str,
    ) -> WorkflowTaskSnapshot:
        """Commit one internal V3 result through a single CAS, joined to the Run transaction."""
        from proof_agent.contracts.workflow_task_update import WorkflowTaskUpdate

        if not isinstance(update, WorkflowTaskUpdate):
            raise PersistenceInvariantError("task updates must use the internal V3 contract")
        current = self._current(
            update.task_id, owner=owner, expected_version=update.expected_version, now=now
        )
        if (
            current.digest() != expected_snapshot_sha256
            or current.goal.revision != update.goal_revision
        ):
            raise PersistenceInvariantError(
                "task update does not match the frozen execution snapshot"
            )
        if current.phase != "active" or current.latest_run_id != run_id:
            raise PersistenceInvariantError("task update does not own the active run")
        criteria = {c.criterion_id: c for c in current.goal.acceptance_criteria}
        merged = {a.criterion_id: a for a in current.assessments}
        for assessment in update.assessments:
            criterion = criteria.get(assessment.criterion_id)
            if (
                criterion is None
                or assessment.verifier != criterion.verifier
                or assessment.goal_revision != current.goal.revision
            ):
                raise PersistenceInvariantError("task assessment is not bound to its criterion")
            if assessment.status == "satisfied":
                if not set(assessment.proof_refs).issubset(update.verified_proof_refs):
                    raise PersistenceInvariantError("task assessment references unverified proof")
                basis = {
                    "source_support": criterion.query,
                    "verified_tool": criterion.tool_step_id,
                    "answer_coverage": criterion.expected_text,
                }[criterion.verifier]
                if basis is None:
                    raise PersistenceInvariantError(
                        "criterion without a verification basis remains unassessed"
                    )
            merged[assessment.criterion_id] = assessment
        previous = current.budget_usage
        delta = update.usage_delta
        usage = TaskBudgetUsage(
            model_calls=previous.model_calls + delta.model_calls,
            retrieval_calls=previous.retrieval_calls + delta.retrieval_calls,
            tool_calls=previous.tool_calls + delta.tool_calls,
            tokens=None
            if previous.tokens is None or delta.tokens is None
            else previous.tokens + delta.tokens,
            unknown_model_calls=previous.unknown_model_calls + delta.unknown_model_calls,
            active_seconds=previous.active_seconds + delta.active_seconds,
        )
        questions = current.questions
        phase: TaskPhase = update.phase
        if update.question is not None:
            draft = update.question
            identity = sha256(
                json.dumps(
                    [f.model_dump(mode="json") for f in draft.fields],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            requested = QuestionRequest(
                question_id=f"q-{current.goal.revision}-{identity[:32]}",
                task_id=current.goal.task_id,
                goal_revision=current.goal.revision,
                stage=draft.stage,
                fields=draft.fields,
                affected_criteria=draft.affected_criteria,
                expires_at=min(
                    now + timedelta(seconds=draft.wait_timeout_seconds),
                    current.raw_content_expires_at,
                ),
                dedupe_key=identity,
                checkpoint_ref=f"{run_id}:{current.digest()}",
            )
            projected = reduce_question(current, requested, now=now)
            questions = projected.questions
            phase = projected.phase
        elif phase == "waiting_for_input":
            raise PersistenceInvariantError("waiting task update requires a question")
        updated = _changed(
            current,
            now=now,
            assessments=tuple(merged.values()),
            budget_usage=usage,
            questions=questions,
            phase=phase,
        )
        self.repository.compare_and_swap(updated, owner=owner, expected_version=current.version)
        return updated
