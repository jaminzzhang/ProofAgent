"""First-party same-host Docker Compose operations for Blue/Green deployment."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPException, HTTPSConnection
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import ssl
import stat
import tempfile
import time
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, TypeAdapter, ValidationError, field_validator, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.deployment.choreography import DeploymentActionError
from proof_agent.deployment.compatibility import (
    deployment_compatibility_sha256,
    load_deployment_compatibility_manifest,
)
from proof_agent.deployment.state import BlueGreenDeploymentRequest, DeploymentSlot
from proof_agent.release.digests import reject_duplicate_json_keys, sha256_hex
from scripts.deployment.command_runner import (
    DeploymentCommandRunner,
    DeploymentToolError,
)


BUILT_IN_DRIVER_NAME = "docker-compose-v1"
_IMAGE_REFERENCE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")
_SAFE_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
_WORKER_SERVICES = ("run-executor", "knowledge-worker")
_PRODUCT_SERVICES = (
    "api",
    "run-executor",
    "knowledge-worker",
    "dashboard",
    "operator-chat",
)
_QUEUE_CONTRACT_VALIDATOR = """\
import json
import sys
from proof_agent.contracts.run_execution import RunRequest

try:
    payload = json.load(sys.stdin)
    requests = payload["requests"]
    if not isinstance(requests, list) or not requests:
        raise ValueError("requests must be a non-empty list")
    for request in requests:
        RunRequest.model_validate(request)
except Exception:
    result = {"compatible": False, "count": 0}
else:
    result = {"compatible": True, "count": len(requests)}
