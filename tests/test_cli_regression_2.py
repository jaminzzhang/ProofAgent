"""CLI lifecycle regression coverage after a repository-relative API run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import proof_agent.delivery.cli as cli_module
from proof_agent.observability.api.app import create_app


REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_AGENT = REPO_ROOT / "proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"
PUBLIC_AGENT = REPO_ROOT / "examples/agent_management_insurance_specialist/agent.yaml"
PUBLIC_AGENT_ID = "agent_management_insurance_specialist"
SUPPORTED_QUESTION = "住院理赔需要哪些材料？"


@dataclass(frozen=True)
class _CliStep:
    name: str
    exit_code: int
    output: str
    new_run_dirs: frozenset[Path]
    latest_exists: bool
    latest_resolved: Path


def test_api_run_then_demo_react_demo_and_run_keep_latest_resolvable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_module, "DEMO_AGENT_PATH", DEMO_AGENT)
    monkeypatch.setattr(cli_module, "REACT_DEMO_AGENT_PATH", DEMO_AGENT)
    application = create_app(
        history_dir=Path("runs/history"),
        runs_dir=Path("runs/latest"),
        conversations_dir=Path("runs/conversations"),
        published_agents={PUBLIC_AGENT_ID: PUBLIC_AGENT},
        agent_configuration_dir=Path("runs/config"),
    )
    response = TestClient(application).post(
        "/api/chat/runs",
        json={
            "agent_id": PUBLIC_AGENT_ID,
            "question": SUPPORTED_QUESTION,
        },
    )
    assert response.status_code == 200, response.text

    api_run_id = response.json()["run_id"]
    latest = Path("runs/latest")
    api_latest_exists = latest.exists()
    api_latest_resolved = latest.resolve()
    expected_api_run = Path("runs/history") / api_run_id
    runner = CliRunner()
    steps: list[_CliStep] = []
    commands = (
        ("demo", ["demo"]),
        ("react-demo", ["react-demo"]),
        (
            "run",
            [
                "run",
                str(PUBLIC_AGENT),
                "--question",
                SUPPORTED_QUESTION,
            ],
        ),
    )

    for name, command in commands:
        before = _history_run_dirs()
        result = runner.invoke(cli_module.app, command)
        after = _history_run_dirs()
        steps.append(
            _CliStep(
                name=name,
                exit_code=result.exit_code,
                output=result.output,
                new_run_dirs=frozenset(after - before),
                latest_exists=latest.exists(),
                latest_resolved=latest.resolve(),
            )
        )

    failures = "\n".join(f"{step.name}: exit={step.exit_code}\n{step.output}" for step in steps)
    assert all(step.exit_code == 0 for step in steps), failures
    assert api_latest_exists
    assert api_latest_resolved == expected_api_run.resolve()
    for step in steps:
        assert step.new_run_dirs, f"{step.name} did not persist a run"
        assert step.latest_exists, f"{step.name} left latest broken"
        assert step.latest_resolved in step.new_run_dirs


def _history_run_dirs() -> set[Path]:
    history = Path("runs/history")
    return {entry.resolve() for entry in history.iterdir() if entry.is_dir()}
