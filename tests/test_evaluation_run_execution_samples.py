from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import EvaluationCaseRef, RunPurpose
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.run_execution_samples import RunExecutionApiEvaluationSampleRunner
from proof_agent.evaluation.sample_production import EvaluationSampleRequest
from proof_agent.observability.api.app import create_app


def test_campaign_uses_run_execution_api_adapter_for_evaluation_samples(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    campaign_path = _write_campaign_fixture(tmp_path)

    summary = run_evaluation_campaign(
        campaign_path=campaign_path,
        output_dir=tmp_path / "campaigns",
        run_store=app.state.store,
        sample_runner=RunExecutionApiEvaluationSampleRunner(app),
    )

    assert summary.readiness_status == "ready"
    subject_manifest_path = summary.artifact_dir / "subject_manifest.yaml"
    subject_manifest = yaml.safe_load(subject_manifest_path.read_text(encoding="utf-8"))
    run_id = subject_manifest["subjects"][0]["run_ref"]["run_id"]
    detail = app.state.store.get_run_detail(run_id)

    assert detail.run_purpose == RunPurpose.EVALUATION_SAMPLE
    assert detail.agent_id == "react_enterprise_qa_v3"
    assert detail.question == "What is the reimbursement rule for travel meals?"
    assert subject_manifest["subjects"][0]["execution_surface"] == "run_execution_api"
    assert subject_manifest["subjects"][0]["projections"]["evaluated_response"]["ref"].endswith(
        "operator_response.txt"
    )
    assert (app.state.store.history_dir / run_id / "operator_response.txt").read_text(
        encoding="utf-8"
    )


def test_run_execution_sample_runner_rejects_target_version_mismatch(
    tmp_path: Path,
) -> None:
    app = _app_with_published_agent(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
    )
    runner = RunExecutionApiEvaluationSampleRunner(app)

    with pytest.raises(
        EvaluationInputError,
        match="does not match active published Agent Version",
    ):
        runner(
            EvaluationSampleRequest(
                case_ref=EvaluationCaseRef(case_id="supported"),
                question="What is the reimbursement rule for travel meals?",
                target_agent_id="react_enterprise_qa_v3",
                target_agent_version_id="wrong_version",
            )
        )


def _app_with_published_agent(tmp_path: Path, manifest_path: Path) -> Any:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    TestClient(app)
    return app


def _write_campaign_fixture(tmp_path: Path) -> Path:
    suite_path = tmp_path / "suite.yaml"
    campaign_path = tmp_path / "campaign.yaml"
    suite_path.write_text(
        """
suite_id: run_execution_sample_smoke
version: "2026-06-22"
name: Run Execution Sample Smoke
cases:
  - case_id: supported
    question: What is the reimbursement rule for travel meals?
    intent_type: guidance
    expected_resolution: answer_with_citations
    risk_class: low
    capability_path: evidence_answer
    expected:
      outcome: ANSWERED_WITH_CITATIONS
""".lstrip(),
        encoding="utf-8",
    )
    campaign_path.write_text(
        """
campaign_id: run_execution_adapter_probe
version: "2026-06-22"
target:
  agent_id: react_enterprise_qa_v3
suites:
  formal:
    - source: core_regression
      suite_ref: suite.yaml
      produce_samples: true
      subject_manifest_id: run_execution_adapter_subjects
thresholds:
  governed_resolution_rate_min: 0.95
  artifact_sufficiency_required: 1.0
  deterministic_gate_pass_required: 1.0
""".lstrip(),
        encoding="utf-8",
    )
    return campaign_path
