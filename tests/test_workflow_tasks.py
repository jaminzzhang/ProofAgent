from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from proof_agent.contracts.persistence import (
    PersistenceConflictError,
    PersistenceIdempotencyConflictError,
    PersistenceInvariantError,
    PersistenceNotFoundError,
)
from proof_agent.contracts.workflow_task import (
    AcceptanceCriterion,
    CriterionAssessment,
    GoalContract,
    QuestionField,
    QuestionRequest,
    TaskBudgetUsage,
    TaskOwner,
    TypedAnswer,
)
from proof_agent.control.workflow.task_service import WorkflowTaskService
from proof_agent.observability.storage.workflow_task_store import (
    FileWorkflowTaskRepository,
    InMemoryWorkflowTaskRepository,
)


NOW = datetime(2026, 9, 12, tzinfo=UTC)
OWNER = TaskOwner(actor_subject="operator-1", agent_id="insurance", agent_version="version-1")


def goal() -> GoalContract:
    return GoalContract(
        task_id="task-1",
        revision=1,
        objective="Explain waiting periods",
        source_input_ref="run-1",
        acceptance_criteria=(
            AcceptanceCriterion(
                criterion_id="terms",
                description="Cite applicable waiting-period terms",
                verifier="source_support",
                query="waiting periods",
            ),
        ),
    )


def question(**updates) -> QuestionRequest:
    return QuestionRequest.model_validate(
        {
            "question_id": "question-1",
            "task_id": "task-1",
            "goal_revision": 1,
            "stage": "goal",
            "fields": (QuestionField(name="product", label="Which product?"),),
            "expires_at": NOW + timedelta(hours=1),
            "dedupe_key": "product",
            "checkpoint_ref": "run-1",
            **updates,
        }
    )


def answer(**updates) -> TypedAnswer:
    return TypedAnswer.model_validate(
        {
            "question_id": "question-1",
            "expected_goal_revision": 1,
            "values": {"product": "Product A"},
            "idempotency_key": "answer-1",
            **updates,
        }
    )


@pytest.fixture
def service() -> WorkflowTaskService:
    result = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    result.create(goal(), owner=OWNER, now=NOW)
    return result


def test_task_creation_persists_goal_separately_from_execution_version() -> None:
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    result = service.create(goal(), owner=OWNER, now=NOW)
    assert result.goal == goal()
    assert result.version == 1
    assert result.phase == "active"
    assert service.repository.get("task-1", owner=OWNER) == result


def test_blocking_answer_and_resume_intent_commit_once_under_concurrent_duplicates(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda _: service.answer("task-1", answer(), owner=OWNER, now=NOW), range(8))
        )
    assert sum(not result.replayed for result in results) == 1
    assert service.get("task-1", owner=OWNER).phase == "active"
    assert service.get("task-1", owner=OWNER).version == 3
    assert len(service.repository.list_pending_resumes(owner=OWNER)) == 1


