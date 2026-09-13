"""Real PostgreSQL tests: each fixture creates and removes its own schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.workflow_task_repository import (
    PostgresWorkflowTaskRepository,
)
from proof_agent.contracts.persistence import PersistenceConflictError, PersistenceInvariantError
from proof_agent.contracts.workflow_task import (
    AcceptanceCriterion,
    GoalContract,
    QuestionField,
    QuestionRequest,
    TaskOwner,
    TypedAnswer,
)
from proof_agent.control.workflow.task_service import WorkflowTaskService


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)
NOW = datetime(2026, 9, 12, tzinfo=UTC)
OWNER = TaskOwner(actor_subject="operator-1", agent_id="insurance", agent_version="version-1")


def _seed(repository: PostgresWorkflowTaskRepository) -> WorkflowTaskService:
    service = WorkflowTaskService(repository)
    service.create(
        GoalContract(
            task_id="task-1",
            revision=1,
            objective="Explain waiting periods",
            source_input_ref="run-1",
            acceptance_criteria=(
                AcceptanceCriterion(
                    criterion_id="terms",
                    description="Cite applicable waiting periods",
                    verifier="source_support",
                    query="waiting periods",
                ),
            ),
        ),
        owner=OWNER,
        now=NOW,
    )
    service.ask(
        "task-1",
        QuestionRequest(
            question_id="question-1",
            task_id="task-1",
            goal_revision=1,
            stage="goal",
            fields=(QuestionField(name="product", label="Which product?"),),
            expires_at=NOW + timedelta(hours=1),
            dedupe_key="product",
            checkpoint_ref="run-1",
        ),
        owner=OWNER,
        expected_version=1,
        now=NOW,
    )
    return service


def _answer() -> TypedAnswer:
    return TypedAnswer(
        question_id="question-1",
        expected_goal_revision=1,
        values={"product": "Product A"},
        idempotency_key="answer-1",
    )


def test_postgres_tasks_cas_reopen_and_owner_isolation(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    service = _seed(repository)
    result = service.answer("task-1", _answer(), owner=OWNER, now=NOW)
    restarted = PostgresWorkflowTaskRepository(postgres_engine)
    assert restarted.get("task-1", owner=OWNER) == result.snapshot
    assert restarted.list_pending_resumes(owner=OWNER) == (result.resume_intent,)
    assert (
        restarted.get("task-1", owner=OWNER.model_copy(update={"actor_subject": "other"})) is None
    )
    assert (
        restarted.get("task-1", owner=OWNER.model_copy(update={"agent_version": "other"})) is None
    )
    with pytest.raises(PersistenceConflictError):
        service.transition("task-1", "paused", owner=OWNER, expected_version=1, now=NOW)


def test_postgres_concurrent_answers_create_one_resume_intent(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    service = _seed(repository)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda _: service.answer("task-1", _answer(), owner=OWNER, now=NOW), range(16))
        )
    assert sum(not result.replayed for result in results) == 1
    assert service.get("task-1", owner=OWNER).version == 3
    assert len(repository.list_pending_resumes(owner=OWNER)) == 1


def test_postgres_snapshot_and_outbox_rollback_together(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    service = _seed(repository)
    before = service.get("task-1", owner=OWNER)

    def break_outbox(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO workflow_task_resumes"):
            raise RuntimeError("isolated outbox failure")

    sa.event.listen(postgres_engine, "before_cursor_execute", break_outbox)
    try:
        with pytest.raises(RuntimeError, match="isolated outbox failure"):
            service.answer("task-1", _answer(), owner=OWNER, now=NOW)
    finally:
        sa.event.remove(postgres_engine, "before_cursor_execute", break_outbox)
    assert repository.get("task-1", owner=OWNER) == before
    assert repository.list_pending_resumes(owner=OWNER) == ()
    assert not service.answer("task-1", _answer(), owner=OWNER, now=NOW).replayed


def test_postgres_outbox_dispatch_joins_caller_transaction(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    service = _seed(repository)
    result = service.answer("task-1", _answer(), owner=OWNER, now=NOW)
    assert result.resume_intent is not None
    with pytest.raises(RuntimeError, match="queue unavailable"):
        with postgres_engine.begin() as connection:
            joined = PostgresWorkflowTaskRepository(connection)
            joined.mark_resume_dispatched(
                result.resume_intent.intent_id, owner=OWNER, run_id="resumed-run"
            )
            raise RuntimeError("queue unavailable")
    assert repository.list_pending_resumes(owner=OWNER) == (result.resume_intent,)
    with postgres_engine.begin() as connection:
        joined = PostgresWorkflowTaskRepository(connection)
        joined.mark_resume_dispatched(
            result.resume_intent.intent_id, owner=OWNER, run_id="resumed-run"
        )
    assert repository.list_pending_resumes(owner=OWNER) == ()
    with pytest.raises(PersistenceInvariantError):
        repository.mark_resume_dispatched(
            result.resume_intent.intent_id, owner=OWNER, run_id="other-run"
        )


def test_postgres_retention_removes_raw_snapshots_and_outbox(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    service = _seed(repository)
    service.answer("task-1", _answer(), owner=OWNER, now=NOW)
    assert repository.purge_expired(now=NOW + timedelta(days=89)) == 0
    assert repository.purge_expired(now=NOW + timedelta(days=90)) == 1
    assert repository.get("task-1", owner=OWNER) is None
    assert repository.list_pending_resumes(owner=OWNER) == ()


def test_postgres_corrupt_snapshot_digest_fails_closed(postgres_engine: Engine) -> None:
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    _seed(repository)
    # Fault injection only in the isolated test schema, never a business-state fixture.
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE workflow_tasks SET snapshot_sha256 = :digest WHERE task_id = :task"),
            {"digest": "0" * 64, "task": "task-1"},
        )
    with pytest.raises(PersistenceInvariantError, match="integrity"):
        repository.get("task-1", owner=OWNER)


def test_postgres_task_run_wait_commit_and_answer_dispatch_use_one_authority(
    postgres_engine, tmp_path
):
    from uuid import uuid4
    from postgres_fixtures import TEST_AGENT_ID, TEST_AGENT_VERSION_ID, seed_agent_version
    from test_postgres_run_queue import _activate, _snapshot
    from test_run_executor import _finalizer, _member
    from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
        PostgresRunQueueRepository,
    )
    from proof_agent.contracts.artifacts import ArtifactOwner
    from proof_agent.contracts.ports.run_queue import RunClaimRejectedError
    from proof_agent.contracts.published_agent import PublishedAgent
    from proof_agent.contracts.run_execution import RunLifecycleState
    from proof_agent.contracts.workflow_task_update import TaskQuestionDraft, WorkflowTaskUpdate
    from proof_agent.delivery.task_execution_service import TaskExecutionService

    seed_agent_version(postgres_engine)
    owner = TaskOwner(
        actor_subject="operator-1", agent_id=TEST_AGENT_ID, agent_version=TEST_AGENT_VERSION_ID
    )
    agent = PublishedAgent(
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        manifest_path=tmp_path / "agent.yaml",
        display_name="Test",
        purpose="Test",
        customer_facing=False,
    )
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    queue = PostgresRunQueueRepository(postgres_engine)
    execution = TaskExecutionService(repository, engine=postgres_engine, queue=queue)
    admission = {
        "permission_mapping_version_id": "019ba001-1111-7000-8000-000000000099",
        "permission_epoch": 1,
    }
    goal = GoalContract(
        task_id="task-1",
        revision=1,
        objective="Explain waiting periods",
        source_input_ref="request-1",
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="terms",
                description="Cite waiting periods",
                verifier="source_support",
                query="waiting periods",
            ),
        ),
    )
    snapshot, created = execution.create(
        goal=goal,
        owner=owner,
        request_sha256="a" * 64,
        published_agent=agent,
        now=NOW,
        admission=admission,
    )
    assert created
    queued = queue.get(snapshot.latest_run_id)
    assert queued.request.task_snapshot_sha256 == snapshot.digest()
    activation = _activate(queue, postgres_engine, slot=1, executor_id="task-worker", now=NOW)
    claim = queue.claim_next(
        slot=1,
        executor_id="task-worker",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    finalized = queue.mark_finalizing(claim, now=NOW + timedelta(seconds=2))
    prepared = _finalizer(postgres_engine, tmp_path).prepare(
        owner=ArtifactOwner(owner_type="run_attempt", owner_id=claim.attempt.attempt_id),
        manifest_id=str(uuid4()),
        members=_member(claim.attempt.attempt_id),
    )
    update = WorkflowTaskUpdate(
        task_id="task-1",
        expected_version=snapshot.version,
        goal_revision=1,
        phase="waiting_for_input",
        question=TaskQuestionDraft(
            stage="goal", fields=(QuestionField(name="product", label="Which product?"),)
        ),
    )
    with pytest.raises(RunClaimRejectedError):
        queue.commit_success(
            finalized,
            manifest=prepared.manifest,
            manifest_ref=prepared.manifest_ref,
            now=NOW + timedelta(seconds=3),
            workflow_task_update=update.model_copy(update={"expected_version": 99}),
        )
    assert queue.get(snapshot.latest_run_id).state == RunLifecycleState.FINALIZING
    assert repository.get("task-1", owner=owner) == snapshot
    queue.commit_success(
        finalized,
        manifest=prepared.manifest,
        manifest_ref=prepared.manifest_ref,
        now=NOW + timedelta(seconds=3),
        workflow_task_update=update,
    )
    waiting = repository.get("task-1", owner=owner)
    assert waiting.phase == "waiting_for_input"
    assert queue.get(snapshot.latest_run_id).state == RunLifecycleState.SUCCEEDED
    answer = TypedAnswer(
        question_id=waiting.questions[0].request.question_id,
        expected_goal_revision=1,
        values={"product": "Product A"},
        idempotency_key="typed-answer",
    )
    submission = WorkflowTaskService(repository).answer(
        "task-1", answer, owner=owner, now=NOW + timedelta(seconds=4)
    )
    continued = execution.dispatch(
        submission.resume_intent,
        owner=owner,
        published_agent=agent,
        now=NOW + timedelta(seconds=5),
        admission=admission,
    )
    assert continued.latest_run_id != snapshot.latest_run_id
    new_run = queue.get(continued.latest_run_id)
    assert new_run.state == RunLifecycleState.QUEUED
    assert new_run.request.task_snapshot_sha256 == continued.digest()
    assert new_run.request.question == goal.objective
    assert repository.list_pending_resumes(owner=owner) == ()
    assert (
        execution.dispatch(
            submission.resume_intent,
            owner=owner,
            published_agent=agent,
            now=NOW + timedelta(seconds=6),
            admission=admission,
        )
        == continued
    )


def test_postgres_concurrent_task_creation_admits_only_one_run(postgres_engine, tmp_path):
    from postgres_fixtures import TEST_AGENT_ID, TEST_AGENT_VERSION_ID, seed_agent_version
    from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
        PostgresRunQueueRepository,
    )
    from proof_agent.contracts.published_agent import PublishedAgent
    from proof_agent.delivery.task_execution_service import TaskExecutionService

    seed_agent_version(postgres_engine)
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    queue = PostgresRunQueueRepository(postgres_engine)
    owner = TaskOwner(
        actor_subject="operator-1", agent_id=TEST_AGENT_ID, agent_version=TEST_AGENT_VERSION_ID
    )
    agent = PublishedAgent(
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        manifest_path=tmp_path / "agent.yaml",
        display_name="Test",
        purpose="Test",
        customer_facing=False,
    )
    goal = GoalContract(
        task_id="task-1",
        revision=1,
        objective="Explain waiting periods",
        source_input_ref="request-1",
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="terms",
                description="Cite waiting periods",
                verifier="source_support",
                query="waiting periods",
            ),
        ),
    )
    execution = TaskExecutionService(repository, engine=postgres_engine, queue=queue)

    def create(_):
        return execution.create(
            goal=goal,
            owner=owner,
            request_sha256="a" * 64,
            published_agent=agent,
            now=NOW,
            admission={
                "permission_mapping_version_id": "019ba001-1111-7000-8000-000000000099",
                "permission_epoch": 1,
            },
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(create, range(16)))
    assert sum(created for _, created in outcomes) == 1
    assert len(queue.list()) == 1


@pytest.mark.parametrize("lost_worker", [False, True])
def test_postgres_failed_task_attempt_persists_unknown_budget_debt_after_restart(
    postgres_engine, tmp_path, lost_worker
):
    from postgres_fixtures import TEST_AGENT_ID, TEST_AGENT_VERSION_ID, seed_agent_version
    from test_postgres_run_queue import _activate, _snapshot
    from proof_agent.capabilities.persistence.postgres.run_queue_repository import (
        PostgresRunQueueRepository,
    )
    from proof_agent.contracts.published_agent import PublishedAgent
    from proof_agent.contracts.run_execution import RunFailure, RunFailureCode, RunLifecycleState
    from proof_agent.delivery.task_execution_service import TaskExecutionService

    seed_agent_version(postgres_engine)
    repository = PostgresWorkflowTaskRepository(postgres_engine)
    queue = PostgresRunQueueRepository(postgres_engine)
    owner = TaskOwner(
        actor_subject="operator-1", agent_id=TEST_AGENT_ID, agent_version=TEST_AGENT_VERSION_ID
    )
    agent = PublishedAgent(
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        manifest_path=tmp_path / "agent.yaml",
        display_name="Test",
        purpose="Test",
        customer_facing=False,
    )
    goal = GoalContract(
        task_id="task-1",
        revision=1,
        objective="Explain waiting periods",
        source_input_ref="request-1",
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="terms",
                description="Cite waiting periods",
                verifier="source_support",
                query="waiting periods",
            ),
        ),
    )
    execution = TaskExecutionService(repository, engine=postgres_engine, queue=queue)
    snapshot, _ = execution.create(
        goal=goal,
        owner=owner,
        request_sha256="a" * 64,
        published_agent=agent,
        now=NOW,
        admission={
            "permission_mapping_version_id": "019ba001-1111-7000-8000-000000000099",
            "permission_epoch": 1,
        },
    )
    activation = _activate(queue, postgres_engine, slot=1, executor_id="task-worker", now=NOW)
    claim = queue.claim_next(
        slot=1,
        executor_id="task-worker",
        activation_epoch=activation.activation_epoch,
        now=NOW + timedelta(seconds=1),
        lease_seconds=15,
        deadline_seconds=120,
        snapshot_factory=_snapshot,
    )
    assert claim is not None
    if lost_worker:
        assert queue.reap_expired_leases(now=NOW + timedelta(seconds=20)) == 1
    else:
        queue.commit_terminal_failure(
            claim,
            target=RunLifecycleState.FAILED,
            failure=RunFailure(code=RunFailureCode.EXECUTION_FAILED),
            now=NOW + timedelta(seconds=2),
        )
    reloaded = PostgresWorkflowTaskRepository(postgres_engine).get("task-1", owner=owner)
    assert reloaded.phase == "paused"
    assert reloaded.budget_usage.tokens is None
    assert reloaded.budget_usage.unknown_model_calls == 1
    assert queue.get(snapshot.latest_run_id).state == RunLifecycleState.FAILED
