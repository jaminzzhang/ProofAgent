from pathlib import Path

from typer.testing import CliRunner

from proof_agent.delivery.cli import app
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
