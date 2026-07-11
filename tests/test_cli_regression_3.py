from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from proof_agent.delivery.cli import app
from proof_agent.delivery.remote_verify_gateway import VERIFY_REMOTE_CHAT_BASE


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_verify_remote_builds_before_supervising_preview_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        "proof_agent.delivery.cli.which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        events.append(
            (
                "build",
                {
                    "command": command,
                    "env": kwargs.get("env"),
                    "process_env": {
                        "VITE_CHAT_URL": os.environ.get("VITE_CHAT_URL"),
                        "VITE_DASHBOARD_URL": os.environ.get("VITE_DASHBOARD_URL"),
                    },
                    "check": kwargs.get("check"),
                },
            )
        )
        return subprocess.CompletedProcess(command, 0)

    def fake_run_dev_processes(specs: list[tuple[str, list[str]]]) -> None:
        events.append(
            (
                "supervise",
                {
                    "specs": specs,
                    "process_env": {
                        "VITE_CHAT_URL": os.environ.get("VITE_CHAT_URL"),
                        "VITE_DASHBOARD_URL": os.environ.get("VITE_DASHBOARD_URL"),
                    },
                },
            )
        )

    monkeypatch.setattr("proof_agent.delivery.cli.subprocess.run", fake_run)
    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)
    monkeypatch.setenv("VITE_CHAT_URL", "http://localhost:5174")
    monkeypatch.setenv("VITE_DASHBOARD_URL", "http://localhost:5173")

    result = runner.invoke(
        app,
        ["verify-remote", "--local-only", "--no-worker", "--no-cleanup"],
    )

    assert result.exit_code == 0, result.exception
    assert [kind for kind, _payload in events] == ["build", "build", "supervise"]

    dashboard_build = events[0][1]
    chat_build = events[1][1]
    assert dashboard_build["command"] == [
        "/usr/bin/npm",
        "run",
        "build",
        "-w",
        "proof-agent-dashboard",
    ]
    assert chat_build["command"] == [
        "/usr/bin/npm",
        "run",
        "build",
        "-w",
        "proof-agent-chat",
        "--",
        "--base",
        VERIFY_REMOTE_CHAT_BASE,
    ]
    for build in (dashboard_build, chat_build):
        assert build["check"] is True
        assert build["process_env"] == {"VITE_CHAT_URL": "", "VITE_DASHBOARD_URL": ""}
        assert build["env"]["VITE_CHAT_URL"] == ""
        assert build["env"]["VITE_DASHBOARD_URL"] == ""

    supervised = events[2][1]
    specs = dict(supervised["specs"])
    assert supervised["process_env"] == {"VITE_CHAT_URL": "", "VITE_DASHBOARD_URL": ""}
    assert specs["dashboard"] == [
        "/usr/bin/npm",
        "run",
        "preview",
        "-w",
        "proof-agent-dashboard",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5173",
    ]
    assert specs["chat"] == [
        "/usr/bin/npm",
        "run",
        "preview",
        "-w",
        "proof-agent-chat",
        "--",
        "--host",
        "127.0.0.1",
        "--port",
        "5174",
        "--base",
        VERIFY_REMOTE_CHAT_BASE,
    ]
    assert os.environ["VITE_CHAT_URL"] == "http://localhost:5174"
    assert os.environ["VITE_DASHBOARD_URL"] == "http://localhost:5173"


def test_verify_remote_build_failure_never_starts_supervisor_and_restores_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervised = False

    monkeypatch.setattr(
        "proof_agent.delivery.cli.which",
        lambda name: "/usr/bin/npm" if name == "npm" else None,
    )

    def fail_build(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(returncode=7, cmd=command)

    def fake_run_dev_processes(_specs: list[tuple[str, list[str]]]) -> None:
        nonlocal supervised
        supervised = True

    monkeypatch.setattr("proof_agent.delivery.cli.subprocess.run", fail_build)
    monkeypatch.setattr("proof_agent.delivery.cli._run_dev_processes", fake_run_dev_processes)
    monkeypatch.setenv("VITE_CHAT_URL", "original-chat")
    monkeypatch.setenv("VITE_DASHBOARD_URL", "original-dashboard")

    result = runner.invoke(
        app,
        ["verify-remote", "--local-only", "--no-worker", "--no-cleanup"],
    )

    assert result.exit_code == 7
    assert supervised is False
    assert os.environ["VITE_CHAT_URL"] == "original-chat"
    assert os.environ["VITE_DASHBOARD_URL"] == "original-dashboard"


def test_direct_frontend_dev_scripts_still_enable_vite_development_mode() -> None:
    for workspace in ("dashboard", "chat"):
        package = json.loads((REPO_ROOT / workspace / "package.json").read_text(encoding="utf-8"))
        assert package["scripts"]["dev"] == "vite"
        assert package["scripts"]["preview"] == "vite preview"