def test_answer_retries_same_content_with_new_key_without_a_second_resume(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    original = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    replay = service.answer("task-1", answer(idempotency_key="second-key"), owner=OWNER, now=NOW)
    assert replay.replayed and replay.snapshot == original.snapshot
    with pytest.raises(PersistenceIdempotencyConflictError):
        service.answer("task-1", answer(values={"product": "Changed"}), owner=OWNER, now=NOW)


@pytest.mark.parametrize(
    "owner",
    [
        OWNER.model_copy(update={"actor_subject": "operator-2"}),
        OWNER.model_copy(update={"agent_id": "different-agent"}),
        OWNER.model_copy(update={"agent_version": "version-2"}),
    ],
)
def test_owner_agent_and_version_are_required_for_reads_and_answers(service, owner) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    assert service.repository.get("task-1", owner=owner) is None
    with pytest.raises(PersistenceNotFoundError):
        service.answer("task-1", answer(), owner=owner, now=NOW)
    assert service.repository.list_pending_resumes(owner=owner) == ()


def test_expired_question_never_resumes_or_counts_as_user_consent(service) -> None:
    asked = service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    expired = service.expire_questions(
        "task-1", owner=OWNER, expected_version=asked.version, now=NOW + timedelta(hours=2)
    )
    assert expired.phase == "waiting_for_input"
    assert expired.questions[0].status == "expired"
    with pytest.raises(PersistenceInvariantError, match="expired"):
        service.answer("task-1", answer(), owner=OWNER, now=NOW + timedelta(hours=2))
    assert service.repository.list_pending_resumes(owner=OWNER) == ()


def test_multiple_blockers_resume_only_when_last_question_is_answered(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    service.ask(
        "task-1",
        question(
            question_id="question-2",
            dedupe_key="date",
            fields=(QuestionField(name="year", label="Which year?", value_type="integer"),),
        ),
        owner=OWNER,
        expected_version=2,
        now=NOW,
    )
    first = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    assert first.snapshot.phase == "waiting_for_input" and first.resume_intent is None
    last = service.answer(
        "task-1",
        answer(question_id="question-2", values={"year": 2026}, idempotency_key="year-answer"),
        owner=OWNER,
        now=NOW,
    )
    assert last.snapshot.phase == "active" and last.resume_intent is not None


def test_optional_question_leaves_independent_work_active_without_parallel_resume(service) -> None:
    asked = service.ask(
        "task-1", question(blocking=False), owner=OWNER, expected_version=1, now=NOW
    )
    assert asked.phase == "active"
    result = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    assert result.snapshot.phase == "active" and result.resume_intent is None


def test_duplicate_question_across_stages_reuses_history_and_detects_schema_conflict(
    service,
) -> None:
    first = service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    duplicate = service.ask(
        "task-1",
        question(question_id="question-2", stage="evidence"),
        owner=OWNER,
        expected_version=2,
        now=NOW,
    )
    assert duplicate == first and len(duplicate.questions) == 1
    with pytest.raises(PersistenceIdempotencyConflictError):
        service.ask(
            "task-1",
            question(question_id="question-3", fields=(QuestionField(name="age", label="Age?"),)),
            owner=OWNER,
            expected_version=2,
            now=NOW,
        )


def test_goal_revision_invalidates_questions_and_rejects_late_answers(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    updated = service.revise_goal(
        "task-1",
        goal().model_copy(update={"revision": 2, "objective": "Explain exclusions"}),
        owner=OWNER,
        expected_version=2,
        now=NOW,
    )
    assert updated.goal.revision == 2 and updated.version == 3
    assert updated.questions[0].status == "superseded"
    with pytest.raises(PersistenceConflictError):
        service.answer("task-1", answer(), owner=OWNER, now=NOW)
    assert service.repository.list_pending_resumes(owner=OWNER) == ()


def test_no_final_answer_or_human_reply_can_replace_required_criterion_proof(service) -> None:
    with pytest.raises(PersistenceInvariantError, match="verification"):
        service.transition("task-1", "complete", owner=OWNER, expected_version=1, now=NOW)
    assessment = CriterionAssessment(
        criterion_id="terms",
        goal_revision=1,
        verifier="source_support",
        status="satisfied",
        proof_refs=("evidence-1",),
    )
    with pytest.raises(PersistenceInvariantError, match="unverified"):
        service.assess(
            "task-1",
            (assessment,),
            owner=OWNER,
            expected_version=1,
            now=NOW,
            verified_proof_refs=(),
        )
    assessed = service.assess(
        "task-1",
        (assessment,),
        owner=OWNER,
        expected_version=1,
        now=NOW,
        verified_proof_refs=("evidence-1",),
    )
    complete = service.transition(
        "task-1", "complete", owner=OWNER, expected_version=assessed.version, now=NOW
    )
    assert complete.phase == "complete"


def test_unknown_business_semantics_remain_unassessed() -> None:
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    ambiguous = goal().model_copy(
        update={
            "acceptance_criteria": (
                AcceptanceCriterion(
                    criterion_id="terms",
                    description="A good enough answer",
                    verifier="source_support",
                ),
            )
        }
    )
    service.create(ambiguous, owner=OWNER, now=NOW)
    with pytest.raises(PersistenceInvariantError, match="unassessed"):
        service.assess(
            "task-1",
            (
                CriterionAssessment(
                    criterion_id="terms",
                    goal_revision=1,
                    verifier="source_support",
                    status="satisfied",
                    proof_refs=("evidence-1",),
                ),
            ),
            owner=OWNER,
            expected_version=1,
            now=NOW,
            verified_proof_refs=("evidence-1",),
        )


@pytest.mark.parametrize("values", [{"product": 1}, {"unknown": "yes"}, {"product": "A" * 2049}])
def test_typed_answers_enforce_schema(service, values) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    with pytest.raises(PersistenceInvariantError):
        service.answer("task-1", answer(values=values), owner=OWNER, now=NOW)


@pytest.mark.parametrize(
    "values", [{}, {"product": " "}, {"product": None}, {"product": {}}, {"value": float("nan")}]
)
def test_empty_or_unbounded_answer_values_are_rejected(values) -> None:
    with pytest.raises(ValidationError):
        answer(values=values)


def test_cas_conflict_does_not_overwrite_newer_task(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    with pytest.raises(PersistenceConflictError):
        service.transition("task-1", "paused", owner=OWNER, expected_version=1, now=NOW)
    assert service.get("task-1", owner=OWNER).phase == "waiting_for_input"


def test_answer_outbox_recovers_after_reopening_and_retention_deletes_both(tmp_path) -> None:
    path = tmp_path / "tasks.sqlite3"
    repository = FileWorkflowTaskRepository(path)
    service = WorkflowTaskService(repository)
    service.create(goal(), owner=OWNER, now=NOW)
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    result = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    repository.close()
    reopened = FileWorkflowTaskRepository(path)
    assert reopened.get("task-1", owner=OWNER) == result.snapshot
    assert reopened.list_pending_resumes(owner=OWNER) == (result.resume_intent,)
    assert reopened.purge_expired(now=NOW + timedelta(days=91)) == 1
    assert reopened.get("task-1", owner=OWNER) is None
    assert reopened.list_pending_resumes(owner=OWNER) == ()
    reopened.close()


def test_resume_dispatch_is_idempotent_and_bound_to_one_run(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    result = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    intent = result.resume_intent
    assert intent is not None
    service.repository.mark_resume_dispatched(intent.intent_id, owner=OWNER, run_id="resumed-run")
    service.repository.mark_resume_dispatched(intent.intent_id, owner=OWNER, run_id="resumed-run")
    assert service.repository.list_pending_resumes(owner=OWNER) == ()
    with pytest.raises(PersistenceInvariantError):
        service.repository.mark_resume_dispatched(intent.intent_id, owner=OWNER, run_id="other-run")


def test_budget_usage_survives_runs_and_unknown_tokens_never_become_zero(service) -> None:
    first = service.bind_run(
        "task-1",
        "run-2",
        owner=OWNER,
        expected_version=1,
        now=NOW,
        usage_delta=TaskBudgetUsage(model_calls=2, retrieval_calls=1, tokens=None),
    )
    last = service.bind_run(
        "task-1",
        "run-3",
        owner=OWNER,
        expected_version=first.version,
        now=NOW,
        usage_delta=TaskBudgetUsage(model_calls=1, tool_calls=1, tokens=100),
    )
    assert last.budget_usage == TaskBudgetUsage(
        model_calls=3, retrieval_calls=1, tool_calls=1, tokens=None
    )
    assert last.latest_run_goal_revision == last.goal.revision == 1


def test_snapshot_nested_answer_is_immutable(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    result = service.answer("task-1", answer(), owner=OWNER, now=NOW)
    with pytest.raises(TypeError):
        result.snapshot.questions[0].answer.values["product"] = "Changed"


def test_required_context_cannot_be_made_nonblocking() -> None:
    service = WorkflowTaskService(InMemoryWorkflowTaskRepository())
    service.create(
        goal().model_copy(update={"required_context": ("product",)}), owner=OWNER, now=NOW
    )
    with pytest.raises(PersistenceInvariantError, match="required context"):
        service.ask("task-1", question(blocking=False), owner=OWNER, expected_version=1, now=NOW)


def test_contract_rejects_model_confidence_as_verifier() -> None:
    with pytest.raises(ValidationError):
        AcceptanceCriterion(
            criterion_id="terms", description="Must be right", verifier="model_confidence"
        )


def test_pause_resume_cannot_bypass_pending_required_question(service) -> None:
    service.ask("task-1", question(), owner=OWNER, expected_version=1, now=NOW)
    paused = service.transition("task-1", "paused", owner=OWNER, expected_version=2, now=NOW)
    with pytest.raises(PersistenceInvariantError, match="unanswered"):
        service.transition(
            "task-1", "active", owner=OWNER, expected_version=paused.version, now=NOW
        )


def test_repository_rejects_forged_final_state_without_criterion_proofs(service) -> None:
    current = service.get("task-1", owner=OWNER)
    forged = current.model_copy(update={"version": 2, "phase": "complete"})
    with pytest.raises(PersistenceInvariantError, match="criteria"):
        service.repository.compare_and_swap(forged, owner=OWNER, expected_version=1)


def test_run_failure_does_not_leave_active_task_or_reset_unknown_usage(service) -> None:
    service.bind_run("task-1", "run-failed", owner=OWNER, expected_version=1, now=NOW)
    failed = service.record_failed_run("task-1", "run-failed", owner=OWNER, now=NOW)
    assert failed.phase == "paused"
    assert failed.budget_usage.tokens is None
    assert failed.budget_usage.unknown_model_calls == 1


def test_explicit_continuation_is_durable_and_cannot_bypass_required_answer(service) -> None:
    paused = service.transition("task-1", "paused", owner=OWNER, expected_version=1, now=NOW)
    intent = service.request_resume("task-1", owner=OWNER, expected_version=paused.version, now=NOW)
    assert intent.kind == "continue" and intent.question_id is None
    assert service.get("task-1", owner=OWNER).phase == "active"
    assert service.repository.list_pending_resumes(owner=OWNER) == (intent,)
