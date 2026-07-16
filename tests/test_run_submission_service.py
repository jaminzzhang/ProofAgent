from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.contracts.run_execution import (
    RunLifecycleState,
    RunQueueRecord,
    RunRequest,
)
from proof_agent.contracts import InstitutionAuthorizationContext
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_submission_service import RunSubmissionService
from proof_agent.observability.api.app import create_app


NOW = datetime(2026, 7, 15, tzinfo=UTC)
RUN_ID = "019ba001-1111-7000-8000-000000000010"
VERSION_ID = "019ba001-1111-7000-8000-000000000001"
PERMISSION_VERSION = "019ba001-1111-7000-8000-000000000099"


class Queue:
    def __init__(self) -> None:
        self.records: dict[str, RunQueueRecord] = {}
        self.admissions = 0

    def admit(self, request: RunRequest):
        self.admissions += 1
        existing = next(
            (
                record
                for record in self.records.values()
                if record.request.operator_subject == request.operator_subject
                and record.request.idempotency_key == request.idempotency_key
            ),
            None,
        )
        if existing is not None:
            return existing, False
        record = RunQueueRecord(
            request=request,
            request_sha256=request.canonical_sha256(),
            state=RunLifecycleState.QUEUED,
            state_version=1,
            enqueued_at=request.submitted_at,
            updated_at=request.submitted_at,
        )
        self.records[request.run_id] = record
        return record, True

    def get(self, run_id: str):
        return self.records.get(run_id)

    def list_page(
        self,
        *,
        limit,
        offset,
        run_purpose=None,
        search=None,
        states=(),
        receipt_outcome=None,
    ):
        records = list(reversed(self.records.values()))
        if run_purpose is not None:
            records = [record for record in records if record.request.run_purpose == run_purpose]
        if search is not None:
            records = [
                record
                for record in records
                if search.lower() in record.request.question.lower()
                or search.lower() in record.request.run_id.lower()
            ]
        if states:
            records = [record for record in records if record.state in states]
        if receipt_outcome is not None:
            records = [
                record
                for record in records
                if record.result.receipt_outcome == receipt_outcome
            ]
        return records[offset : offset + limit], len(records)

    def request_cancel(self, *, run_id: str, operator_subject: str, now: datetime):
        current = self.records[run_id]
        assert current.request.operator_subject == operator_subject
        cancelled = current.model_copy(
            update={
                "state": RunLifecycleState.CANCELLED,
                "state_version": current.state_version + 1,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self.records[run_id] = cancelled
        return cancelled


def _agent() -> PublishedAgent:
    return PublishedAgent(
        agent_id="agent_management_insurance_specialist",
        manifest_path=Path("unused.yaml"),
        display_name="Insurance Specialist",
        purpose="answer governed insurance questions",
        customer_facing=False,
        agent_version_id=VERSION_ID,
    )


def test_submission_only_admits_a_frozen_request_without_executing_dependencies() -> None:
    queue = Queue()
    service = RunSubmissionService(
        queue,  # type: ignore[arg-type]
        clock=lambda: NOW,
        run_id_factory=lambda: RUN_ID,
    )

    authorization = InstitutionAuthorizationContext(
        institutions=("branch-shanghai",),
        roles=("institution-specialist",),
    )
    record, created = service.submit(
        published_agent=_agent(),
        question="本产品的等待期是多少？",
        operator_subject="operator-1",
        idempotency_key="submit-1",
        permission_mapping_version_id=PERMISSION_VERSION,
        permission_epoch=7,
        institution_authorization=authorization,
    )

    assert created is True
    assert record.state is RunLifecycleState.QUEUED
    assert record.request.agent_version_id == VERSION_ID
    assert record.request.permission_epoch == 7
    assert record.request.institution_authorization == authorization
    assert queue.admissions == 1


class Registry:
    def resolve(self, agent_id: str):
        return _agent() if agent_id == _agent().agent_id else None


def test_async_run_api_returns_202_projection_and_supports_cancel(tmp_path: Path) -> None:
    queue = Queue()
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
        run_queue_repository=queue,  # type: ignore[arg-type]
    )
    app.state.published_agents = Registry()
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        headers={"Idempotency-Key": "submit-1"},
        json={
            "agent_id": _agent().agent_id,
            "question": "本产品的等待期是多少？",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "queued"
    assert body["result_available"] is False
    assert body["progress_url"].endswith("/progress")
    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    listing = client.get("/api/runs?state=queued&search=等待期")
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 1
    assert listing.json()["data"][0]["state"] == "queued"
    cancelled = client.post(f"/api/runs/{body['run_id']}/cancel")
    assert cancelled.status_code == 202
    assert cancelled.json()["state"] == "cancelled"
    stats = client.get("/api/stats")
    assert stats.status_code == 200
    assert stats.json() == {
        "total_runs": 1,
        "outcome_distribution": {},
        "pending_approvals": 0,
    }


def test_api_idempotent_repeat_returns_existing_run(tmp_path: Path) -> None:
    queue = Queue()
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        agent_configuration_dir=tmp_path / "config",
        run_queue_repository=queue,  # type: ignore[arg-type]
    )
    app.state.published_agents = Registry()
    client = TestClient(app)
    payload = {"agent_id": _agent().agent_id, "question": "question"}

    first = client.post(
        "/api/runs", headers={"Idempotency-Key": "same"}, json=payload
    )
    repeated = client.post(
        "/api/runs", headers={"Idempotency-Key": "same"}, json=payload
    )

    assert first.status_code == 202
    assert repeated.status_code == 202
    assert repeated.json()["run_id"] == first.json()["run_id"]
    assert repeated.json()["created"] is False