print(json.dumps(result, separators=(",", ":"), sort_keys=True))
"""
_ADMISSION_INCLUDE_DIRECTIVE = (
    "include /etc/nginx/proofagent/admission-control.conf;"
)


@dataclass(frozen=True)
class StableOriginResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class StableOriginClient:
    """Bounded HTTPS transport used only by deployment smoke checks."""

    def __init__(self, *, origin: str, tls_ca_file: Path) -> None:
        parsed = urlsplit(origin)
        assert parsed.hostname is not None
        self._host = parsed.hostname
        self._port = parsed.port or 443
        self._tls_ca_file = tls_ca_file

    def request(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        max_bytes: int = 1_048_576,
    ) -> StableOriginResponse:
        connection = self._connection()
        try:
            connection.request(method, path, body=body, headers=dict(headers or {}))
            response = connection.getresponse()
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise DeploymentActionError("stable_smoke_response_too_large")
            return StableOriginResponse(
                status=response.status,
                headers=self._response_headers(response.getheaders()),
                body=content,
            )
        except (HTTPException, OSError, ssl.SSLError) as exc:
            raise DeploymentActionError("stable_smoke_request_failed") from exc
        finally:
            connection.close()

    def first_sse_event(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
    ) -> StableOriginResponse:
        connection = self._connection()
        try:
            connection.request("GET", path, headers=dict(headers))
            response = connection.getresponse()
            chunks: list[bytes] = []
            size = 0
            while True:
                line = response.readline(4097)
                size += len(line)
                if size > 4096:
                    raise DeploymentActionError("stable_smoke_sse_event_too_large")
                chunks.append(line)
                if line in {b"", b"\n", b"\r\n"}:
                    break
            return StableOriginResponse(
                status=response.status,
                headers=self._response_headers(response.getheaders()),
                body=b"".join(chunks),
            )
        except (HTTPException, OSError, ssl.SSLError) as exc:
            raise DeploymentActionError("stable_smoke_sse_failed") from exc
        finally:
            connection.close()

    def _connection(self) -> HTTPSConnection:
        return HTTPSConnection(
            self._host,
            self._port,
            timeout=10,
            context=ssl.create_default_context(cafile=str(self._tls_ca_file)),
        )

    @staticmethod
    def _response_headers(items: Sequence[tuple[str, str]]) -> dict[str, str]:
        return {key.lower(): value for key, value in items}


class StableSmokeSession(StrictFrozenModel):
    session_cookie: str = Field(min_length=32, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class StableSmokeRequest(StrictFrozenModel):
    agent_id: str = Field(min_length=1, max_length=255, pattern=_SAFE_IDENTIFIER)
    question: str = Field(min_length=1, max_length=2048)


class ComposeSlotConfig(StrictFrozenModel):
    slot: DeploymentSlot
    slot_number: int = Field(ge=1, le=2)
    project_name: str = Field(min_length=1, max_length=128, pattern=_SAFE_IDENTIFIER)
    release_id: str = Field(min_length=1, max_length=128, pattern=_SAFE_IDENTIFIER)
    image_reference: str = Field(min_length=80, max_length=512)
    schema_revision: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    )
    active_environment_file: Path
    standby_environment_file: Path
    run_executor_owner_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_SAFE_IDENTIFIER,
    )
    knowledge_worker_owner_id: str = Field(
        min_length=1,
        max_length=255,
        pattern=_SAFE_IDENTIFIER,
    )

    @field_validator("image_reference")
    @classmethod
    def require_immutable_image(cls, value: str) -> str:
        if _IMAGE_REFERENCE.fullmatch(value) is None:
            raise ValueError("Compose slot image must be an immutable sha256 reference")
        return value

    @model_validator(mode="after")
    def bind_slot_number(self) -> Self:
        expected = 1 if self.slot is DeploymentSlot.BLUE else 2
        if self.slot_number != expected:
            raise ValueError("blue uses slot 1 and green uses slot 2")
        return self

    @property
    def image_digest(self) -> str:
        return self.image_reference.rsplit("@sha256:", 1)[1]


class DockerComposeDriverConfig(StrictFrozenModel):
    schema_version: Literal["proofagent.docker-compose-blue-green-driver.v1"]
    slot_compose_file: Path
    deployment_compatibility_manifest: Path
    migration_set_file: Path
    vault_compatibility_file: Path
    vault_agent_token_secret: str = Field(
        min_length=1,
        max_length=255,
        pattern=_SAFE_IDENTIFIER,
    )
    active_gateway_include: Path
    gateway_compose_file: Path
    gateway_nginx_config: Path
    gateway_admission_include: Path
    stable_origin: str = Field(min_length=9, max_length=512)
    tls_ca_file: Path
    stable_smoke_session_file: Path
    stable_smoke_request_file: Path
    stable_smoke_timeout_seconds: int = Field(default=180, ge=30, le=300)
    worker_lease_expiry_wait_seconds: int = Field(default=20, ge=16, le=305)
    old: ComposeSlotConfig
    candidate: ComposeSlotConfig
    old_api_queue_fixtures: Path
    candidate_api_queue_fixtures: Path

    @model_validator(mode="after")
    def require_opposite_slots(self) -> Self:
        if self.old.slot is self.candidate.slot:
            raise ValueError("Compose old and candidate slots must differ")
        if self.old.project_name == self.candidate.project_name:
            raise ValueError("Compose slots require distinct project names")
        gateway_parent = self.gateway_compose_file.parent.resolve()
        if any(
            path.parent.resolve() != gateway_parent
            for path in (
                self.gateway_nginx_config,
                self.gateway_admission_include,
                self.active_gateway_include,
            )
        ):
            raise ValueError("Gateway files must share the Compose bind directory")
        if (
            self.gateway_nginx_config.name != "nginx.conf"
            or self.gateway_admission_include.name != "admission-control.conf"
            or self.active_gateway_include.name != "active-upstreams.conf"
        ):
            raise ValueError("Gateway controller filenames are fixed")
        return self

    @field_validator("stable_origin")
    @classmethod
    def require_https_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("stable_origin must be an HTTPS origin")
        return value.rstrip("/")


class DockerComposeBlueGreenOperations:
    """Concrete shell-free Compose boundary for the approved deployment sequence."""

    def __init__(
        self,
        config: DockerComposeDriverConfig,
        *,
        runner: DeploymentCommandRunner,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        admission_probe: Callable[[bool], None] | None = None,
        stable_client: StableOriginClient | None = None,
    ) -> None:
        self._config = config
        self._runner = runner
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self._admission_probe = admission_probe or self._probe_admission_endpoint
        self._stable_client = stable_client or StableOriginClient(
            origin=config.stable_origin,
            tls_ca_file=config.tls_ca_file,
        )
        self._validated_file_sha256: dict[Path, str] | None = None

    @classmethod
    def from_mapping(
        cls,
        config: Mapping[str, object],
        *,
        runner: DeploymentCommandRunner,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        admission_probe: Callable[[bool], None] | None = None,
        stable_client: StableOriginClient | None = None,
    ) -> DockerComposeBlueGreenOperations:
        validated = TypeAdapter(DockerComposeDriverConfig).validate_python(config)
        return cls(
            validated,
            runner=runner,
            clock=clock,
            sleeper=sleeper,
            admission_probe=admission_probe,
            stable_client=stable_client,
        )

    def validate_prechecks(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        self._require_files(
            self._config.slot_compose_file,
            self._config.deployment_compatibility_manifest,
            self._config.migration_set_file,
            self._config.vault_compatibility_file,
            self._config.active_gateway_include,
            self._config.gateway_compose_file,
            self._config.gateway_nginx_config,
            self._config.gateway_admission_include,
            self._config.tls_ca_file,
            self._config.stable_smoke_session_file,
            self._config.stable_smoke_request_file,
            self._config.old_api_queue_fixtures,
            self._config.candidate_api_queue_fixtures,
            self._config.old.active_environment_file,
            self._config.old.standby_environment_file,
            self._config.candidate.active_environment_file,
            self._config.candidate.standby_environment_file,
        )
        manifest = load_deployment_compatibility_manifest(
            self._config.deployment_compatibility_manifest,
            checked_at=self._now(),
        )
        if (
            deployment_compatibility_sha256(manifest)
            != request.binding.deployment_compatibility_manifest_sha256
        ):
            raise DeploymentActionError("deployment_manifest_binding_mismatch")
        if (
            sha256_hex(self._config.migration_set_file.read_bytes())
            != request.binding.migration_set_sha256
        ):
            raise DeploymentActionError("migration_set_binding_mismatch")
        self._validate_environment(
            self._config.old,
            self._config.old.active_environment_file,
            activation="active",
        )
        self._validate_environment(
            self._config.old,
            self._config.old.standby_environment_file,
            activation="standby",
        )
        self._validate_environment(
            self._config.candidate,
            self._config.candidate.active_environment_file,
            activation="active",
        )
        self._validate_environment(
            self._config.candidate,
            self._config.candidate.standby_environment_file,
            activation="standby",
        )
        self._validate_active_gateway(request)
        self._load_stable_smoke_inputs()
        if self._config.gateway_admission_include.read_bytes() != (
            self._render_admission_include(paused=False)
        ):
            raise DeploymentActionError("gateway_admission_state_mismatch")
        for image in (
            self._config.old.image_reference,
            self._config.candidate.image_reference,
        ):
            self._run(
                ["docker", "image", "inspect", image],
                timeout_seconds=30,
            )
        for slot, environment_file in (
            (self._config.old, self._config.old.active_environment_file),
            (
                self._config.candidate,
                self._config.candidate.standby_environment_file,
            ),
        ):
            self._compose(
                slot,
                environment_file,
                "config",
                "--quiet",
                timeout_seconds=30,
            )
        self.assert_old_api_ready(request)
        authority = self._exec_python(
            self._config.old,
            "api",
            self._worker_epoch_script(self._config.old),
            timeout_seconds=15,
            active=True,
        )
        if not self._parse_worker_epoch(
            authority,
            expected_epoch=request.old_activation_epoch,
        ):
            raise DeploymentActionError("old_worker_epoch_mismatch")
        self._validated_file_sha256 = {
            path: sha256_hex(path.read_bytes())
            for path in self._immutable_input_paths()
        }

    def validate_controller_binding(
        self,
        *,
        gateway_compose_file: Path,
        gateway_nginx_config: Path,
        gateway_active_include: Path,
        stable_origin: str,
        tls_ca_file: Path,
    ) -> None:
        if (
            gateway_compose_file.resolve()
            != self._config.gateway_compose_file.resolve()
            or gateway_nginx_config.resolve()
            != self._config.gateway_nginx_config.resolve()
            or gateway_active_include.resolve()
            != self._config.active_gateway_include.resolve()
            or stable_origin.rstrip("/") != self._config.stable_origin
            or tls_ca_file.resolve() != self._config.tls_ca_file.resolve()
        ):
            raise DeploymentToolError("deployment_controller_binding_mismatch")

    def run_locked_expand_migration(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self._validate_request_binding(request)
        self._compose(
            self._config.candidate,
            self._config.candidate.standby_environment_file,
            "--profile",
            "migration",
            "run",
            "--rm",
            "migrate",
            timeout_seconds=1800,
        )

    def start_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        self._compose(
            self._config.candidate,
            self._config.candidate.standby_environment_file,
            "up",
            "-d",
            *_PRODUCT_SERVICES,
            timeout_seconds=300,
        )

    def assert_candidate_ready(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        candidate = self._config.candidate
        probes = (
            (
                "api",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8000/readyz",
                    role="api",
                    activation="STANDBY",
                ),
            ),
            (
                "run-executor",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8001/readyz",
                    role="run_executor",
                    activation="STANDBY",
                ),
            ),
            (
                "knowledge-worker",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8002/readyz",
                    role="knowledge_worker",
                    activation="STANDBY",
                ),
            ),
            (
                "dashboard",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="dashboard",
                ),
            ),
            (
                "operator-chat",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="operator-chat",
                ),
            ),
        )
        for service, script in probes:
            self._exec_python(candidate, service, script, timeout_seconds=30)

    def run_isolated_smoke(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        candidate = self._config.candidate
        probes = (
            (
                "api",
                self._status_probe_script(
                    url="http://127.0.0.1:8000/livez",
                    expected_key="status",
                    expected_value="alive",
                ),
            ),
            (
                "dashboard",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="dashboard",
                ),
            ),
            (
                "operator-chat",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="operator-chat",
                ),
            ),
        )
        for service, script in probes:
            self._exec_python(candidate, service, script, timeout_seconds=30)

    def _assert_candidate_soak_health(self) -> None:
        candidate = self._config.candidate
        probes = (
            (
                "api",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8000/readyz",
                    role="api",
                    activation="STANDBY",
                ),
            ),
            (
                "run-executor",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8001/readyz",
                    role="run_executor",
                    activation="ACTIVE",
                ),
            ),
            (
                "knowledge-worker",
                self._identity_probe_script(
                    candidate,
                    url="http://127.0.0.1:8002/readyz",
                    role="knowledge_worker",
                    activation="ACTIVE",
                ),
            ),
            (
                "dashboard",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="dashboard",
                ),
            ),
            (
                "operator-chat",
                self._static_probe_script(
                    url=(
                        "http://127.0.0.1:8080/"
                        ".well-known/proof-agent-asset-digest"
                    ),
                    surface="operator-chat",
                ),
            ),
        )
        for service, script in probes:
            self._exec_python(
                candidate,
                service,
                script,
                timeout_seconds=30,
                active=True,
            )

    def queue_contracts_are_bidirectionally_compatible(
        self, request: BlueGreenDeploymentRequest
    ) -> bool:
        self._validate_request_binding(request)
        validations = (
            (
                self._config.candidate.image_reference,
                self._config.old_api_queue_fixtures,
            ),
            (
                self._config.old.image_reference,
                self._config.candidate_api_queue_fixtures,
            ),
        )
        compatible: list[bool] = []
        for image, fixture_path in validations:
            stdout = self._run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "--network",
                    "none",
                    "--read-only",
                    "--cap-drop",
                    "ALL",
                    "--security-opt",
                    "no-new-privileges",
                    "--user",
                    "10001:10001",
                    image,
                    "python",
                    "-c",
                    _QUEUE_CONTRACT_VALIDATOR,
                ],
                timeout_seconds=60,
                stdin=fixture_path.read_bytes(),
            )
            compatible.append(self._parse_queue_contract_result(stdout))
        return all(compatible)

    def pause_admission(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        if not request.admission_pause_authorized:
            raise DeploymentActionError("admission_pause_not_authorized")
        self._set_admission(paused=True)

    def resume_admission(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        self._set_admission(paused=False)

    def begin_old_workers_draining(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self._validate_request_binding(request)
        self._signal_workers(self._config.old, signal_name="SIGUSR1")
        self._wait_worker_epoch(
            self._config.old,
            expected_epoch=request.old_activation_epoch,
            expected_state="draining",
            timeout_seconds=30,
        )

    def wait_old_claims_zero(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        timeout_seconds: int,
    ) -> bool:
        self._validate_request_binding(request)
        return self._wait_claims_zero(
            self._config.old,
            timeout_seconds=timeout_seconds,
            expected_timeout=request.drain_timeout_seconds,
        )

    def restore_old_workers_active(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        expected_epoch: int,
    ) -> None:
        self._validate_request_binding(request)
        if expected_epoch != request.old_activation_epoch:
            raise DeploymentActionError("old_resume_epoch_mismatch")
        self._signal_workers(self._config.old, signal_name="SIGUSR2")
        self._wait_worker_epoch(
            self._config.old,
            expected_epoch=expected_epoch,
            expected_state="active",
            timeout_seconds=30,
        )

    def keep_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None:
        self.assert_candidate_ready(request)

    def activate_candidate_workers(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        previous_epoch: int,
    ) -> int:
        self._validate_request_binding(request)
        if previous_epoch != request.old_activation_epoch:
            raise DeploymentActionError("candidate_activation_epoch_mismatch")
        self._compose(
            self._config.old,
            self._config.old.active_environment_file,
            "stop",
            "--timeout",
            "30",
            *_WORKER_SERVICES,
            timeout_seconds=60,
        )
        self._compose(
            self._config.candidate,
            self._config.candidate.active_environment_file,
            "up",
            "-d",
            "--force-recreate",
            *_WORKER_SERVICES,
            timeout_seconds=300,
        )
        epoch = previous_epoch + 1
        self._wait_worker_epoch(
            self._config.candidate,
            expected_epoch=epoch,
            expected_state="active",
            timeout_seconds=30,
        )
        return epoch

    def run_stable_origin_smoke(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        session, smoke = self._load_stable_smoke_inputs()
        expected_generation = request.active_gateway_generation + 1

        login = self._stable_client.request("GET", "/api/auth/login")
        self._require_stable_route(
            login,
            request=request,
            expected_generation=expected_generation,
        )
        location = login.headers.get("location", "")
        parsed_location = urlsplit(location)
        if (
            login.status != 307
            or parsed_location.scheme != "https"
            or not parsed_location.netloc
            or parsed_location.username is not None
            or parsed_location.password is not None
        ):
            raise DeploymentActionError("stable_smoke_oidc_login_failed")

        cookie = session.session_cookie
        session_response = self._stable_client.request(
            "GET",
            "/api/auth/session",
            headers={"Cookie": f"proof_agent_session={cookie}"},
        )
        self._require_stable_route(
            session_response,
            request=request,
            expected_generation=expected_generation,
        )
        if session_response.status != 200:
            raise DeploymentActionError("stable_smoke_session_failed")
        cookie = self._rotated_session_cookie(session_response, fallback=cookie)
        session_payload = self._json_response(session_response)
        csrf_token = session_payload.get("csrf_token")
        permissions = session_payload.get("effective_permissions")
        if (
            not isinstance(csrf_token, str)
            or len(csrf_token) < 32
            or not isinstance(permissions, list)
            or not {"run.submit", "run.view"}.issubset(permissions)
        ):
            raise DeploymentActionError("stable_smoke_session_invalid")

        submission = self._stable_client.request(
            "POST",
            "/api/runs",
            headers={
                "Cookie": f"proof_agent_session={cookie}",
                "Origin": self._config.stable_origin,
                "X-CSRF-Token": csrf_token,
                "Idempotency-Key": (
                    f"deployment-smoke-{request.binding.binding_sha256[:32]}-"
                    f"{expected_generation}"
                ),
                "Content-Type": "application/json",
            },
            body=json.dumps(
                {
                    "agent_id": smoke.agent_id,
                    "question": smoke.question,
                    "conversation_id": None,
                    "allow_untrusted_web_supplement": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8"),
        )
        self._require_stable_route(
            submission,
            request=request,
            expected_generation=expected_generation,
        )
        admission_paused = self._config.gateway_admission_include.read_bytes() == (
            self._render_admission_include(paused=True)
        )
        if admission_paused:
            if submission.status != 503:
                raise DeploymentActionError("stable_smoke_admission_pause_failed")
            return
        if submission.status != 202:
            raise DeploymentActionError("stable_smoke_submission_failed")
        submitted = self._json_response(submission)
        run_id = submitted.get("run_id")
        if not isinstance(run_id, str) or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            run_id,
        ) is None:
            raise DeploymentActionError("stable_smoke_run_id_invalid")

        auth_headers = {"Cookie": f"proof_agent_session={cookie}"}
        event = self._stable_client.first_sse_event(
            f"/api/runs/{run_id}/progress",
            headers=auth_headers,
        )
        self._require_stable_route(
            event,
            request=request,
            expected_generation=expected_generation,
        )
        if (
            event.status != 200
            or not event.headers.get("content-type", "").startswith(
                "text/event-stream"
            )
            or b"event: state_snapshot" not in event.body
        ):
            raise DeploymentActionError("stable_smoke_sse_failed")

        terminal = self._wait_stable_run_terminal(
            request,
            run_id=run_id,
            headers=auth_headers,
            expected_generation=expected_generation,
        )
        artifact_manifest_id = terminal.get("artifact_manifest_id")
        if (
            terminal.get("state") != "succeeded"
            or terminal.get("result_available") is not True
            or not isinstance(artifact_manifest_id, str)
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                artifact_manifest_id,
            )
            is None
        ):
            raise DeploymentActionError("stable_smoke_terminal_failed")
        receipt = self._stable_client.request(
            "GET",
            f"/api/runs/{run_id}/receipt",
            headers=auth_headers,
        )
        self._require_stable_route(
            receipt,
            request=request,
            expected_generation=expected_generation,
        )
        receipt_payload = self._json_response(receipt)
        receipt_markdown = receipt_payload.get("receipt_markdown")
        if (
            receipt.status != 200
            or receipt_payload.get("run_id") != run_id
            or not isinstance(receipt_markdown, str)
            or not receipt_markdown.strip()
        ):
            raise DeploymentActionError("stable_smoke_s3_result_failed")

    def soak(self, request: BlueGreenDeploymentRequest, *, seconds: int) -> None:
        self._validate_request_binding(request)
        if seconds != request.soak_seconds or seconds != 1800:
            raise DeploymentActionError("compose_soak_duration_invalid")
        for _interval in range(30):
            self._assert_candidate_soak_health()
            self._sleeper(60.0)
        self._assert_candidate_soak_health()

    def stop_old_compute(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        self._compose(
            self._config.old,
            self._config.old.active_environment_file,
            "stop",
            "--timeout",
            "30",
            "api",
            "dashboard",
            "operator-chat",
            timeout_seconds=60,
        )

    def assert_old_api_ready(self, request: BlueGreenDeploymentRequest) -> None:
        self._validate_request_binding(request)
        self._exec_python(
            self._config.old,
            "api",
            self._identity_probe_script(
                self._config.old,
                url="http://127.0.0.1:8000/readyz",
                role="api",
                activation="ACTIVE",
            ),
            timeout_seconds=30,
            active=True,
        )

    def begin_candidate_workers_draining(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self._validate_request_binding(request)
        self._signal_workers(self._config.candidate, signal_name="SIGUSR1")
        self._wait_worker_epoch(
            self._config.candidate,
            expected_epoch=request.old_activation_epoch + 1,
            expected_state="draining",
            timeout_seconds=30,
        )

    def wait_candidate_claims_zero(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        timeout_seconds: int,
    ) -> bool:
        self._validate_request_binding(request)
        return self._wait_claims_zero(
            self._config.candidate,
            timeout_seconds=timeout_seconds,
            expected_timeout=request.drain_timeout_seconds,
        )

    def fence_candidate_and_wait_for_lease_expiry(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self._validate_request_binding(request)
        self._compose(
            self._config.candidate,
            self._config.candidate.active_environment_file,
            "stop",
            "--timeout",
            "0",
            *_WORKER_SERVICES,
            timeout_seconds=30,
        )
        self._sleeper(float(self._config.worker_lease_expiry_wait_seconds))

    def activate_old_workers(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        previous_epoch: int,
    ) -> int:
        self._validate_request_binding(request)
        if previous_epoch < request.old_activation_epoch:
            raise DeploymentActionError("old_activation_epoch_mismatch")
        self._compose(
            self._config.candidate,
            self._config.candidate.active_environment_file,
            "stop",
            "--timeout",
            "30",
            *_WORKER_SERVICES,
            timeout_seconds=60,
        )
        self._compose(
            self._config.old,
            self._config.old.active_environment_file,
            "up",
            "-d",
            "--force-recreate",
            *_WORKER_SERVICES,
            timeout_seconds=300,
        )
        epoch = previous_epoch + 1
        self._wait_worker_epoch(
            self._config.old,
            expected_epoch=epoch,
            expected_state="active",
            timeout_seconds=30,
        )
        return epoch

    def fail_lost_candidate_attempts(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self._validate_request_binding(request)
        stdout = self._exec_python(
            self._config.old,
            "api",
            self._fail_lost_attempts_script(),
            timeout_seconds=60,
            active=True,
        )
        payload = self._parse_bounded_json(stdout)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"failed_attempts"}
            or not isinstance(payload["failed_attempts"], int)
            or isinstance(payload["failed_attempts"], bool)
            or payload["failed_attempts"] < 0
        ):
            raise DeploymentActionError("lost_attempt_result_invalid")

    def _validate_request_binding(self, request: BlueGreenDeploymentRequest) -> None:
        if (
            request.old_slot is not self._config.old.slot
            or request.candidate_slot is not self._config.candidate.slot
            or request.binding.release_id != self._config.candidate.release_id
            or request.binding.image_reference != self._config.candidate.image_reference
            or request.binding.schema_revision != self._config.candidate.schema_revision
        ):
            raise DeploymentActionError("compose_request_binding_mismatch")
        self._validate_immutable_inputs()

    def _immutable_input_paths(self) -> tuple[Path, ...]:
        return (
            self._config.slot_compose_file,
            self._config.deployment_compatibility_manifest,
            self._config.migration_set_file,
            self._config.vault_compatibility_file,
            self._config.gateway_compose_file,
            self._config.gateway_nginx_config,
            self._config.tls_ca_file,
            self._config.stable_smoke_session_file,
            self._config.stable_smoke_request_file,
            self._config.old.active_environment_file,
            self._config.old.standby_environment_file,
            self._config.candidate.active_environment_file,
            self._config.candidate.standby_environment_file,
            self._config.old_api_queue_fixtures,
            self._config.candidate_api_queue_fixtures,
        )

    def _validate_immutable_inputs(self) -> None:
        if self._validated_file_sha256 is None:
            return
        try:
            unchanged = all(
                path.is_file() and sha256_hex(path.read_bytes()) == expected
                for path, expected in self._validated_file_sha256.items()
            )
        except OSError as exc:
            raise DeploymentActionError("compose_driver_input_changed") from exc
        if not unchanged:
            raise DeploymentActionError("compose_driver_input_changed")

    @staticmethod
    def _require_files(*paths: Path) -> None:
        if any(not path.is_file() for path in paths):
            raise DeploymentActionError("compose_driver_file_missing")

    @staticmethod
    def _read_environment(path: Path) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export ") or "=" not in line:
                raise DeploymentActionError("compose_environment_invalid")
            key, value = line.split("=", 1)
            if (
                not key
                or key in values
                or key.strip() != key
                or value.strip() != value
                or "\x00" in value
            ):
                raise DeploymentActionError("compose_environment_invalid")
            values[key] = value
        return values

    def _validate_environment(
        self,
        slot: ComposeSlotConfig,
        path: Path,
        *,
        activation: Literal["active", "standby"],
    ) -> None:
        values = self._read_environment(path)
        expected = {
            "PROOF_AGENT_MODE": "production",
            "PROOF_AGENT_RELEASE_ID": slot.release_id,
            "PROOF_AGENT_RELEASE_SCHEMA": slot.schema_revision,
            "PROOF_AGENT_IMAGE_DIGEST": slot.image_digest,
            "PROOF_AGENT_DEPLOYMENT_SLOT": slot.slot.value,
            "PROOF_AGENT_ACTIVATION_STATE": activation,
            "PROOF_AGENT_DEPLOYMENT_COMPATIBILITY_MANIFEST": (
                "/run/configs/deployment-compatibility-manifest.json"
            ),
            "PROOF_AGENT_EXECUTOR_ID": slot.run_executor_owner_id,
            "PROOF_AGENT_KNOWLEDGE_WORKER_ID": slot.knowledge_worker_owner_id,
        }
        if any(values.get(key) != value for key, value in expected.items()):
            raise DeploymentActionError("compose_environment_binding_mismatch")

    def _validate_active_gateway(self, request: BlueGreenDeploymentRequest) -> None:
        include = self._config.active_gateway_include.read_text(encoding="utf-8")
        required = (
            f"# routing-generation: {request.active_gateway_generation}",
            f'default "{request.old_slot.value}";',
            f"server {request.old_slot.value}-api:8000;",
            f"server {request.old_slot.value}-dashboard:8080;",
            f"server {request.old_slot.value}-operator-chat:8080;",
        )
        if any(include.count(item) != 1 for item in required):
            raise DeploymentActionError("gateway_active_state_mismatch")

    def _compose_environment(
        self,
        slot: ComposeSlotConfig,
        environment_file: Path,
    ) -> dict[str, str]:
        return {
            "SLOT": slot.slot.value,
            "SLOT_NUMBER": str(slot.slot_number),
            "SLOT_ENV_FILE": str(environment_file.resolve()),
            "PROOF_AGENT_IMAGE": slot.image_reference,
            "PROOF_AGENT_RELEASE_SCHEMA": slot.schema_revision,
            "VAULT_COMPATIBILITY_FILE": str(
                self._config.vault_compatibility_file.resolve()
            ),
            "DEPLOYMENT_COMPATIBILITY_FILE": str(
                self._config.deployment_compatibility_manifest.resolve()
            ),
            "VAULT_AGENT_TOKEN_SECRET": self._config.vault_agent_token_secret,
        }

    def _compose(
        self,
        slot: ComposeSlotConfig,
        environment_file: Path,
        *args: str,
        timeout_seconds: int,
        stdin: bytes | None = None,
    ) -> str:
        return self._run(
            [
                "docker",
                "compose",
                "--project-name",
                slot.project_name,
                "-f",
                str(self._config.slot_compose_file),
                *args,
            ],
            timeout_seconds=timeout_seconds,
            stdin=stdin,
            env=self._compose_environment(slot, environment_file),
        )

    def _exec_python(
        self,
        slot: ComposeSlotConfig,
        service: str,
        script: str,
        *,
        timeout_seconds: int,
        active: bool = False,
    ) -> str:
        environment_file = (
            slot.active_environment_file
            if active
            else slot.standby_environment_file
        )
        return self._compose(
            slot,
            environment_file,
            "exec",
            "-T",
            service,
            "python",
            "-c",
            script,
            timeout_seconds=timeout_seconds,
        )

    def _signal_workers(
        self,
        slot: ComposeSlotConfig,
        *,
        signal_name: Literal["SIGUSR1", "SIGUSR2"],
    ) -> None:
        self._compose(
            slot,
            slot.active_environment_file,
            "kill",
            "--signal",
            signal_name,
            *_WORKER_SERVICES,
            timeout_seconds=30,
        )

    @staticmethod
    def _render_admission_include(*, paused: bool) -> bytes:
        blocked = "1" if paused else "0"
        return (
            "# Deployment-controller-owned file; do not edit in place.\n"
            'map "$request_method:$uri" $proofagent_run_admission_blocked {\n'
            '    default "0";\n'
            f'    "POST:/api/runs" "{blocked}";\n'
            "}\n"
        ).encode("utf-8")

    def _set_admission(self, *, paused: bool) -> None:
        active = self._config.gateway_admission_include
        if not active.is_file():
            raise DeploymentActionError("gateway_admission_include_missing")
        old = active.read_bytes()
        expected_old = self._render_admission_include(paused=not paused)
        candidate = self._render_admission_include(paused=paused)
        if old == candidate:
            self._admission_probe(paused)
            return
        if old != expected_old:
            raise DeploymentActionError("gateway_admission_state_mismatch")
        mode = stat.S_IMODE(active.stat().st_mode)
        candidate_path = self._write_gateway_temp(
            active,
            candidate,
            mode=mode,
        )
        replaced = False
        try:
            self._validate_admission_candidate(candidate_path)
            os.replace(candidate_path, active)
            replaced = True
            self._fsync_directory(active.parent)
            try:
                self._reload_gateway()
                self._admission_probe(paused)
            except Exception as exc:
                self._restore_admission(old, mode=mode, paused=not paused)
                raise DeploymentActionError(
                    "gateway_admission_verification_failed"
                ) from exc
        finally:
            if not replaced:
                candidate_path.unlink(missing_ok=True)

    def _validate_admission_candidate(self, candidate_path: Path) -> None:
        nginx = self._config.gateway_nginx_config.read_text(encoding="utf-8")
        if nginx.count(_ADMISSION_INCLUDE_DIRECTIVE) != 1:
            raise DeploymentActionError("gateway_admission_directive_invalid")
        container_candidate = (
            f"/etc/nginx/proofagent/{candidate_path.name}"
        )
        candidate_nginx = nginx.replace(
            _ADMISSION_INCLUDE_DIRECTIVE,
            f"include {container_candidate};",
        ).encode("utf-8")
        nginx_path = self._write_gateway_temp(
            self._config.gateway_nginx_config,
            candidate_nginx,
            mode=0o644,
        )
        try:
            self._run(
                [
                    "docker",
                    "exec",
                    self._gateway_container_id(),
                    "nginx",
                    "-t",
                    "-c",
                    f"/etc/nginx/proofagent/{nginx_path.name}",
                ],
                timeout_seconds=30,
            )
        finally:
            nginx_path.unlink(missing_ok=True)

    def _restore_admission(
        self,
        content: bytes,
        *,
        mode: int,
        paused: bool,
    ) -> None:
        active = self._config.gateway_admission_include
        restore = self._write_gateway_temp(active, content, mode=mode)
        try:
            os.replace(restore, active)
            self._fsync_directory(active.parent)
            self._reload_gateway()
            self._admission_probe(paused)
        except Exception as exc:
            restore.unlink(missing_ok=True)
            raise DeploymentActionError("gateway_admission_restore_failed") from exc

    @staticmethod
    def _write_gateway_temp(active: Path, content: bytes, *, mode: int) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{active.name}.",
            suffix=".tmp",
            dir=active.parent,
        )
        path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(mode)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _gateway_container_id(self) -> str:
        container_id = self._run(
            [
                "docker",
                "compose",
                "-f",
                str(self._config.gateway_compose_file),
                "ps",
                "-q",
                "gateway",
            ],
            timeout_seconds=30,
        ).strip()
        if not container_id or "\n" in container_id:
            raise DeploymentActionError("gateway_container_not_running")
        return container_id

    def _reload_gateway(self) -> None:
        self._run(
            [
                "docker",
                "exec",
                self._gateway_container_id(),
                "nginx",
                "-s",
                "reload",
            ],
            timeout_seconds=30,
        )

    def _probe_admission_endpoint(self, paused: bool) -> None:
        parsed = urlsplit(self._config.stable_origin)
        assert parsed.hostname is not None
        try:
            context = ssl.create_default_context(
                cafile=str(self._config.tls_ca_file)
            )
            connection = HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                timeout=10,
                context=context,
            )
            try:
                connection.request(
                    "POST",
                    "/api/runs",
                    body=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "Cache-Control": "no-cache",
                    },
                )
                response = connection.getresponse()
                status = response.status
                response.read(4096)
            finally:
                connection.close()
        except (HTTPException, OSError, ssl.SSLError) as exc:
            raise DeploymentActionError("gateway_admission_probe_failed") from exc
        expected = {503} if paused else {400, 401, 403, 415, 422}
        if status not in expected:
            raise DeploymentActionError("gateway_admission_probe_failed")

    def _load_stable_smoke_inputs(
        self,
    ) -> tuple[StableSmokeSession, StableSmokeRequest]:
        session_path = self._config.stable_smoke_session_file
        if (
            session_path.is_symlink()
            or stat.S_IMODE(session_path.stat().st_mode) & 0o077
        ):
            raise DeploymentActionError("stable_smoke_session_permissions_invalid")
        try:
            session = TypeAdapter(StableSmokeSession).validate_python(
                self._read_strict_json(session_path)
            )
            smoke = TypeAdapter(StableSmokeRequest).validate_python(
                self._read_strict_json(self._config.stable_smoke_request_file)
            )
        except ValidationError as exc:
            raise DeploymentActionError("stable_smoke_input_invalid") from exc
        return session, smoke

    @staticmethod
    def _read_strict_json(path: Path) -> object:
        try:
            raw = path.read_text(encoding="utf-8")
            reject_duplicate_json_keys(raw)
            return json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise DeploymentActionError("compose_driver_json_invalid") from exc

    @staticmethod
    def _json_response(response: StableOriginResponse) -> dict[str, object]:
        try:
            payload = json.loads(response.body)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise DeploymentActionError("stable_smoke_response_invalid") from exc
        if not isinstance(payload, dict):
            raise DeploymentActionError("stable_smoke_response_invalid")
        return payload

    @staticmethod
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
            raise DeploymentActionError("stable_smoke_session_cookie_invalid") from exc
        morsel = cookies.get("proof_agent_session")
        if (
            morsel is None
            or not 32 <= len(morsel.value) <= 512
            or re.fullmatch(r"[A-Za-z0-9_-]+", morsel.value) is None
        ):
            raise DeploymentActionError("stable_smoke_session_cookie_invalid")
        return morsel.value

    @staticmethod
    def _require_stable_route(
        response: StableOriginResponse,
        *,
        request: BlueGreenDeploymentRequest,
        expected_generation: int,
    ) -> None:
        if (
            response.headers.get("x-proofagent-routing-generation")
            != str(expected_generation)
            or response.headers.get("x-proofagent-routing-slot")
            != request.candidate_slot.value
        ):
            raise DeploymentActionError("stable_smoke_route_marker_invalid")

    def _wait_stable_run_terminal(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        run_id: str,
        headers: Mapping[str, str],
        expected_generation: int,
    ) -> dict[str, object]:
        timeout = self._config.stable_smoke_timeout_seconds
        deadline = self._now() + timedelta(seconds=timeout)
        max_polls = (timeout + 1) // 2 + 1
        terminal_states = {"succeeded", "failed", "timed_out", "cancelled"}
        for poll_number in range(max_polls):
            response = self._stable_client.request(
                "GET",
                f"/api/runs/{run_id}",
                headers=headers,
            )
            self._require_stable_route(
                response,
                request=request,
                expected_generation=expected_generation,
            )
            if response.status != 200:
                raise DeploymentActionError("stable_smoke_run_poll_failed")
            payload = self._json_response(response)
            state = payload.get("state")
            if not isinstance(state, str):
                raise DeploymentActionError("stable_smoke_run_poll_invalid")
            if state in terminal_states:
                return payload
            if poll_number + 1 >= max_polls or self._now() >= deadline:
                break
            self._sleeper(2.0)
        raise DeploymentActionError("stable_smoke_run_timeout")

    def _wait_claims_zero(
        self,
        slot: ComposeSlotConfig,
        *,
        timeout_seconds: int,
        expected_timeout: int,
    ) -> bool:
        if timeout_seconds != expected_timeout or not 1 <= timeout_seconds <= 150:
            raise DeploymentActionError("claim_drain_timeout_invalid")
        deadline = self._now() + timedelta(seconds=timeout_seconds)
        max_polls = (timeout_seconds + 1) // 2 + 1
        for poll_number in range(max_polls):
            stdout = self._exec_python(
                slot,
                "api",
                self._claim_count_script(slot),
                timeout_seconds=15,
                active=True,
            )
            run_attempts, knowledge_jobs = self._parse_claim_counts(stdout)
            if run_attempts == 0 and knowledge_jobs == 0:
                return True
            if poll_number + 1 >= max_polls or self._now() >= deadline:
                return False
            self._sleeper(2.0)
        return False

    @staticmethod
    def _claim_count_script(slot: ComposeSlotConfig) -> str:
        return f"""\
