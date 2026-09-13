from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from proof_agent.contracts.published_agent import PublishedAgent
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.contracts.workflow_task import CriterionAssessment, QuestionField, TaskBudgetUsage
from proof_agent.contracts.workflow_task_update import TaskQuestionDraft, WorkflowTaskUpdate
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.dependencies import get_operator_identity
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
)


VERSION = "019ba001-1111-7000-8000-000000000001"


@pytest.fixture
def task_client(tmp_path, monkeypatch):
    app = create_app(
        history_dir=tmp_path / "history",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "configuration",
        published_agents={},
    )
    agent = PublishedAgent(
        agent_id="insurance",
        agent_version_id=VERSION,
        manifest_path=tmp_path / "agent.yaml",
        display_name="Insurance",
        purpose="Explain terms",
        customer_facing=False,
    )
    app.state.published_agents = SimpleNamespace(
        resolve=lambda agent_id: agent if agent_id == "insurance" else None
    )
    executions = []

    def execute(**kwargs):
        snapshot = kwargs["conversation_context"].workflow_task
        executions.append(snapshot)
        if not snapshot.questions:
            update = WorkflowTaskUpdate(
                task_id=snapshot.goal.task_id,
                expected_version=snapshot.version,
                goal_revision=snapshot.goal.revision,
                phase="waiting_for_input",
                question=TaskQuestionDraft(
                    stage="goal", fields=(QuestionField(name="product", label="Which product?"),)
                ),
                usage_delta=TaskBudgetUsage(model_calls=1, tokens=100, active_seconds=1.0),
            )
            outcome = ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
            output = "Which product?"
        else:
            update = WorkflowTaskUpdate(
                task_id=snapshot.goal.task_id,
                expected_version=snapshot.version,
                goal_revision=snapshot.goal.revision,
                phase="complete",
                assessments=(
                    CriterionAssessment(
                        criterion_id="requested-answer",
                        goal_revision=snapshot.goal.revision,
                        verifier="source_support",
                        status="satisfied",
                        proof_refs=("evidence-current-run",),
                    ),
                ),
                verified_proof_refs=("evidence-current-run",),
                usage_delta=TaskBudgetUsage(model_calls=1, tokens=200),
            )
            outcome = ReceiptOutcome.ANSWERED_WITH_CITATIONS
            output = "Verified waiting period."
        result = SimpleNamespace(
            workflow_template_execution_result=SimpleNamespace(workflow_task_update=update),
            final_output=output,
        )
        detail = SimpleNamespace(
            run_id=kwargs["run_id"],
            outcome=outcome,
            evidence_chunks=(),
            approval_state=None,
            governance_details=None,
        )
        return result, detail, None

    monkeypatch.setattr("proof_agent.delivery.api._execute_published_agent_run", execute)
    return TestClient(app), executions


def _create(client):
    return client.post(
        "/api/tasks",
        json={"agent_id": "insurance", "objective": "Explain waiting periods"},
        headers={"Idempotency-Key": "create-1"},
    )


def test_task_api_auto_run_waits_then_typed_answer_resumes_once_with_accumulated_budget(
    task_client,
):
    client, executions = task_client
    created = _create(client)
    assert created.status_code == 200, created.text
    snapshot = created.json()["task"]
    assert snapshot["phase"] == "waiting_for_input"
    task_id = snapshot["goal"]["task_id"]
    question = snapshot["questions"][0]["request"]
    payload = {
        "agent_id": "insurance",
        "agent_version": VERSION,
        "answer": {
            "question_id": question["question_id"],
            "expected_goal_revision": 1,
            "values": {"product": "Product A"},
            "idempotency_key": "answer-1",
        },
    }
    answered = client.post(f"/api/tasks/{task_id}/answers", json=payload)
    assert answered.status_code == 200, answered.text
    final = answered.json()["task"]
    assert final["phase"] == "complete"
    assert final["budget_usage"]["model_calls"] == 2
    assert final["budget_usage"]["tokens"] == 300
    assert final["latest_run_id"] != snapshot["latest_run_id"]
    assert executions[1].questions[0].answer.values["product"] == "Product A"
    duplicate = client.post(f"/api/tasks/{task_id}/answers", json=payload)
    assert duplicate.status_code == 200 and duplicate.json()["replayed"] is True
    assert len(executions) == 2


def test_task_creation_idempotency_survives_execution_and_rejects_changed_goal(task_client):
    client, executions = task_client
    first = _create(client)
    duplicate = _create(client)
    assert duplicate.status_code == 200 and duplicate.json()["created"] is False
    assert first.json()["task"]["goal"]["task_id"] == duplicate.json()["task"]["goal"]["task_id"]
    assert len(executions) == 1
    changed = client.post(
        "/api/tasks",
        json={"agent_id": "insurance", "objective": "Something else"},
        headers={"Idempotency-Key": "create-1"},
    )
    assert changed.status_code == 409


