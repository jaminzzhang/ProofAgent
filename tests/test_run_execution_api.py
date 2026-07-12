import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
import shutil

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts.dashboard import RunPurpose
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.errors import ProofAgentError
import proof_agent.delivery.run_execution_service as run_execution_service
from proof_agent.observability.api.app import create_app
from proof_agent.observability.api.operator_identity import (
    OperatorIdentityContext,
    OperatorPermission,
)
from proof_agent.observability.storage.run_store import RunStore


def _app_with_published_agent(tmp_path: Path, manifest_path: Path):
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    return create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )


class _StaticOperatorIdentityProvider:
    def __init__(self, permissions: set[OperatorPermission]) -> None:
        self._permissions = permissions

    def current_identity(self) -> OperatorIdentityContext:
        return OperatorIdentityContext(
            operator_id="test-operator",
            display_name="Test Operator",
            permissions=frozenset(self._permissions),
        )


def _write_artifacts(tmp_path: Path, run_id: str) -> tuple[Path, Path]:
    trace_src = tmp_path / f"{run_id}.jsonl"
    receipt_src = tmp_path / f"{run_id}.md"
    trace_src.write_text(
        json.dumps({"event_type": "run_started", "run_id": run_id}) + "\n",
        encoding="utf-8",
    )
    receipt_src.write_text("# Receipt", encoding="utf-8")
    return trace_src, receipt_src


def _app_with_validation_capture(
    tmp_path: Path,
    *,
    run_id: str = "run_validation",
    run_purpose: RunPurpose = RunPurpose.VALIDATION,
    expires_at: str | None = None,
):
    configuration_store = LocalAgentConfigurationStore(tmp_path / "config")
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=configuration_store,
    )
    run_store: RunStore = app.state.store
    trace_src, receipt_src = _write_artifacts(tmp_path, run_id)
    run_store.save_run_artifacts(
        run_id,
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Validate draft",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        run_purpose=run_purpose,
        agent_id="react_enterprise_qa_v3",
        draft_id="draft_001",
    )
    artifact = configuration_store.record_sensitive_validation_capture_artifact(
        run_id=run_id,
        draft_id="draft_001",
        payload={"result_summary": {"outcome": "ANSWERED_WITH_CITATIONS"}},
        actor="test-operator",
    )
    if expires_at is not None:
        capture_file = tmp_path / "config" / artifact.artifact_path
        stored = json.loads(capture_file.read_text(encoding="utf-8"))
        stored["metadata"]["expires_at"] = expires_at
        capture_file.write_text(json.dumps(stored), encoding="utf-8")
    assert run_store.attach_validation_capture(run_id, artifact.capture_id)
    return app, artifact


def _copy_react_agent_with_response_details(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "react_enterprise_qa_v3"
    shutil.copytree(Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            "  include_reasoning_summary: false\n  include_review_results: false",
            "  include_reasoning_summary: true\n  include_review_results: true",
        ),
        encoding="utf-8",
    )
    return manifest_path