import json
import os
import sqlalchemy as sa
from proof_agent.capabilities.persistence.postgres.database import create_postgres_engine
from proof_agent.capabilities.persistence.postgres.schema import hybrid_ingestion_jobs, run_attempts

engine = create_postgres_engine(os.environ["PROOF_AGENT_POSTGRES_DSN"])
with engine.connect() as connection:
    run_count = connection.execute(
        sa.select(sa.func.count()).select_from(run_attempts).where(
            run_attempts.c.state.in_(("running", "finalizing", "cancel_requested")),
            run_attempts.c.executor_id == {slot.run_executor_owner_id!r},
        )
    ).scalar_one()
    knowledge_count = connection.execute(
        sa.select(sa.func.count()).select_from(hybrid_ingestion_jobs).where(
            hybrid_ingestion_jobs.c.state == "CLAIMED",
            hybrid_ingestion_jobs.c.worker_id == {slot.knowledge_worker_owner_id!r},
        )
    ).scalar_one()
print(json.dumps({{"run_attempts": int(run_count), "knowledge_jobs": int(knowledge_count)}}, separators=(",", ":"), sort_keys=True))
"""

    @staticmethod
    def _parse_claim_counts(stdout: str) -> tuple[int, int]:
        payload = DockerComposeBlueGreenOperations._parse_bounded_json(stdout)
        if not isinstance(payload, dict) or set(payload) != {
            "run_attempts",
            "knowledge_jobs",
        }:
            raise DeploymentActionError("claim_count_result_invalid")
        counts = (payload["run_attempts"], payload["knowledge_jobs"])
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in counts
        ):
            raise DeploymentActionError("claim_count_result_invalid")
        return counts

    def _wait_worker_epoch(
        self,
        slot: ComposeSlotConfig,
        *,
        expected_epoch: int,
        expected_state: Literal["active", "draining"],
        timeout_seconds: int,
    ) -> None:
        if expected_epoch < 0 or not 1 <= timeout_seconds <= 60:
            raise DeploymentActionError("worker_epoch_wait_invalid")
        deadline = self._now() + timedelta(seconds=timeout_seconds)
        max_polls = (timeout_seconds + 1) // 2 + 1
        for poll_number in range(max_polls):
            stdout = self._exec_python(
                slot,
                "api",
                self._worker_epoch_script(slot, expected_state=expected_state),
                timeout_seconds=15,
                active=True,
            )
            if self._parse_worker_epoch(stdout, expected_epoch=expected_epoch):
                return
            if poll_number + 1 >= max_polls or self._now() >= deadline:
                break
            self._sleeper(2.0)
        raise DeploymentActionError("worker_epoch_state_mismatch")

    @staticmethod
    def _worker_epoch_script(
        slot: ComposeSlotConfig,
        *,
        expected_state: Literal["active", "draining"] = "active",
    ) -> str:
        state_member = "ACTIVE" if expected_state == "active" else "DRAINING"
        return f"""\
