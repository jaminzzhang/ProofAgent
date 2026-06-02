from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_agent.capabilities.knowledge.ingestion.contracts import KnowledgeWorkerDiagnostic
from proof_agent.capabilities.knowledge.ingestion.worker import (
    KnowledgeWorkerResult,
    KnowledgeWorkerTaskOutcome,
)
from proof_agent.delivery.cli import app
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.compare.result import RagResult


runner = CliRunner()


def test_demo_command_exists() -> None:
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "Proof Agent demo" in result.output


def test_react_demo_command_runs_no_key_scenarios() -> None:
    result = runner.invoke(app, ["react-demo"])
    assert result.exit_code == 0
    assert "Proof Agent ReAct demo" in result.output
    assert "supported: ANSWERED_WITH_CITATIONS" in result.output
    assert "unsupported: REFUSED_NO_EVIDENCE" in result.output
    assert "clarify: WAITING_FOR_USER_CLARIFICATION" in result.output
    assert "tool_required: WAITING_FOR_APPROVAL" in result.output


def test_doctor_command_exists() -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Python" in result.output


def test_compare_command_runs_supplied_manifest(monkeypatch) -> None:
    calls = []

    def fake_run_harness_rag(question: str, *, agent_yaml: Path) -> RagResult:
        calls.append((question, agent_yaml))
        return RagResult(outcome="REFUSED_NO_EVIDENCE", message="Governed refusal")

    monkeypatch.setattr("proof_agent.delivery.cli.run_harness_rag", fake_run_harness_rag)

    result = runner.invoke(
        app,
        [
            "compare",
            "custom/agent.yaml",
            "--question",
            "What discount should we give this customer next year?",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        ("What discount should we give this customer next year?", Path("custom/agent.yaml"))
    ]


def test_inspect_trace_jsonl(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"run_id":"run_test","event_type":"run_started","sequence":1,"redaction":{"applied":false}}\n'
        '{"run_id":"run_test","event_type":"final_output","sequence":2,"redaction":{"applied":true}}\n',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inspect", str(trace_path)])
    assert result.exit_code == 0
    assert "Trace events: 2" in result.output
    assert "Redaction applied: yes" in result.output


def test_inspect_governance_receipt(tmp_path: Path) -> None:
    receipt_path = tmp_path / "governance_receipt.md"
    receipt_path.write_text(
        "# Governance Receipt\n\n## Final Outcome\n\nANSWERED_WITH_CITATIONS\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["inspect", str(receipt_path)])
    assert result.exit_code == 0
    assert "Final Outcome: ANSWERED_WITH_CITATIONS" in result.output


def test_knowledge_worker_prints_diagnostics_before_task_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(
            outcome=KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_123",
                source_id="source_ready",
                state="accepted",
            ),
            diagnostics=(
                KnowledgeWorkerDiagnostic(
                    source_id="source_invalid",
                    code="PA_CONFIG_001",
                    message="Malformed Source configuration.",
                ),
            ),
        ),
    )

    assert result.exit_code == 0
    warning = "knowledge worker warning: source_invalid (PA_CONFIG_001)"
    outcome = "knowledge upload accepted: upload_123"
    assert warning in result.output
    assert outcome in result.output
    assert result.output.index(warning) < result.output.index(outcome)


def test_knowledge_worker_diagnostics_only_does_not_print_no_task(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(
            outcome=None,
            diagnostics=(
                KnowledgeWorkerDiagnostic(
                    source_id="source_invalid",
                    code="PA_CONFIG_001",
                    message="Malformed Source configuration.",
                ),
            ),
        ),
    )

    assert result.exit_code == 0
    assert "knowledge worker warning: source_invalid (PA_CONFIG_001)" in result.output
    assert "no queued knowledge tasks" not in result.output


def test_knowledge_worker_once_prints_no_task_text_when_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(monkeypatch, tmp_path, worker_result=None)

    assert result.exit_code == 0
    assert "no queued knowledge tasks" in result.output


@pytest.mark.parametrize(
    ("outcome", "expected_output"),
    [
        (
            KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_accepted",
                source_id="source_local",
                state="accepted",
            ),
            "knowledge upload accepted: upload_accepted",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="quarantine_validation",
                task_id="upload_rejected",
                source_id="source_local",
                state="rejected",
                error_code="PA_INGESTION_002",
            ),
            "knowledge upload rejected: upload_rejected (PA_INGESTION_002)",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_ready",
                source_id="source_local",
                state="ready",
            ),
            "knowledge ingestion job ready: job_ready",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_retry",
                source_id="source_local",
                state="retry_scheduled",
                error_code="PA_INGESTION_003",
            ),
            "knowledge ingestion job retry scheduled: job_retry (PA_INGESTION_003)",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_deferred",
                source_id="source_local",
                state="deferred",
            ),
            "knowledge ingestion job deferred: job_deferred",
        ),
        (
            KnowledgeWorkerTaskOutcome(
                kind="artifact_build",
                task_id="job_failed",
                source_id="source_local",
                state="failed",
                error_code="PA_INGESTION_003",
            ),
            "knowledge ingestion job failed: job_failed (PA_INGESTION_003)",
        ),
    ],
)
def test_knowledge_worker_prints_task_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    outcome: KnowledgeWorkerTaskOutcome,
    expected_output: str,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        worker_result=KnowledgeWorkerResult(outcome=outcome),
    )

    assert result.exit_code == 0
    assert expected_output in result.output


def test_knowledge_worker_store_lock_timeout_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = _invoke_knowledge_worker(
        monkeypatch,
        tmp_path,
        error=ProofAgentError(
            "PA_INGESTION_004",
            "Timed out waiting for the knowledge store lock.",
            "Retry later.",
        ),
    )

    assert result.exit_code != 0
    assert "PA_INGESTION_004" in result.output


def test_knowledge_worker_requires_once_for_bounded_execution() -> None:
    result = runner.invoke(app, ["knowledge-worker"])

    assert result.exit_code != 0
    assert "--once" in result.output
    assert "continuous" in result.output.lower()


def _invoke_knowledge_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    worker_result: KnowledgeWorkerResult | None = None,
    error: ProofAgentError | None = None,
):
    class FakeKnowledgeIngestionWorker:
        def __init__(self, **_: object) -> None:
            pass

        def run_once(self) -> KnowledgeWorkerResult | None:
            if error is not None:
                raise error
            return worker_result

    monkeypatch.setattr(
        "proof_agent.capabilities.knowledge.ingestion.worker.KnowledgeIngestionWorker",
        FakeKnowledgeIngestionWorker,
    )
    return runner.invoke(
        app,
        ["knowledge-worker", "--config-dir", str(tmp_path), "--once"],
    )
