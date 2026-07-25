#!/usr/bin/env python3
"""External Blue/Green deployment controller.

This tool is intentionally excluded from the production image. Environment-specific
Compose operations are supplied by a trusted installed entry point; this file owns
the shell-free command runner, nginx validation/reload/probes and durable result
journal boundary.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from http.client import HTTPException, HTTPSConnection
from importlib.metadata import entry_points
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
from typing import Protocol, cast
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from proof_agent.deployment.choreography import (
    BlueGreenChoreographer,
    BlueGreenOperations,
)
from proof_agent.deployment.gateway import (
    AtomicNginxGatewaySwitcher,
    GatewayRouteObservation,
    GatewaySurface,
    NginxGatewayControl,
)
from proof_agent.deployment.state import (
    BlueGreenDeploymentRequest,
    DeploymentOutcome,
    DeploymentSlot,
)
from proof_agent.release.digests import reject_duplicate_json_keys
from scripts.deployment.command_runner import (
    CommandResult as CommandResult,
    DeploymentCommandRunner,
    DeploymentToolError,
    SubprocessCommandRunner,
)


DRIVER_ENTRY_POINT_GROUP = "proof_agent.blue_green_deployment_drivers"
_INCLUDE_DIRECTIVE = "include /etc/nginx/proofagent/active-upstreams.conf;"
_CANDIDATE_INCLUDE = "/tmp/proofagent-candidate-upstreams.conf"
_CANDIDATE_NGINX = "/tmp/proofagent-candidate-nginx.conf"


class DockerNginxGatewayControl(NginxGatewayControl):
    """Validate inside the running immutable Gateway image and probe stable HTTPS."""

    def __init__(
        self,
        *,
        runner: DeploymentCommandRunner,
        compose_file: Path,
        nginx_config: Path,
        stable_origin: str,
        tls_ca_file: Path,
    ) -> None:
        parsed = urlsplit(stable_origin)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise DeploymentToolError("gateway_stable_origin_invalid")
        if not compose_file.is_file() or not nginx_config.is_file():
            raise DeploymentToolError("gateway_configuration_missing")
        if not tls_ca_file.is_file():
            raise DeploymentToolError("gateway_tls_ca_missing")
        self._runner = runner
        self._compose_file = compose_file
        self._nginx_config = nginx_config
        assert parsed.hostname is not None
        self._stable_host = parsed.hostname
        self._stable_port = parsed.port or 443
        self._ssl_context = ssl.create_default_context(cafile=str(tls_ca_file))

    def validate(self, candidate_include: Path) -> None:
        if candidate_include.parent != self._nginx_config.parent:
            raise DeploymentToolError("gateway_candidate_directory_mismatch")
        container_id = self._gateway_container_id()
        nginx = self._nginx_config.read_text(encoding="utf-8")
        if nginx.count(_INCLUDE_DIRECTIVE) != 1:
            raise DeploymentToolError("gateway_include_directive_invalid")
        candidate_nginx = nginx.replace(
            _INCLUDE_DIRECTIVE,
            f"include {_CANDIDATE_INCLUDE};",
        ).encode("utf-8")
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".proofagent-candidate-nginx.",
            suffix=".conf",
            dir=self._nginx_config.parent,
        )
        host_candidate_nginx = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(candidate_nginx)
                stream.flush()
                os.fsync(stream.fileno())
            host_candidate_nginx.chmod(0o644)
            self._runner.run(
                ["docker", "cp", str(candidate_include), f"{container_id}:{_CANDIDATE_INCLUDE}"],
                timeout_seconds=30,
            )
            self._runner.run(
                [
                    "docker",
                    "cp",
                    str(host_candidate_nginx),
                    f"{container_id}:{_CANDIDATE_NGINX}",
                ],
                timeout_seconds=30,
            )
            self._runner.run(
                [
                    "docker",
                    "exec",
                    container_id,
                    "nginx",
                    "-t",
                    "-c",
                    _CANDIDATE_NGINX,
                ],
                timeout_seconds=30,
            )
        finally:
            host_candidate_nginx.unlink(missing_ok=True)

    def reload(self) -> None:
        self._runner.run(
            ["docker", "exec", self._gateway_container_id(), "nginx", "-s", "reload"],
            timeout_seconds=30,
        )

    def observe_routes(self) -> tuple[GatewayRouteObservation, ...]:
        paths = {
            GatewaySurface.DASHBOARD: "/",
            GatewaySurface.OPERATOR_CHAT: "/operator/",
            GatewaySurface.API: "/api/readyz",
            GatewaySurface.OIDC_CALLBACK: "/api/auth/callback",
            GatewaySurface.SSE: "/api/runs/deployment-probe/progress",
        }
        observations: list[GatewayRouteObservation] = []
        for surface, path in paths.items():
            connection = HTTPSConnection(
                self._stable_host,
                self._stable_port,
                timeout=10,
                context=self._ssl_context,
            )
            try:
                connection.request("GET", path, headers={"Cache-Control": "no-cache"})
                response = connection.getresponse()
                generation_text = response.getheader(
                    "X-ProofAgent-Routing-Generation", ""
                )
                slot_text = response.getheader("X-ProofAgent-Routing-Slot", "")
                response.close()
            except (HTTPException, OSError) as exc:
                raise DeploymentToolError("gateway_route_probe_failed") from exc
            finally:
                connection.close()
            try:
                generation = int(generation_text)
                slot = DeploymentSlot(slot_text)
            except (TypeError, ValueError) as exc:
                raise DeploymentToolError("gateway_route_marker_invalid") from exc
            observations.append(
                GatewayRouteObservation(
                    surface=surface,
                    generation=generation,
                    slot=slot,
                )
            )
        return tuple(observations)

    def _gateway_container_id(self) -> str:
        result = self._runner.run(
            [
                "docker",
                "compose",
                "-f",
                str(self._compose_file),
                "ps",
                "-q",
                "gateway",
            ],
            timeout_seconds=30,
        )
        container_id = result.stdout.strip()
        if not container_id or "\n" in container_id:
            raise DeploymentToolError("gateway_container_not_running")
        return container_id


class DeploymentOperationsFactory(Protocol):
    def __call__(
        self,
        *,
        runner: DeploymentCommandRunner,
        config: Mapping[str, object],
    ) -> BlueGreenOperations: ...


def _read_json(path: Path) -> object:
    raw = path.read_text(encoding="utf-8")
    reject_duplicate_json_keys(raw)
    return json.loads(raw)


def _load_operations(
    *,
    driver_name: str,
    runner: DeploymentCommandRunner,
    config_path: Path,
) -> BlueGreenOperations:
    config_payload = _read_json(config_path)
    if not isinstance(config_payload, dict) or any(
        not isinstance(key, str) for key in config_payload
    ):
        raise DeploymentToolError("deployment_driver_config_invalid")
    if driver_name == "docker-compose-v1":
        from scripts.deployment.compose_driver import (
            DockerComposeBlueGreenOperations,
        )

        return DockerComposeBlueGreenOperations.from_mapping(
            config_payload,
            runner=runner,
        )
    matches = [
        point
        for point in entry_points(group=DRIVER_ENTRY_POINT_GROUP)
        if point.name == driver_name
    ]
    if len(matches) != 1:
        raise DeploymentToolError("deployment_driver_not_installed")
    factory = cast(DeploymentOperationsFactory, matches[0].load())
    return factory(runner=runner, config=config_payload)


def _write_journal(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Proof Agent fenced Blue/Green deploy")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--driver", required=True)
    parser.add_argument("--driver-config", type=Path, required=True)
    parser.add_argument("--gateway-compose", type=Path, required=True)
    parser.add_argument("--gateway-nginx-config", type=Path, required=True)
    parser.add_argument("--gateway-active-include", type=Path, required=True)
    parser.add_argument("--stable-origin", required=True)
    parser.add_argument("--tls-ca-file", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        request = TypeAdapter(BlueGreenDeploymentRequest).validate_python(
            _read_json(args.request)
        )
        runner = SubprocessCommandRunner()
        operations = _load_operations(
            driver_name=args.driver,
            runner=runner,
            config_path=args.driver_config,
        )
        validate_controller_binding = getattr(
            operations,
            "validate_controller_binding",
            None,
        )
        if callable(validate_controller_binding):
            validate_controller_binding(
                gateway_compose_file=args.gateway_compose,
                gateway_nginx_config=args.gateway_nginx_config,
                gateway_active_include=args.gateway_active_include,
                stable_origin=args.stable_origin,
                tls_ca_file=args.tls_ca_file,
            )
        gateway = AtomicNginxGatewaySwitcher(
            active_include=args.gateway_active_include,
            control=DockerNginxGatewayControl(
                runner=runner,
                compose_file=args.gateway_compose,
                nginx_config=args.gateway_nginx_config,
                stable_origin=args.stable_origin,
                tls_ca_file=args.tls_ca_file,
            ),
        )
        result = BlueGreenChoreographer(
            operations=operations,
            gateway=gateway,
        ).deploy(request)
        serialized = result.model_dump_json(indent=2).encode("utf-8") + b"\n"
        _write_journal(args.journal, serialized)
        sys.stdout.buffer.write(serialized)
        return {
            DeploymentOutcome.DEPLOYED: 0,
            DeploymentOutcome.ABORTED: 2,
            DeploymentOutcome.ABORT_FAILED: 4,
            DeploymentOutcome.ROLLED_BACK: 3,
            DeploymentOutcome.ROLLBACK_FAILED: 4,
        }[result.outcome]
    except (
        DeploymentToolError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        error_code = (
            exc.error_code
            if isinstance(exc, DeploymentToolError)
            else "deployment_request_invalid"
        )
        print(json.dumps({"error_code": error_code, "status": "failed"}, sort_keys=True))
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