def test_task_api_cannot_complete_by_user_assertion_or_read_other_owners(task_client):
    client, _ = task_client
    created = _create(client).json()["task"]
    task_id = created["goal"]["task_id"]
    denied_complete = client.patch(
        f"/api/tasks/{task_id}/phase",
        json={
            "agent_id": "insurance",
            "agent_version": VERSION,
            "expected_version": created["version"],
            "phase": "complete",
        },
    )
    assert denied_complete.status_code == 422
    client.app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="other-operator",
        display_name="Other",
        permissions=frozenset(OperatorPermission),
    )
    denied_read = client.get(
        f"/api/tasks/{task_id}", params={"agent_id": "insurance", "agent_version": VERSION}
    )
    assert denied_read.status_code == 404


def test_task_api_submission_requires_current_run_permission(task_client):
    client, executions = task_client
    client.app.dependency_overrides[get_operator_identity] = lambda: OperatorIdentityContext(
        operator_id="viewer",
        display_name="Viewer",
        permissions=frozenset({OperatorPermission.RUN_VIEW}),
    )
    assert _create(client).status_code == 403
    assert executions == []


def test_paused_required_question_resumes_to_question_without_running_model(task_client):
    client, executions = task_client
    created = _create(client).json()["task"]
    task_id = created["goal"]["task_id"]
    owner = {"agent_id": "insurance", "agent_version": VERSION}
    paused = client.patch(
        f"/api/tasks/{task_id}/phase",
        json={**owner, "expected_version": created["version"], "phase": "paused"},
    )
    assert paused.status_code == 200
    resumed = client.post(f"/api/tasks/{task_id}/resume", json=owner)
    assert resumed.status_code == 200 and resumed.json()["task"]["phase"] == "waiting_for_input"
    assert len(executions) == 1


def test_local_execution_failure_persists_unknown_budget_and_pauses(task_client, monkeypatch):
    client, _ = task_client

    def fail(**kwargs):
        raise RuntimeError("model transport failed")

    monkeypatch.setattr("proof_agent.delivery.api._execute_published_agent_run", fail)
    failed = _create(client)
    assert failed.status_code == 500
    assert failed.json()["detail"] == "workflow_task_execution_failed"
    replay = _create(client)
    assert replay.status_code == 200
    task = replay.json()["task"]
    assert task["phase"] == "paused"
    assert task["budget_usage"]["tokens"] is None
    assert task["budget_usage"]["unknown_model_calls"] == 1


def test_expired_question_renews_without_execution_and_rejects_the_old_answer(task_client, monkeypatch):
    from datetime import UTC, datetime, timedelta
    client, executions = task_client
    created = _create(client).json()['task']
    task_id = created['goal']['task_id']
    owner = {'agent_id': 'insurance', 'agent_version': VERSION}
    old = created['questions'][0]['request']
    future = datetime.fromisoformat(old['expires_at'].replace('Z', '+00:00')) + timedelta(seconds=1)

    class FutureDateTime(datetime):
        @classmethod
        def now(cls, tz=UTC):
            return future.astimezone(tz)

    monkeypatch.setattr('proof_agent.delivery.workflow_task_api.datetime', FutureDateTime)
    expired = client.get(f'/api/tasks/{task_id}', params=owner)
    assert expired.json()['task']['questions'][0]['status'] == 'expired'
    renewed = client.post(f'/api/tasks/{task_id}/resume', json=owner)
    assert renewed.status_code == 200, renewed.text
    snapshot = renewed.json()['task']
    assert snapshot['phase'] == 'waiting_for_input'
    assert len(executions) == 1
    assert snapshot['budget_usage'] == created['budget_usage']
    pending = [item for item in snapshot['questions'] if item['status'] == 'pending']
    assert len(pending) == 1 and pending[0]['request']['question_id'] != old['question_id']
    rejected = client.post(f'/api/tasks/{task_id}/answers', json={**owner, 'answer': {
        'question_id': old['question_id'], 'expected_goal_revision': 1,
        'values': {'product': 'Product A'}, 'idempotency_key': 'expired-answer',
    }})
    assert rejected.status_code == 409
    assert len(executions) == 1


@pytest.mark.parametrize('operation', ['resume', 'pause'])
def test_interrupted_local_run_cannot_resume_or_pause_with_a_fresh_budget(task_client, operation):
    from proof_agent.contracts.workflow_task import WorkflowTaskSnapshot
    client, executions = task_client
    current = WorkflowTaskSnapshot.model_validate(_create(client).json()['task'])
    repository = client.app.state.workflow_task_repository
    interrupted = current.model_copy(update={'phase': 'active', 'version': current.version + 1, 'questions': ()})
    repository.compare_and_swap(interrupted, owner=current.owner, expected_version=current.version)
    task_id = current.goal.task_id
    owner = {'agent_id': 'insurance', 'agent_version': VERSION}
    if operation == 'resume':
        result = client.post(f'/api/tasks/{task_id}/resume', json=owner)
    else:
        result = client.patch(f'/api/tasks/{task_id}/phase', json={**owner,
            'expected_version': interrupted.version, 'phase': 'paused'})
    assert result.status_code == 200, result.text
    snapshot = result.json()['task']
    assert snapshot['phase'] == 'paused'
    assert snapshot['budget_usage']['tokens'] is None
    assert snapshot['budget_usage']['unknown_model_calls'] == 1
    assert len(executions) == 1