def _copy_react_v3_agent_with_unique_knowledge(tmp_path: Path) -> Path:
    agent_dir = tmp_path / "react_enterprise_qa_v3_unique"
    shutil.copytree(
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3"),
        agent_dir,
    )
    knowledge_dir = agent_dir / "knowledge"
    for path in knowledge_dir.glob("*.md"):
        path.unlink()
    (knowledge_dir / "sapphire-meals.md").write_text(
        "# Sapphire Meal Policy\n\n"
        "## Reimbursement\n\n"
        "Sapphire meals are reimbursed up to 77 USD per day when the traveler "
        "keeps the sapphire meal receipt.\n",
        encoding="utf-8",
    )
    manifest_path = agent_dir / "agent.yaml"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            "name: react_enterprise_qa_v3", "name: react_enterprise_qa_v3_unique"
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_chat_run_execution_starts_published_agent_and_persists_run(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "react_enterprise_qa_v3"
    assert body["run_id"].startswith("run_")
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert "Travel meals are reimbursed" in body["final_output"]
    assert body["links"]["run_detail"] == f"/api/runs/{body['run_id']}"
    assert body["links"]["trace"] == f"/api/runs/{body['run_id']}/trace"
    assert body["links"]["receipt"] == f"/api/runs/{body['run_id']}/receipt"
    assert body["evidence"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["question"] == "What is the reimbursement rule for travel meals?"


def test_chat_run_maps_model_provider_error_to_upstream_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    def fake_execute_agent_package_run(request: object) -> object:
        _ = request
        raise ProofAgentError(
            "PA_MODEL_002",
            "model provider API error (upstream status 400).",
            (
                "Check the configured provider, model name, base_url, endpoint mode, "
                "and structured-output support before retrying."
            ),
        )

    monkeypatch.setattr(
        run_execution_service,
        "execute_agent_package_run",
        fake_execute_agent_package_run,
    )

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "PA_MODEL_002"


def test_chat_run_response_includes_citation_refs_when_available(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citation_refs"]
    assert body["citation_refs"][0]["citation"] == ("customer-support-policy.md#travel-meals:L3-L7")
    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["citation_refs"] == body["citation_refs"]


def test_chat_run_executes_v3_agent_through_controlled_react_orchestrator(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert body["final_output"]

    detail = client.get(f"/api/runs/{body['run_id']}")
    assert detail.status_code == 200
    detail_body = detail.json()
    trace = client.get(f"/api/runs/{body['run_id']}/trace").json()
    run_started = next(event for event in trace["events"] if event["event_type"] == "run_started")
    assert run_started["payload"]["runtime"] == "controlled_react_orchestrator"
    assert detail_body["workflow_projection"]["template_descriptor_version"] == (
        "react_enterprise_qa.v3"
    )


def test_chat_run_v3_uses_configured_knowledge_provider(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        _copy_react_v3_agent_with_unique_knowledge(tmp_path),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3_unique",
            "question": "What is the sapphire meal reimbursement rule?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"
    assert "77 USD" in body["final_output"]
    assert body["citation_refs"]
    assert body["citation_refs"][0]["citation"] == ("sapphire-meals.md#reimbursement:L3-L5")


def test_chat_run_v3_persists_observation_truth_for_resume(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    truth_dir = (
        tmp_path / "controlled_react" / body["run_id"] / "controlled_react" / "observation_truth"
    )

    assert list(truth_dir.glob("*.json"))


def test_chat_run_v3_response_evidence_uses_safe_projection(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["evidence"]
    assert "content" not in body["evidence"][0]


def test_chat_run_uses_published_stage_runtime_facts(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    trace = client.get(f"/api/runs/{body['run_id']}/trace").json()
    summary = next(
        event
        for event in trace["events"]
        if event["event_type"] == "workflow_stage_configuration_trace_summary"
    )
    assert summary["payload"]["source"] == {
        "source_type": "published_agent_version",
        "reference": f"published_version:{body['agent_version_id']}",
    }
    detail = client.get(f"/api/runs/{body['run_id']}").json()
    projection = detail["workflow_projection"]
    assert projection["template_name"] == "react_enterprise_qa_v3"
    assert projection["template_descriptor_version"] == "react_enterprise_qa.v3"
    assert projection["stage_configuration_source"] == summary["payload"]["source"]
    assert {stage["stage_id"] for stage in projection["stages"]} >= {
        "plan",
        "model_answer",
    }


def test_validation_capture_requires_agent_validate_permission(tmp_path: Path) -> None:
    app, _artifact = _app_with_validation_capture(tmp_path)
    app.state.operator_identity_provider = _StaticOperatorIdentityProvider(set())
    client = TestClient(app)

    response = client.get("/api/runs/run_validation/validation-capture")

    assert response.status_code == 403
    assert response.json()["detail"] == "Operator lacks required permission: agent.validate"


def test_production_run_never_exposes_validation_capture(tmp_path: Path) -> None:
    app, _artifact = _app_with_validation_capture(
        tmp_path,
        run_id="run_production",
        run_purpose=RunPurpose.PRODUCTION,
    )
    client = TestClient(app)

    response = client.get("/api/runs/run_production/validation-capture")

    assert response.status_code == 404
    assert response.json()["detail"] == "Validation capture not found: run_production"


def test_expired_validation_capture_returns_404(tmp_path: Path) -> None:
    expired_at = (
        (datetime.now(UTC) - timedelta(minutes=1))
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )
    app, _artifact = _app_with_validation_capture(tmp_path, expires_at=expired_at)
    client = TestClient(app)

    response = client.get("/api/runs/run_validation/validation-capture")

    assert response.status_code == 404
    assert response.json()["detail"] == "Validation capture not found: run_validation"


def test_chat_run_execution_rejects_unknown_agent_id(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "unknown",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["available_agent_ids"] == ["react_enterprise_qa_v3"]


def test_chat_run_execution_rejects_arbitrary_manifest_path(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "agent_yaml": "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 422


def test_chat_run_execution_rejects_inline_approval_resume_parameter(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "Look up customer policy status before answering.",
            "approved": True,
        },
    )

    assert response.status_code == 422


def test_chat_run_execution_registers_react_enterprise_qa(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_id"] == "react_enterprise_qa_v3"
    assert body["outcome"] == "ANSWERED_WITH_CITATIONS"


def test_chat_run_omits_governance_details_by_default(tmp_path: Path) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()


def test_chat_run_omits_governance_details_when_agent_policy_denies(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path, Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    assert "governance_details" not in response.json()


def test_chat_run_returns_governance_details_when_agent_policy_allows(
    tmp_path: Path,
) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    app = _app_with_published_agent(tmp_path, manifest_path)
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    details = response.json()["governance_details"]
    assert details["reasoning_summary"]
    assert details["review_results"]


def test_chat_run_returns_intent_resolution_when_v3_policy_allows(
    tmp_path: Path,
) -> None:
    manifest_path = _copy_react_agent_with_response_details(tmp_path)
    app = _app_with_published_agent(tmp_path, manifest_path)
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "react_enterprise_qa_v3",
            "question": "What is the reimbursement rule for travel meals?",
            "include_governance_details": True,
        },
    )

    assert response.status_code == 200
    details = response.json()["governance_details"]
    assert details["intent_resolution"]["domain_intent"] == "enterprise_policy_question"
    assert details["reasoning_summary"]
    assert details["review_results"]
