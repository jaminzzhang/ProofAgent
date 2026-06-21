from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from proof_agent.delivery.cli import app


pytestmark = [
    pytest.mark.llm_regression,
    pytest.mark.skipif(
        os.environ.get("PROOF_AGENT_RUN_LLM_REGRESSION") != "1",
        reason="set PROOF_AGENT_RUN_LLM_REGRESSION=1 to run real LLM regression tests",
    ),
    pytest.mark.skipif(
        not os.environ.get("OPENAI_COMPATIBLE_API_KEY"),
        reason="OPENAI_COMPATIBLE_API_KEY is required for real LLM regression tests",
    ),
    pytest.mark.skipif(
        not os.environ.get("OPENAI_COMPATIBLE_BASE_URL"),
        reason="OPENAI_COMPATIBLE_BASE_URL is required for real LLM regression tests",
    ),
]


def test_v3_intent_execution_suite_passes_real_llm_gate(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "evaluate",
            "run-suite",
            "--suite",
            "v3_intent_execution",
            "--agent",
            "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3_bfsp/agent.llm.yaml",
            "--output-dir",
            str(tmp_path / "evaluations"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Release Decision: passed" in result.output
    report = (
        tmp_path
        / "evaluations"
        / "v3_intent_execution-v3_intent_execution_run_subjects"
        / "evaluation_report.md"
    ).read_text(encoding="utf-8")
    assert "- bfsp_recommendation_accuracy:" in report
    assert "- action_constraint_rewrite_rate:" in report
