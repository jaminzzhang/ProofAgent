"""Tests for agent configuration metadata on persisted runs."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.contracts.dashboard import RunIndex, RunPurpose
from proof_agent.contracts.receipt import ReceiptOutcome
from proof_agent.observability.api.app import create_app
from proof_agent.observability.storage.run_store import RunStore


def _write_artifacts(tmp_path: Path, run_id: str) -> tuple[Path, Path]:
    trace_src = tmp_path / f"{run_id}.jsonl"
    receipt_src = tmp_path / f"{run_id}.md"
    trace_src.write_text(
        json.dumps({"event_type": "run_started", "run_id": run_id}) + "\n",
        encoding="utf-8",
    )
    receipt_src.write_text("# Receipt", encoding="utf-8")
    return trace_src, receipt_src


def test_save_run_artifacts_persists_agent_configuration_metadata(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    trace_src, receipt_src = _write_artifacts(tmp_path, "run_validation")

    index = store.save_run_artifacts(
        "run_validation",
        trace_source=trace_src,
        receipt_source=receipt_src,
        question="Validate draft",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        run_purpose=RunPurpose.VALIDATION,
        agent_id="agent_enterprise_qa",
        agent_version_id="version_001",
        draft_id="draft_001",
    )

    detail = store.get_run_detail(index.run_id)

    assert index.run_purpose == RunPurpose.VALIDATION
    assert detail is not None
    assert detail.run_purpose == RunPurpose.VALIDATION
    assert detail.agent_id == "agent_enterprise_qa"
    assert detail.agent_version_id == "version_001"
    assert detail.draft_id == "draft_001"


def test_list_runs_defaults_to_production_runs(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    store.write_run_meta(
        RunIndex(
            run_id="run_prod",
            question="Production question",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:19Z",
            run_purpose=RunPurpose.PRODUCTION,
        )
    )
    store.write_run_meta(
        RunIndex(
            run_id="run_validation",
            question="Validation question",
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            created_at="2026-05-10T14:32:20Z",
            updated_at="2026-05-10T14:32:21Z",
            run_purpose=RunPurpose.VALIDATION,
        )
    )

    production_runs, production_total = store.list_runs()
    validation_runs, validation_total = store.list_runs(run_purpose=RunPurpose.VALIDATION)
    all_runs, all_total = store.list_runs(run_purpose=None)

    assert production_total == 1
    assert production_runs[0].run_id == "run_prod"
    assert validation_total == 1
    assert validation_runs[0].run_id == "run_validation"
    assert all_total == 2
    assert {run.run_id for run in all_runs} == {"run_prod", "run_validation"}


def test_stats_exclude_validation_runs_by_default(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "history")
    store.write_run_meta(
        RunIndex(
            run_id="run_prod",
            question="Production question",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:19Z",
            run_purpose=RunPurpose.PRODUCTION,
        )
    )
    store.write_run_meta(
        RunIndex(
            run_id="run_validation",
            question="Validation question",
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            created_at="2026-05-10T14:32:20Z",
            updated_at="2026-05-10T14:32:21Z",
            run_purpose=RunPurpose.VALIDATION,
        )
    )

    stats = store.get_stats()

    assert stats["total_runs"] == 1
    assert stats["outcome_distribution"] == {"ANSWERED_WITH_CITATIONS": 1}


def test_runs_api_filters_by_run_purpose(tmp_path: Path) -> None:
    app = create_app(history_dir=tmp_path / "history")
    client = TestClient(app)
    store: RunStore = app.state.store
    store.write_run_meta(
        RunIndex(
            run_id="run_prod",
            question="Production question",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:18Z",
            updated_at="2026-05-10T14:32:19Z",
        )
    )
    store.write_run_meta(
        RunIndex(
            run_id="run_validation",
            question="Validation question",
            outcome=ReceiptOutcome.REFUSED_NO_EVIDENCE,
            created_at="2026-05-10T14:32:20Z",
            updated_at="2026-05-10T14:32:21Z",
            run_purpose=RunPurpose.VALIDATION,
        )
    )
    store.write_run_meta(
        RunIndex(
            run_id="run_evaluation_sample",
            question="Evaluation sample question",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            created_at="2026-05-10T14:32:22Z",
            updated_at="2026-05-10T14:32:23Z",
            run_purpose=RunPurpose.EVALUATION_SAMPLE,
        )
    )

    default_response = client.get("/api/runs")
    validation_response = client.get("/api/runs?run_purpose=validation")
    evaluation_sample_response = client.get("/api/runs?run_purpose=evaluation_sample")
    all_response = client.get("/api/runs?run_purpose=all")

    assert default_response.status_code == 200
    assert default_response.json()["meta"]["total"] == 1
    assert default_response.json()["data"][0]["run_id"] == "run_prod"
    assert validation_response.status_code == 200
    assert validation_response.json()["meta"]["total"] == 1
    assert validation_response.json()["data"][0]["run_id"] == "run_validation"
    assert evaluation_sample_response.status_code == 200
    assert evaluation_sample_response.json()["meta"]["total"] == 1
    assert evaluation_sample_response.json()["data"][0]["run_id"] == "run_evaluation_sample"
    assert all_response.status_code == 200
    assert all_response.json()["meta"]["total"] == 3