import json
import os
from datetime import UTC, datetime
from proof_agent.capabilities.persistence.postgres.database import create_postgres_engine
from proof_agent.capabilities.persistence.postgres.worker_role_repository import PostgresWorkerRoleRepository
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.contracts.worker_roles import ProductionWorkerRole

repository = PostgresWorkerRoleRepository(create_postgres_engine(os.environ["PROOF_AGENT_POSTGRES_DSN"]))
now = datetime.now(UTC)
expected = {{
    ProductionWorkerRole.RUN_EXECUTOR: ({slot.slot_number}, {slot.run_executor_owner_id!r}),
    ProductionWorkerRole.KNOWLEDGE_WORKER: ({slot.slot_number}, {slot.knowledge_worker_owner_id!r}),
}}
rows = {{role: repository.get(role) for role in expected}}
ready = all(
    row.state is RoleActivationState.{state_member}
    and row.slot == expected[role][0]
    and row.owner_id == expected[role][1]
    and row.is_live(at=now)
    for role, row in rows.items()
)
print(json.dumps({{
    "ready": ready,
    "run_executor": rows[ProductionWorkerRole.RUN_EXECUTOR].activation_epoch,
    "knowledge_worker": rows[ProductionWorkerRole.KNOWLEDGE_WORKER].activation_epoch,
}}, separators=(",", ":"), sort_keys=True))
"""

    @staticmethod
    def _parse_worker_epoch(stdout: str, *, expected_epoch: int) -> bool:
        payload = DockerComposeBlueGreenOperations._parse_bounded_json(stdout)
        if not isinstance(payload, dict) or set(payload) != {
            "ready",
            "run_executor",
            "knowledge_worker",
        }:
            raise DeploymentActionError("worker_epoch_result_invalid")
        epochs = (payload["run_executor"], payload["knowledge_worker"])
        if (
            not isinstance(payload["ready"], bool)
            or any(
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                for value in epochs
            )
        ):
            raise DeploymentActionError("worker_epoch_result_invalid")
        return bool(payload["ready"] and epochs == (expected_epoch, expected_epoch))

    @staticmethod
    def _fail_lost_attempts_script() -> str:
        return """\
