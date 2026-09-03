from __future__ import annotations

import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Mapping

import pytest

from proof_agent.deployment.choreography import DeploymentActionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://proof-agent.localhost:8443"
SESSION_COOKIE = "s" * 48
ROTATED_SESSION_COOKIE = "r" * 48
CSRF_TOKEN = "c" * 64


def _probe() -> ModuleType:
    return importlib.import_module("scripts.deployment.agent_rollback_gate_probe")


class _Response:
    def __init__(
        self,
        status: int,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.status = status
        self.headers = dict(headers or {})
        self.body = json.dumps(body or {}).encode("utf-8")


class _RecordingStableOriginClient:
    def __init__(
        self,
        *,
        permissions: list[object] | None = None,
        gate_body: Mapping[str, object] | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.permissions = permissions or ["agent.publish"]
        self.gate_body = gate_body or {
            "detail": "production_agent_rollback_unavailable"
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        max_bytes: int = 1_048_576,
    ) -> _Response:
        del max_bytes
        call = {
            "method": method,
            "path": path,
            "headers": dict(headers or {}),
            "body": body,
        }
        self.calls.append(call)
        index = len(self.calls)
        if index == 1:
            return _Response(
                200,
                body={
                    "csrf_token": CSRF_TOKEN,
                    "effective_permissions": self.permissions,
                },
                headers={
                    "set-cookie": (
                        "proof_agent_session="
                        f"{ROTATED_SESSION_COOKIE}; Secure; HttpOnly; SameSite=Lax"
                    )
                },
            )
        if index == 2:
            return _Response(401)
        if index == 3:
            return _Response(403)
        if index == 4:
            return _Response(
                503,
                body=self.gate_body,
            )
        raise AssertionError(call)


def test_deployed_probe_requires_401_403_then_exact_closed_gate_503(
    tmp_path: Path,
) -> None:
    probe = _probe()
    session_file = tmp_path / "rollback-gate-session.json"
    session_file.write_text(
        json.dumps({"session_cookie": SESSION_COOKIE}) + "\n",
        encoding="utf-8",
    )
    session_file.chmod(0o600)
    client = _RecordingStableOriginClient()

    result = probe.verify_production_local_agent_rollback_gate(
        origin=ORIGIN,
        session_file=session_file,
        client=client,
    )

    assert result == {
        "schema_version": "production-local-agent-rollback-gate-verification.v1",
        "evidence_class": "local_deployed_gate_closed_validation_only",
        "status": "passed",
        "unauthenticated_status": 401,
        "csrf_missing_status": 403,
        "gate_closed_status": 503,
        "rollback_executed": False,
        "gate_activation_authorized": False,
        "production_go": False,
    }
    assert [
        (call["method"], call["path"]) for call in client.calls
    ] == [
        ("GET", "/api/auth/session"),
        (
            "POST",
            "/api/config/agents/agent_rollback_gate_probe/versions/"
            "version_rollback_gate_target/rollback",
        ),
        (
            "POST",
            "/api/config/agents/agent_rollback_gate_probe/versions/"
            "version_rollback_gate_target/rollback",
        ),
        (
            "POST",
            "/api/config/agents/agent_rollback_gate_probe/versions/"
            "version_rollback_gate_target/rollback",
        ),
    ]
    session_headers = client.calls[0]["headers"]
    assert session_headers == {
        "Cookie": f"proof_agent_session={SESSION_COOKIE}",
    }
    assert client.calls[1]["headers"] == {"Content-Type": "application/json"}
    assert client.calls[2]["headers"] == {
        "Content-Type": "application/json",
        "Cookie": f"proof_agent_session={ROTATED_SESSION_COOKIE}",
    }
    assert client.calls[3]["headers"] == {
        "Content-Type": "application/json",
        "Cookie": f"proof_agent_session={ROTATED_SESSION_COOKIE}",
        "Origin": ORIGIN,
        "X-CSRF-Token": CSRF_TOKEN,
    }
    assert {
        call["body"] for call in client.calls if call["method"] == "POST"
    } == {
        b'{"expected_active_version_id":"version_rollback_gate_current"}'
    }


def test_deployed_probe_host_entry_accepts_only_a_private_session_file() -> None:
    path = (
        PROJECT_ROOT
        / "scripts"
        / "production-local-verify-agent-rollback-gate.sh"
    )

    script = path.read_text(encoding="utf-8")

    assert 'if [ "$#" -ne 1 ]' in script
    assert "agent_rollback_gate_probe" in script
    assert "https://proof-agent.localhost:8443" in script
    assert "docker/production-local/runtime/tls/ca.crt" in script
    for forbidden in (
        ".env.production-local",
        "docker compose",
        "production_agent_rollback_enabled",
        "session_cookie=",
        "proof_agent_session=",
    ):
        assert forbidden not in script


@pytest.mark.parametrize("unsafe_kind", ["group_readable", "symlink"])
def test_deployed_probe_rejects_unsafe_session_file_before_https(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    probe = _probe()
    private_file = tmp_path / "private-session.json"
    private_file.write_text(
        json.dumps({"session_cookie": SESSION_COOKIE}) + "\n",
        encoding="utf-8",
    )
    private_file.chmod(0o600)
    session_file = private_file
    if unsafe_kind == "group_readable":
        private_file.chmod(0o640)
    else:
        session_file = tmp_path / "session-link.json"
        session_file.symlink_to(private_file)

    client = _RecordingStableOriginClient()
    with pytest.raises(
        DeploymentActionError,
        match="rollback_gate_probe_session_permissions_invalid",
    ):
        probe.verify_production_local_agent_rollback_gate(
            origin=ORIGIN,
            session_file=session_file,
            client=client,
        )

    assert client.calls == []


def test_deployed_probe_requires_publish_permission_before_rollback_posts(
    tmp_path: Path,
) -> None:
    probe = _probe()
    session_file = tmp_path / "rollback-gate-session.json"
    session_file.write_text(
        json.dumps({"session_cookie": SESSION_COOKIE}) + "\n",
        encoding="utf-8",
    )
    session_file.chmod(0o600)
    client = _RecordingStableOriginClient(permissions=["agent.view"])

    with pytest.raises(
        DeploymentActionError,
        match="rollback_gate_probe_session_invalid",
    ):
        probe.verify_production_local_agent_rollback_gate(
            origin=ORIGIN,
            session_file=session_file,
            client=client,
        )

    assert len(client.calls) == 1


def test_deployed_probe_rejects_non_exact_closed_gate_response(
    tmp_path: Path,
) -> None:
    probe = _probe()
    session_file = tmp_path / "rollback-gate-session.json"
    session_file.write_text(
        json.dumps({"session_cookie": SESSION_COOKIE}) + "\n",
        encoding="utf-8",
    )
    session_file.chmod(0o600)
    client = _RecordingStableOriginClient(
        gate_body={
            "detail": "production_agent_rollback_unavailable",
            "internal": "must-not-be-accepted",
        }
    )

    with pytest.raises(
        DeploymentActionError,
        match="rollback_gate_probe_gate_not_closed",
    ):
        probe.verify_production_local_agent_rollback_gate(
            origin=ORIGIN,
            session_file=session_file,
            client=client,
        )


def test_deployed_probe_cli_hides_failure_detail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    probe = _probe()
    secret_sentinel = "private-session-cookie-must-not-appear"

    def fail(argv: object = None) -> None:
        del argv
        raise RuntimeError(secret_sentinel)

    monkeypatch.setattr(probe, "main", fail)

    assert probe.cli([]) == 1

    output = capsys.readouterr()
    assert json.loads(output.err) == {
        "schema_version": (
            "production-local-agent-rollback-gate-verification-failure.v1"
        ),
        "status": "failed",
        "error_code": "agent_rollback_gate_verification_failed",
    }
    assert secret_sentinel not in output.err
    assert output.out == ""
