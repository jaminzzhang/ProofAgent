from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest
from pydantic import TypeAdapter

from proof_agent.deployment.state import BlueGreenDeploymentRequest
from scripts.deployment import blue_green
from scripts.deployment import command_runner


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    def run(
        self,
        argv: list[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> blue_green.CommandResult:
        assert stdin is None
        assert env is None
        self.calls.append((list(argv), timeout_seconds))
        if argv[-3:] == ["ps", "-q", "gateway"]:
            return blue_green.CommandResult(stdout="gateway-container-id\n")
        return blue_green.CommandResult(stdout="")


def test_checked_in_request_example_is_strict_and_non_executable_placeholder() -> None:
    path = Path("deploy/production/blue-green-request.example.json")
    request = TypeAdapter(BlueGreenDeploymentRequest).validate_python(
        json.loads(path.read_text(encoding="utf-8"))
    )

    assert request.binding.release_id == "replace-with-candidate-release-id"
    assert request.drain_timeout_seconds == 150
    assert request.soak_seconds == 1800


def test_command_runner_uses_argument_vector_without_shell_or_error_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            argv,
            9,
            stdout=b"do-not-print-this",
            stderr=b"secret-like-diagnostic",
        )

    monkeypatch.setattr(command_runner.subprocess, "run", fake_run)

    with pytest.raises(blue_green.DeploymentToolError) as caught:
        blue_green.SubprocessCommandRunner().run(
            ["docker", "image", "inspect", "name@sha256:" + "a" * 64],
            timeout_seconds=30,
        )

    assert caught.value.error_code == "deployment_command_failed"
    assert captured["argv"] == [
        "docker",
        "image",
        "inspect",
        "name@sha256:" + "a" * 64,
    ]
    assert captured["shell"] is False
    assert "secret-like-diagnostic" not in str(caught.value)


def test_nginx_validation_stages_full_candidate_config_inside_gateway(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: {}\n", encoding="utf-8")
    nginx = tmp_path / "nginx.conf"
    nginx.write_text(
        "http { include /etc/nginx/proofagent/active-upstreams.conf; }\n",
        encoding="utf-8",
    )
    candidate = tmp_path / ".candidate.conf"
    candidate.write_text("upstream proofagent_api {}\n", encoding="utf-8")
    tls_ca = tmp_path / "ca.pem"
    tls_ca.write_text("not-read-during-validation\n", encoding="utf-8")
    monkeypatch.setattr(
        blue_green.ssl,
        "create_default_context",
        lambda **_kwargs: object(),
    )
    runner = FakeRunner()
    control = blue_green.DockerNginxGatewayControl(
        runner=runner,
        compose_file=compose,
        nginx_config=nginx,
        stable_origin="https://proof-agent.example.test",
        tls_ca_file=tls_ca,
    )

    control.validate(candidate)

    commands = [call[0] for call in runner.calls]
    assert commands[0] == [
        "docker",
        "compose",
        "-f",
        str(compose),
        "ps",
        "-q",
        "gateway",
    ]
    assert commands[1] == [
        "docker",
        "cp",
        str(candidate),
        "gateway-container-id:/tmp/proofagent-candidate-upstreams.conf",
    ]
    assert commands[3] == [
        "docker",
        "exec",
        "gateway-container-id",
        "nginx",
        "-t",
        "-c",
        "/tmp/proofagent-candidate-nginx.conf",
    ]
    assert candidate.is_file()