import json
import os
from datetime import UTC, datetime
from proof_agent.capabilities.persistence.postgres.database import create_postgres_engine
from proof_agent.capabilities.persistence.postgres.run_queue_repository import PostgresRunQueueRepository

repository = PostgresRunQueueRepository(create_postgres_engine(os.environ["PROOF_AGENT_POSTGRES_DSN"]))
failed = repository.reap_expired_leases(now=datetime.now(UTC))
print(json.dumps({"failed_attempts": failed}, separators=(",", ":"), sort_keys=True))
"""

    @staticmethod
    def _identity_probe_script(
        slot: ComposeSlotConfig,
        *,
        url: str,
        role: str,
        activation: Literal["ACTIVE", "STANDBY"],
    ) -> str:
        expected = json.dumps(
            {
                "status": "ready",
                "release_id": slot.release_id,
                "image_digest": slot.image_digest,
                "deployment_slot": slot.slot.value,
                "role": role,
                "activation_state": activation,
                "schema_revision": slot.schema_revision,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        return (
            "import json,urllib.request;"
            f"p=json.load(urllib.request.urlopen({url!r},timeout=5));"
            f"e=json.loads({expected!r});"
            "actual={k:(p.get('schema',{}).get('revision') if "
            "k=='schema_revision' else p.get(k)) for k in e};"
            "raise_system_exit=0 if actual==e else 1;"
            "__import__('sys').exit(raise_system_exit)"
        )

    @staticmethod
    def _static_probe_script(*, url: str, surface: str) -> str:
        return (
            "import json,re,sys,urllib.request;"
            f"p=json.load(urllib.request.urlopen({url!r},timeout=5));"
            f"ok=p.get('surface')=={surface!r} and "
            "isinstance(p.get('sha256'),str) and "
            "re.fullmatch('[0-9a-f]{64}',p['sha256']) is not None;"
            "sys.exit(0 if ok else 1)"
        )

    @staticmethod
    def _status_probe_script(
        *,
        url: str,
        expected_key: str,
        expected_value: str,
    ) -> str:
        return (
            "import json,sys,urllib.request;"
            f"p=json.load(urllib.request.urlopen({url!r},timeout=5));"
            f"sys.exit(0 if p.get({expected_key!r})=={expected_value!r} else 1)"
        )

    @staticmethod
    def _parse_queue_contract_result(stdout: str) -> bool:
        payload = DockerComposeBlueGreenOperations._parse_bounded_json(stdout)
        if (
            not isinstance(payload, dict)
            or set(payload) != {"compatible", "count"}
            or not isinstance(payload["compatible"], bool)
            or not isinstance(payload["count"], int)
            or isinstance(payload["count"], bool)
            or payload["count"] < 0
            or (payload["compatible"] and payload["count"] < 1)
        ):
            raise DeploymentActionError("queue_contract_result_invalid")
        return payload["compatible"]

    @staticmethod
    def _parse_bounded_json(stdout: str) -> object:
        if len(stdout.encode("utf-8")) > 4096:
            raise DeploymentActionError("compose_command_result_invalid")
        try:
            return json.loads(stdout)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise DeploymentActionError("compose_command_result_invalid") from exc

    def _run(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int,
        stdin: bytes | None = None,
        env: Mapping[str, str] | None = None,
    ) -> str:
        try:
            return self._runner.run(
                argv,
                timeout_seconds=timeout_seconds,
                stdin=stdin,
                env=env,
            ).stdout
        except DeploymentToolError as exc:
            raise DeploymentActionError("compose_command_failed") from exc

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise DeploymentActionError("compose_driver_clock_invalid")
        return value


__all__ = [
    "BUILT_IN_DRIVER_NAME",
    "ComposeSlotConfig",
    "DockerComposeBlueGreenOperations",
    "DockerComposeDriverConfig",
    "StableOriginClient",
    "StableOriginResponse",
]
