import json
from pathlib import Path
from typing import Any

import pytest

import proof_agent.delivery.run_execution_service as run_execution_service
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import ReceiptOutcome, RunResult
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.approval_resume import LangGraphApprovalResumeRegistry


def test_published_agent_run_uses_per_run_history_artifact_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = RunStore(tmp_path / "history")
    configuration_store = LocalAgentConfigurationStore(tmp_path / "config")
    captured: dict[str, Path] = {}

    def fake_run_with_langgraph(agent_yaml: Path, **kwargs: Any) -> RunResult:
        run_id = str(kwargs["run_id"])
        runs_dir = Path(kwargs["runs_dir"])
        captured["runs_dir"] = runs_dir
        runs_dir.mkdir(parents=True, exist_ok=True)
        trace_path = runs_dir / "trace.jsonl"
        receipt_path = runs_dir / "governance_receipt.md"
        trace_path.write_text(
            json.dumps({"event_type": "run_started", "run_id": run_id}) + "\n",
            encoding="utf-8",
        )
        receipt_path.write_text("# Receipt\n", encoding="utf-8")
        assert isinstance(kwargs["store"], RunStore)
        kwargs["store"].save_run_artifacts(
            run_id,
            trace_source=trace_path,
            receipt_source=receipt_path,
            question=str(kwargs["question"]),
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            run_purpose=kwargs["run_purpose"],
            agent_id=kwargs["agent_id"],
            agent_version_id=kwargs["agent_version_id"],
            draft_id=kwargs["draft_id"],
        )
        return RunResult(
            final_output="ok",
            outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
            trace_path=trace_path,
            receipt_path=receipt_path,
        )

    monkeypatch.setattr(
        run_execution_service,
        "run_with_langgraph",
        fake_run_with_langgraph,
    )

    execution = run_execution_service.execute_published_agent_run(
        dependencies=run_execution_service.RunExecutionDependencies(
            store=store,
            runs_dir=tmp_path / "latest",
            configuration_store=configuration_store,
            approval_resume_registry=LangGraphApprovalResumeRegistry(
                tmp_path / "approval_resume",
                configuration_store=configuration_store,
            ),
        ),
        published_agent=PublishedAgent(
            agent_id="enterprise_qa",
            manifest_path=Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
            display_name="Enterprise QA",
            purpose="Answer enterprise QA questions.",
            customer_facing=False,
            agent_version_id="version_001",
            source_draft_id="draft_001",
        ),
        question="What is the reimbursement rule for travel meals?",
    )

    expected_dir = store.history_dir / execution.detail.run_id
    assert captured["runs_dir"] == expected_dir
    assert (expected_dir / "trace.jsonl").exists()
    assert not (tmp_path / "latest" / "trace.jsonl").exists()
