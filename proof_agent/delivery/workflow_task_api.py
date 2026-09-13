"""Owner-scoped task/HIL API; production execution enters only the durable Run queue."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Iterator, Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from proof_agent.contracts.conversation import ContextAdmission, ConversationTurn
from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.ports.run_queue import (
    RunConversationBusyError,
    RunIdempotencyConflictError,
    RunQueueOverloadedError,
)
from proof_agent.contracts.published_agent import PublishedAgent
from proof_agent.contracts.workflow_task import (
    AcceptanceCriterion,
    GoalContract,
    TaskOwner,
    TypedAnswer,
    WorkflowTaskSnapshot,
)
from proof_agent.control.conversation import admit_conversation_context
from proof_agent.control.workflow.task_service import WorkflowTaskService
from proof_agent.delivery.task_execution_service import TaskExecutionService
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
    require_operator_permission,
)


router = APIRouter(tags=["workflow-tasks"])


class TaskCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=2048)
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = Field(default=(), max_length=32)
    constraints: tuple[str, ...] = Field(default=(), max_length=32)
    required_context: tuple[str, ...] = Field(default=(), max_length=32)
    conversation_id: str | None = Field(default=None, max_length=128)
    allow_untrusted_web_supplement: bool = False


class TaskIdentityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str = Field(min_length=1, max_length=128)
    agent_version: str = Field(min_length=1, max_length=128)


class TaskAnswerBody(TaskIdentityBody):
    answer: TypedAnswer


class TaskGoalBody(TaskIdentityBody):
    expected_version: int = Field(ge=1)
    goal: GoalContract


class TaskPhaseBody(TaskIdentityBody):
    expected_version: int = Field(ge=1)
    phase: Literal["paused", "active", "waiting_for_input", "cancelled"]


@contextmanager
def _errors() -> Iterator[None]:
    try:
        yield
    except PersistenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="workflow_task_not_found") from exc
    except (PersistenceConflictError, PersistenceIdempotencyConflictError) as exc:
        raise HTTPException(status_code=409, detail="workflow_task_conflict") from exc
    except (RunConversationBusyError, RunIdempotencyConflictError) as exc:
        raise HTTPException(status_code=409, detail="workflow_task_run_conflict") from exc
    except RunQueueOverloadedError as exc:
        raise HTTPException(
            status_code=429,
            detail="run_queue_overloaded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except PersistenceInvariantError as exc:
        raise HTTPException(status_code=409, detail="workflow_task_transition_rejected") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid_workflow_task_request") from exc


def _service(request: Request) -> TaskExecutionService:
    repository = getattr(request.app.state, "workflow_task_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="workflow_task_authority_unavailable")
    repository.purge_expired(now=datetime.now(UTC))
    return TaskExecutionService(
        repository,
        engine=getattr(request.app.state, "workflow_task_engine", None),
        queue=getattr(request.app.state, "run_queue_repository", None),
    )


def _owner(identity: OperatorIdentityContext, body: TaskIdentityBody) -> TaskOwner:
    return TaskOwner(
        actor_subject=identity.operator_id, agent_id=body.agent_id, agent_version=body.agent_version
    )


def _version(agent: PublishedAgent) -> str:
    return agent.agent_version_id or f"local:{sha256(agent.manifest_path.read_bytes()).hexdigest()}"


def _agent(request: Request, agent_id: str, version: str | None = None) -> PublishedAgent:
    registry = request.app.state.published_agents
    exact = getattr(registry, "resolve_exact", None)
    agent = (
        exact(agent_id=agent_id, version_id=version)
        if version and callable(exact)
        else registry.resolve(agent_id)
    )
    if agent is None or (version is not None and _version(agent) != version):
        raise HTTPException(
            status_code=409 if version else 404, detail="task_agent_version_unavailable"
        )
    return cast(PublishedAgent, agent)


def _admission(identity: OperatorIdentityContext) -> dict[str, Any]:
    return {
        "permission_mapping_version_id": identity.permission_mapping_version_id,
        "permission_epoch": identity.permission_epoch,
        "institution_authorization": identity.institution_authorization,
    }


def _conversation(request: Request, conversation_id: str | None, agent_id: str) -> Any:
    if conversation_id is None:
        return None
    from proof_agent.delivery.api import _get_conversation_repository, _get_conversation_store

    repository = _get_conversation_repository(request)
    conversation = (
        repository.get(conversation_id)
        if repository is not None
        else _get_conversation_store(request).get_conversation(conversation_id)
    )
    if conversation is None or conversation.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="task_conversation_not_found")
    return conversation


def _projection(snapshot: WorkflowTaskSnapshot, **extra: Any) -> dict[str, Any]:
    return {"task": snapshot.model_dump(mode="json"), "run_id": snapshot.latest_run_id, **extra}


def _local_result(request: Request, snapshot: WorkflowTaskSnapshot) -> dict[str, Any]:
    store = getattr(request.app.state, "store", None)
    if store is None or snapshot.latest_run_id is None:
        return {}
    detail = store.get_run_detail(snapshot.latest_run_id)
    if detail is None:
        return {}
    from proof_agent.delivery.api import _final_output_from_trace
    return {"final_output": _final_output_from_trace(detail), "outcome": detail.outcome.value,
        "evidence": [chunk.model_dump(mode="json") for chunk in detail.evidence_chunks]}


def _execute_local(
    request: Request,
    snapshot: WorkflowTaskSnapshot,
    agent: PublishedAgent,
    identity: OperatorIdentityContext,
) -> dict[str, Any]:
    from proof_agent.delivery.api import _execute_published_agent_run, _get_conversation_store

    conversation = _conversation(request, snapshot.conversation_id, snapshot.owner.agent_id)
    turn_id = str(uuid4())
    context = ContextAdmission(admitted=False)
    if conversation is not None:
        context = admit_conversation_context(
            conversation, current_question=snapshot.goal.objective, current_turn_id=turn_id
        )
    context = context.model_copy(update={"workflow_task": snapshot})
    try:
        result, detail, _ = _execute_published_agent_run(
            app_request=request,
            published_agent=agent,
            question=snapshot.goal.objective,
            conversation_context=context,
            run_id=snapshot.latest_run_id,
            institution_authorization=identity.institution_authorization,
            allow_untrusted_web_supplement=snapshot.allow_untrusted_web_supplement,
        )
    except Exception as exc:
        WorkflowTaskService(_service(request).repository).record_failed_run(
            snapshot.goal.task_id,
            snapshot.latest_run_id or "",
            owner=snapshot.owner,
            now=datetime.now(UTC),
        )
        raise HTTPException(status_code=500, detail="workflow_task_execution_failed") from exc
    update = getattr(result.workflow_template_execution_result, "workflow_task_update", None)
    if update is None:
        WorkflowTaskService(_service(request).repository).record_failed_run(
            snapshot.goal.task_id,
            snapshot.latest_run_id or "",
            owner=snapshot.owner,
            now=datetime.now(UTC),
        )
        raise HTTPException(status_code=500, detail="workflow_task_update_missing")
    updated = WorkflowTaskService(_service(request).repository).apply_update(
        update,
        owner=snapshot.owner,
        now=datetime.now(UTC),
        run_id=detail.run_id,
        expected_snapshot_sha256=snapshot.digest(),
    )
    if conversation is not None:
        turn = ConversationTurn(
            turn_id=turn_id,
            task_state=context.task_state,
            run_id=detail.run_id,
            agent_id=agent.agent_id,
            question=snapshot.goal.objective,
            final_output=result.final_output,
            outcome=detail.outcome,
            created_at=datetime.now(UTC).isoformat(),
            context_admission=context,
            evidence=tuple(chunk.model_dump(mode="json") for chunk in detail.evidence_chunks),
            approval_state=detail.approval_state,
            governance_details=detail.governance_details,
        )
        appended = _get_conversation_store(request).append_turn_expected(
            conversation.conversation_id, turn, expected_turn_count=len(conversation.turns)
        )
        if appended is None:
            raise HTTPException(status_code=409, detail="task_conversation_changed")
    return _projection(
        updated,
        final_output=result.final_output,
        outcome=detail.outcome.value,
        evidence=[chunk.model_dump(mode="json") for chunk in detail.evidence_chunks],
    )


@router.post("/tasks")
def create_task(
    body: TaskCreateBody,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
    idempotency_key: str = Header(min_length=1, max_length=128, alias="Idempotency-Key"),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    with _errors():
        agent = _agent(request, body.agent_id)
        owner = TaskOwner(
            actor_subject=identity.operator_id,
            agent_id=body.agent_id,
            agent_version=_version(agent),
        )
        task_id = str(
            uuid5(NAMESPACE_URL, f"proofagent-task:{identity.operator_id}:{idempotency_key}")
        )
        criteria = body.acceptance_criteria or (
            AcceptanceCriterion(
                criterion_id="requested-answer",
                description="Answer the requested question from accepted sources",
                verifier="source_support",
                query=body.objective,
            ),
        )
        goal = GoalContract(
            task_id=task_id,
            revision=1,
            objective=body.objective,
            source_input_ref=f"task-input:{task_id}",
            acceptance_criteria=criteria,
            constraints=body.constraints,
            required_context=body.required_context,
        )
        fingerprint = sha256(
            json.dumps(
                {**body.model_dump(mode="json"), "agent_version": owner.agent_version},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        conversation = _conversation(request, body.conversation_id, body.agent_id)
        service = _service(request)
        snapshot, created = service.create(
            goal=goal,
            owner=owner,
            request_sha256=fingerprint,
            published_agent=agent,
            now=datetime.now(UTC),
            admission=_admission(identity),
            conversation_id=body.conversation_id,
            conversation_turn_count=None if conversation is None else len(conversation.turns),
            allow_untrusted_web_supplement=body.allow_untrusted_web_supplement,
        )
        if service.queue is None and created:
            return {**_execute_local(request, snapshot, agent, identity), "created": True}
        return _projection(snapshot, created=created)


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str,
    agent_id: str,
    agent_version: str,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_VIEW)
    with _errors():
        owner = TaskOwner(
            actor_subject=identity.operator_id, agent_id=agent_id, agent_version=agent_version
        )
        service = WorkflowTaskService(_service(request).repository)
        snapshot = service.get(task_id, owner=owner)
        if any(
            item.status == "pending" and item.request.expires_at <= datetime.now(UTC)
            for item in snapshot.questions
        ):
            snapshot = service.expire_questions(
                task_id, owner=owner, expected_version=snapshot.version, now=datetime.now(UTC)
            )
        return _projection(snapshot, **_local_result(request, snapshot))


def _resume(
    request: Request,
    task_id: str,
    owner: TaskOwner,
    identity: OperatorIdentityContext,
    *,
    allow_continue: bool = False,
) -> dict[str, Any]:
    service = _service(request)
    guard = request.app.state.workflow_task_local_lock if service.queue is None else nullcontext()
    with guard:
        return _resume_locked(request, task_id, owner, identity, allow_continue=allow_continue)


def _resume_locked(
    request: Request,
    task_id: str,
    owner: TaskOwner,
    identity: OperatorIdentityContext,
    *,
    allow_continue: bool,
) -> dict[str, Any]:
    service = _service(request)
    agent = _agent(request, owner.agent_id, owner.agent_version)
    snapshot = WorkflowTaskService(service.repository).get(task_id, owner=owner)
    if allow_continue and snapshot.phase in {"paused", "waiting_for_input"} and any(
        item.status in {"pending", "expired"} and item.request.goal_revision == snapshot.goal.revision
        and item.request.expires_at <= datetime.now(UTC) for item in snapshot.questions
    ):
        renewed = WorkflowTaskService(service.repository).renew_expired_questions(task_id, owner=owner,
            expected_version=snapshot.version, now=datetime.now(UTC))
        return _projection(renewed, **_local_result(request, renewed))
    pending = [
        intent
        for intent in service.repository.list_pending_resumes(owner=owner)
        if intent.task_id == task_id and intent.goal_revision == snapshot.goal.revision
    ]
    if not pending and allow_continue and snapshot.phase in {"active", "paused"}:
        if (service.queue is None and snapshot.phase == "active" and snapshot.latest_run_id is not None
                and snapshot.latest_run_goal_revision == snapshot.goal.revision
                and not _local_result(request, snapshot)):
            paused = WorkflowTaskService(service.repository).record_failed_run(task_id,
                snapshot.latest_run_id, owner=owner, now=datetime.now(UTC))
            return _projection(paused)
        blockers = any(
            q.request.blocking
            and q.status in {"pending", "expired"}
            and q.request.goal_revision == snapshot.goal.revision
            for q in snapshot.questions
        )
        if blockers:
            if snapshot.phase == "paused":
                snapshot = WorkflowTaskService(service.repository).transition(
                    task_id,
                    "waiting_for_input",
                    owner=owner,
                    expected_version=snapshot.version,
                    now=datetime.now(UTC),
                )
            return _projection(snapshot)
        if service.queue is not None and snapshot.latest_run_id is not None:
            previous_run = service.queue.get(snapshot.latest_run_id)
            if previous_run is not None and not previous_run.state.is_terminal:
                return _projection(snapshot)
        pending = [
            WorkflowTaskService(service.repository).request_resume(
                task_id, owner=owner, expected_version=snapshot.version, now=datetime.now(UTC)
            )
        ]
    for intent in pending:
        if intent.goal_revision != snapshot.goal.revision:
            continue
        conversation = _conversation(request, snapshot.conversation_id, owner.agent_id)
        already_bound = snapshot.latest_run_id == str(uuid5(NAMESPACE_URL, intent.intent_id))
        if service.queue is None and already_bound and snapshot.phase == "active":
            paused = WorkflowTaskService(service.repository).record_failed_run(task_id,
                snapshot.latest_run_id or "", owner=owner, now=datetime.now(UTC))
            return _projection(paused)
        snapshot = service.dispatch(
            intent,
            owner=owner,
            published_agent=agent,
            now=datetime.now(UTC),
            admission=_admission(identity),
            conversation_turn_count=None if conversation is None else len(conversation.turns),
        )
        if service.queue is None:
            if snapshot.phase != "active":
                service.repository.mark_resume_dispatched(
                    intent.intent_id, owner=owner, run_id=snapshot.latest_run_id or ""
                )
                continue
            result = _execute_local(request, snapshot, agent, identity)
            service.repository.mark_resume_dispatched(
                intent.intent_id, owner=owner, run_id=snapshot.latest_run_id or ""
            )
            return result
    return _projection(snapshot, **_local_result(request, snapshot))


@router.post("/tasks/{task_id}/answers")
def answer_task(
    task_id: str,
    body: TaskAnswerBody,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    with _errors():
        owner = _owner(identity, body)
        _agent(request, owner.agent_id, owner.agent_version)
        submission = WorkflowTaskService(_service(request).repository).answer(
            task_id, body.answer, owner=owner, now=datetime.now(UTC)
        )
        return {**_resume(request, task_id, owner, identity), "replayed": submission.replayed}


@router.post("/tasks/{task_id}/resume")
def resume_task(
    task_id: str,
    body: TaskIdentityBody,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    with _errors():
        return _resume(request, task_id, _owner(identity, body), identity, allow_continue=True)


@router.patch("/tasks/{task_id}/goal")
def revise_task_goal(
    task_id: str,
    body: TaskGoalBody,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    with _errors():
        execution = _service(request)
        current = WorkflowTaskService(execution.repository).get(
            task_id, owner=_owner(identity, body)
        )
        if (execution.queue is None and current.phase == 'active' and current.latest_run_id
                and current.latest_run_goal_revision == current.goal.revision):
            raise HTTPException(status_code=409, detail='task_run_must_stop_before_goal_revision')
        if execution.queue is not None and current.latest_run_id is not None:
            run = execution.queue.get(current.latest_run_id)
            if run is not None and not run.state.is_terminal:
                raise HTTPException(
                    status_code=409, detail="task_run_must_stop_before_goal_revision"
                )
        updated = WorkflowTaskService(execution.repository).revise_goal(
            task_id,
            body.goal,
            owner=_owner(identity, body),
            expected_version=body.expected_version,
            now=datetime.now(UTC),
        )
        return _projection(updated)


@router.patch("/tasks/{task_id}/phase")
def change_task_phase(
    task_id: str,
    body: TaskPhaseBody,
    request: Request,
    identity: OperatorIdentityContext = Depends(get_operator_identity),
) -> dict[str, Any]:
    require_operator_permission(identity, OperatorPermission.RUN_SUBMIT)
    with _errors():
        execution = _service(request)
        owner = _owner(identity, body)
        service = WorkflowTaskService(execution.repository)
        current = service.get(task_id, owner=owner)
        if current.version != body.expected_version:
            raise PersistenceConflictError(
                resource_type="workflow_task",
                resource_id=task_id,
                expected_revision=body.expected_version,
                actual_revision=current.version,
            )
        active_run = (
            None
            if execution.queue is None or current.latest_run_id is None
            else execution.queue.get(current.latest_run_id)
        )
        local_inflight = (execution.queue is None and current.phase == 'active'
                          and current.latest_run_id is not None
                          and current.latest_run_goal_revision == current.goal.revision)
        if body.phase == "paused" and (local_inflight or (active_run is not None and not active_run.state.is_terminal)):
            updated = service.record_failed_run(
                task_id, current.latest_run_id or "", owner=owner, now=datetime.now(UTC)
            )
        else:
            updated = service.transition(
                task_id,
                body.phase,
                owner=owner,
                expected_version=body.expected_version,
                now=datetime.now(UTC),
            )
        if (
            body.phase in {"paused", "cancelled"}
            and active_run is not None
            and not active_run.state.is_terminal
        ):
            assert execution.queue is not None
            execution.queue.request_cancel(
                run_id=active_run.request.run_id,
                operator_subject=identity.operator_id,
                now=datetime.now(UTC),
            )
        return _projection(updated)
