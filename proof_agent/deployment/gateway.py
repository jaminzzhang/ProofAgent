"""Atomic Gateway configuration; command execution belongs to the deployment tool."""

from __future__ import annotations

from enum import StrEnum
import os
from pathlib import Path
import stat
import tempfile
from typing import Protocol

from pydantic import Field

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.deployment.state import DeploymentSlot
from proof_agent.release.digests import sha256_hex


class GatewaySurface(StrEnum):
    DASHBOARD = "dashboard"
    OPERATOR_CHAT = "operator_chat"
    API = "api"
    OIDC_CALLBACK = "oidc_callback"
    SSE = "sse"


class GatewayRouteObservation(StrictFrozenModel):
    surface: GatewaySurface
    generation: int = Field(ge=1)
    slot: DeploymentSlot


class GatewayRoutingGeneration(StrictFrozenModel):
    generation: int = Field(ge=1)
    slot: DeploymentSlot
    deployment_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    include_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class GatewaySwitcher(Protocol):
    def switch(
        self,
        *,
        target_slot: DeploymentSlot,
        binding_sha256: str,
        current_generation: int,
    ) -> GatewayRoutingGeneration: ...


class NginxGatewayControl(Protocol):
    """Deployment-tool boundary for nginx validation, reload and route probes."""

    def validate(self, candidate_include: Path) -> None: ...

    def reload(self) -> None: ...

    def observe_routes(self) -> tuple[GatewayRouteObservation, ...]: ...


class GatewaySwitchError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


def render_gateway_include(
    *,
    slot: DeploymentSlot,
    generation: int,
    deployment_binding_sha256: str,
) -> bytes:
    """Render all route targets and public generation markers as one include."""

    if generation < 1:
        raise ValueError("Gateway generation must be positive")
    if len(deployment_binding_sha256) != 64 or any(
        char not in "0123456789abcdef" for char in deployment_binding_sha256
    ):
        raise ValueError("Gateway deployment binding digest is invalid")
    rendered = f"""# Deployment-controller-owned file; do not edit in place.
# deployment-binding-sha256: {deployment_binding_sha256}
# routing-generation: {generation}
map $host $proofagent_routing_generation {{
    default "{generation}";
}}
map $host $proofagent_routing_slot {{
    default "{slot.value}";
}}

upstream proofagent_api {{
    server {slot.value}-api:8000;
    keepalive 32;
}}

upstream proofagent_dashboard {{
    server {slot.value}-dashboard:8080;
    keepalive 16;
}}

upstream proofagent_operator_chat {{
    server {slot.value}-operator-chat:8080;
    keepalive 16;
}}
"""
    return rendered.encode("utf-8")


class AtomicNginxGatewaySwitcher:
    """Validate a same-directory temp include, replace once, reload and verify."""

    def __init__(
        self,
        *,
        active_include: Path,
        control: NginxGatewayControl,
    ) -> None:
        self._active_include = active_include
        self._control = control

    def switch(
        self,
        *,
        target_slot: DeploymentSlot,
        binding_sha256: str,
        current_generation: int,
    ) -> GatewayRoutingGeneration:
        if not self._active_include.is_file():
            raise GatewaySwitchError("gateway_active_include_missing")
        generation = current_generation + 1
        candidate = render_gateway_include(
            slot=target_slot,
            generation=generation,
            deployment_binding_sha256=binding_sha256,
        )
        old = self._active_include.read_bytes()
        mode = stat.S_IMODE(self._active_include.stat().st_mode)
        candidate_path = self._write_temp(candidate, mode=mode)
        replaced = False
        try:
            try:
                self._control.validate(candidate_path)
            except Exception as exc:
                raise GatewaySwitchError("gateway_candidate_invalid") from exc
            os.replace(candidate_path, self._active_include)
            replaced = True
            self._fsync_parent()
            try:
                self._control.reload()
                observations = self._control.observe_routes()
                self._verify_observations(
                    observations,
                    slot=target_slot,
                    generation=generation,
                )
            except Exception as exc:
                self._restore(old, mode=mode)
                raise GatewaySwitchError(
                    "gateway_generation_verification_failed"
                ) from exc
        finally:
            if not replaced:
                candidate_path.unlink(missing_ok=True)
        return GatewayRoutingGeneration(
            generation=generation,
            slot=target_slot,
            deployment_binding_sha256=binding_sha256,
            include_sha256=sha256_hex(candidate),
        )

    def _restore(self, content: bytes, *, mode: int) -> None:
        restore_path = self._write_temp(content, mode=mode)
        try:
            os.replace(restore_path, self._active_include)
            self._fsync_parent()
            self._control.reload()
        except Exception as exc:
            restore_path.unlink(missing_ok=True)
            raise GatewaySwitchError("gateway_restore_failed") from exc

    def _write_temp(self, content: bytes, *, mode: int) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{self._active_include.name}.",
            suffix=".tmp",
            dir=self._active_include.parent,
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

    def _fsync_parent(self) -> None:
        descriptor = os.open(self._active_include.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _verify_observations(
        observations: tuple[GatewayRouteObservation, ...],
        *,
        slot: DeploymentSlot,
        generation: int,
    ) -> None:
        by_surface = {observation.surface: observation for observation in observations}
        if len(observations) != len(GatewaySurface) or set(by_surface) != set(
            GatewaySurface
        ):
            raise GatewaySwitchError("gateway_surface_set_mismatch")
        if any(
            observation.slot is not slot or observation.generation != generation
            for observation in observations
        ):
            raise GatewaySwitchError("gateway_mixed_routing_generation")


__all__ = [
    "AtomicNginxGatewaySwitcher",
    "GatewayRouteObservation",
    "GatewayRoutingGeneration",
    "GatewaySurface",
    "GatewaySwitchError",
    "GatewaySwitcher",
    "NginxGatewayControl",
    "render_gateway_include",
]
