from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import RunPurpose
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.customer_run_samples import CustomerRunApiEvaluationSampleRunner
from proof_agent.observability.api.app import create_app


def test_campaign_uses_customer_run_api_adapter_for_evaluation_samples(
    tmp_path: Path,
) -> None:
    app = _app_with_customer_facing_published_agent(tmp_path)
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        run_store=app.state.store,
        sample_runner=CustomerRunApiEvaluationSampleRunner(app, customer_id="CUST-001"),
    )

    assert summary.readiness_status == "ready"
    subject_manifest_path = summary.artifact_dir / "subject_manifest.yaml"
    subject_manifest = yaml.safe_load(subject_manifest_path.read_text(encoding="utf-8"))
    subject = subject_manifest["subjects"][0]
    run_id = subject["run_ref"]["run_id"]
    detail = app.state.store.get_run_detail(run_id)
    conversation = _customer_conversation_for_run(app, run_id)

    assert detail.run_purpose == RunPurpose.EVALUATION_SAMPLE
    assert detail.agent_id == "insurance_customer_service"
    assert detail.question == "What documents are required for inpatient claim reimbursement?"
    assert conversation is not None
    assert conversation.customer_ref == "CUST-001"
    assert conversation.snapshots[-1].run_id == run_id
    assert subject["execution_surface"] == "customer_run_api"
    assert subject["projections"]["evaluated_response"]["audience"] == "customer"
    assert subject["projections"]["evaluated_response"]["ref"].endswith("customer_response.txt")
    response_text = (app.state.store.history_dir / run_id / "customer_response.txt").read_text(
        encoding="utf-8"
    )
    assert "governance_details" not in response_text
    assert "Trace" not in response_text
    assert response_text.strip()


def test_customer_run_sample_uses_case_customer_id_metadata(tmp_path: Path) -> None:
    app = _app_with_customer_facing_published_agent(tmp_path)
    campaign_path = _write_campaign_fixture(tmp_path, customer_id="CUST-001")

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        run_store=app.state.store,
        sample_runner=CustomerRunApiEvaluationSampleRunner(app),
    )

    subject_manifest = yaml.safe_load(
        (summary.artifact_dir / "subject_manifest.yaml").read_text(encoding="utf-8")
    )
    run_id = subject_manifest["subjects"][0]["run_ref"]["run_id"]
    conversation = _customer_conversation_for_run(app, run_id)

    assert conversation is not None
    assert conversation.customer_ref == "CUST-001"


def _app_with_customer_facing_published_agent(tmp_path: Path) -> Any:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(
        Path("examples/insurance_customer_service/agent.yaml"),
        store=store,
        actor="test-user",
    )
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_store=store,
    )
    TestClient(app)
    return app


def _write_campaign_fixture(tmp_path: Path, *, customer_id: str | None = None) -> Path:
    suite_path = tmp_path / "suite.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    metadata = (
        f"""
    metadata:
      customer_id: {customer_id}
"""
        if customer_id is not None
        else ""
    )
    suite_path.write_text(
        """
suite_id: customer_run_sample_smoke
version: "2026-06-22"
name: Customer Run Sample Smoke
cases:
  - case_id: inpatient_documents
    question: What documents are required for inpatient claim reimbursement?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: customer_service_fact
    capability_path: customer_projection
    expected:
      outcome: ANSWERED_WITH_CITATIONS
      response_assertions:
        must_not_include:
          - governance_details
          - Trace
"""
        + metadata,
        encoding="utf-8",
    )
    campaign_path.write_text(
        """
campaign_id: customer_run_adapter_probe
version: "2026-06-22"
target:
  agent_id: insurance_customer_service
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      produce_samples: true
      subject_manifest_id: customer_run_adapter_subjects
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path


def _customer_conversation_for_run(app: Any, run_id: str) -> Any | None:
    for path in app.state.customer_store.conversations_dir.glob("*/conversation.json"):
        conversation = app.state.customer_store.get_conversation(path.parent.name)
        if conversation is None:
            continue
        if any(snapshot.run_id == run_id for snapshot in conversation.snapshots):
            return conversation
    return None
