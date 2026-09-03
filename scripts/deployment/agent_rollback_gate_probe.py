"""Verify the deployed Production Agent rollback route remains closed."""

from __future__ import annotations

from collections.abc import Mapping
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
import stat
import sys
from typing import Protocol, Sequence

from pydantic import TypeAdapter, ValidationError

from proof_agent.deployment.choreography import DeploymentActionError
from proof_agent.release.digests import reject_duplicate_json_keys
from scripts.deployment.compose_driver import (
    StableOriginClient,
    StableOriginResponse,
    StableSmokeSession,
)


_ROLLBACK_PATH = (
    "/api/config/agents/agent_rollback_gate_probe/versions/"
    "version_rollback_gate_target/rollback"
)
_ROLLBACK_BODY = b'{"expected_active_version_id":"version_rollback_gate_current"}'
_COOKIE_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class StableOriginTransport(Protocol):
    """Bounded transport required by the deployed gate probe."""

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        max_bytes: int = 1_048_576,
    ) -> StableOriginResponse: ...


def verify_production_local_agent_rollback_gate(
    *,
    origin: str,
    session_file: Path,
    client: StableOriginTransport,
) -> dict[str, object]:
    """Require the deployed security path to end at the closed rollback gate."""

    session = _load_private_session(session_file)
    session_response = client.request(
        "GET",
        "/api/auth/session",
        headers={
            "Cookie": f"proof_agent_session={session.session_cookie}",
        },
    )
    if session_response.status != 200:
        raise DeploymentActionError("rollback_gate_probe_session_failed")
    session_payload = _json_object(session_response)
    csrf_token = session_payload.get("csrf_token")
    permissions = session_payload.get("effective_permissions")
    if (
        not isinstance(csrf_token, str)
        or len(csrf_token) < 32
        or not isinstance(permissions, list)
        or "agent.publish" not in permissions
    ):
        raise DeploymentActionError("rollback_gate_probe_session_invalid")
    cookie = _rotated_session_cookie(
        session_response,
        fallback=session.session_cookie,
    )

    unauthenticated = client.request(
        "POST",
        _ROLLBACK_PATH,
        headers={"Content-Type": "application/json"},
        body=_ROLLBACK_BODY,
    )
    if unauthenticated.status != 401:
        raise DeploymentActionError(
            "rollback_gate_probe_unauthenticated_admission_failed"
        )

    csrf_missing = client.request(
        "POST",
        _ROLLBACK_PATH,
        headers={
            "Content-Type": "application/json",
            "Cookie": f"proof_agent_session={cookie}",
        },
        body=_ROLLBACK_BODY,
    )
    if csrf_missing.status != 403:
        raise DeploymentActionError("rollback_gate_probe_csrf_admission_failed")

    gate_closed = client.request(
        "POST",
        _ROLLBACK_PATH,
        headers={
            "Content-Type": "application/json",
            "Cookie": f"proof_agent_session={cookie}",
            "Origin": origin,
            "X-CSRF-Token": csrf_token,
        },
        body=_ROLLBACK_BODY,
    )
    if gate_closed.status != 503 or _json_object(gate_closed) != {
        "detail": "production_agent_rollback_unavailable"
    }:
        raise DeploymentActionError("rollback_gate_probe_gate_not_closed")

    return {
        "schema_version": "production-local-agent-rollback-gate-verification.v1",
        "evidence_class": "local_deployed_gate_closed_validation_only",
        "status": "passed",
        "unauthenticated_status": unauthenticated.status,
        "csrf_missing_status": csrf_missing.status,
        "gate_closed_status": gate_closed.status,
        "rollback_executed": False,
        "gate_activation_authorized": False,
        "production_go": False,
    }


def _load_private_session(path: Path) -> StableSmokeSession:
    try:
        path_stat = path.lstat()
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or stat.S_IMODE(path_stat.st_mode) & 0o077
            or path_stat.st_size > 2_048
        ):
            raise DeploymentActionError(
                "rollback_gate_probe_session_permissions_invalid"
            )
        raw = path.read_text(encoding="utf-8")
        reject_duplicate_json_keys(raw)
        return TypeAdapter(StableSmokeSession).validate_python(json.loads(raw))
    except DeploymentActionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise DeploymentActionError("rollback_gate_probe_session_invalid") from exc


def _json_object(response: StableOriginResponse) -> dict[str, object]:
    try:
        raw = response.body.decode("utf-8")
        reject_duplicate_json_keys(raw)
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DeploymentActionError("rollback_gate_probe_response_invalid") from exc
    if not isinstance(payload, dict):
        raise DeploymentActionError("rollback_gate_probe_response_invalid")
    return payload


def _rotated_session_cookie(
    response: StableOriginResponse,
    *,
    fallback: str,
) -> str:
    raw = response.headers.get("set-cookie")
    if not raw:
        return fallback
    cookies = SimpleCookie()
    try:
        cookies.load(raw)
    except Exception as exc:
        raise DeploymentActionError("rollback_gate_probe_session_invalid") from exc
    morsel = cookies.get("proof_agent_session")
    if (
        morsel is None
        or not 32 <= len(morsel.value) <= 512
        or _COOKIE_PATTERN.fullmatch(morsel.value) is None
    ):
        raise DeploymentActionError("rollback_gate_probe_session_invalid")
    return morsel.value


def main(argv: Sequence[str] | None = None) -> None:
    """Run the bounded probe with host-entry supplied deployment paths."""

    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        raise DeploymentActionError("rollback_gate_probe_arguments_invalid")
    origin, ca_file_value, session_file_value = arguments
    client = StableOriginClient(
        origin=origin,
        tls_ca_file=Path(ca_file_value),
    )
    result = verify_production_local_agent_rollback_gate(
        origin=origin,
        session_file=Path(session_file_value),
        client=client,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


def cli(argv: Sequence[str] | None = None) -> int:
    """Return one trace-safe result without exposing session or response detail."""

    try:
        main(argv)
    except Exception as exc:
        payload = {
            "schema_version": (
                "production-local-agent-rollback-gate-verification-failure.v1"
            ),
            "status": "failed",
            "error_code": "agent_rollback_gate_verification_failed",
        }
        if isinstance(exc, DeploymentActionError):
            payload["reason_code"] = exc.error_code
        print(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
        return 1
    return 0


__all__ = [
    "StableOriginTransport",
    "cli",
    "main",
    "verify_production_local_agent_rollback_gate",
]


if __name__ == "__main__":
    raise SystemExit(cli())
