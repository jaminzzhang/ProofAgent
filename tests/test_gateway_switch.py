from __future__ import annotations

from pathlib import Path

import pytest

from proof_agent.deployment.gateway import (
    AtomicNginxGatewaySwitcher,
    GatewayRouteObservation,
    GatewaySurface,
    GatewaySwitchError,
    render_gateway_include,
)
from proof_agent.deployment.state import DeploymentSlot


BINDING = "a" * 64
OLD_BINDING = "b" * 64


class FakeNginxControl:
    def __init__(
        self,
        *,
        active_include: Path,
        observations: tuple[GatewayRouteObservation, ...] | None = None,
        fail_validation: bool = False,
    ) -> None:
        self.active_include = active_include
        self.observations = observations
        self.fail_validation = fail_validation
        self.calls: list[object] = []
        self.old_active_during_validation: bytes | None = None

    def validate(self, candidate_include: Path) -> None:
        self.calls.append(("validate", candidate_include.parent, candidate_include.read_bytes()))
        self.old_active_during_validation = self.active_include.read_bytes()
        if self.fail_validation:
            raise RuntimeError("synthetic nginx -t failure")

    def reload(self) -> None:
        self.calls.append("reload")

    def observe_routes(self) -> tuple[GatewayRouteObservation, ...]:
        self.calls.append("observe_routes")
        if self.observations is not None:
            return self.observations
        return tuple(
            GatewayRouteObservation(
                surface=surface,
                generation=13,
                slot=DeploymentSlot.GREEN,
            )
            for surface in GatewaySurface
        )


def _active(tmp_path: Path) -> tuple[Path, bytes]:
    active = tmp_path / "active-upstreams.conf"
    old = render_gateway_include(
        slot=DeploymentSlot.BLUE,
        generation=12,
        deployment_binding_sha256=OLD_BINDING,
    )
    active.write_bytes(old)
    return active, old


def test_switch_validates_temp_then_atomically_reloads_and_observes_all_surfaces(
    tmp_path: Path,
) -> None:
    active, old = _active(tmp_path)
    control = FakeNginxControl(active_include=active)

    result = AtomicNginxGatewaySwitcher(
        active_include=active,
        control=control,
    ).switch(
        target_slot=DeploymentSlot.GREEN,
        binding_sha256=BINDING,
        current_generation=12,
    )

    expected = render_gateway_include(
        slot=DeploymentSlot.GREEN,
        generation=13,
        deployment_binding_sha256=BINDING,
    )
    assert control.old_active_during_validation == old
    assert control.calls[0][0] == "validate"
    assert control.calls[0][1] == tmp_path
    assert control.calls[0][2] == expected
    assert control.calls[1:] == ["reload", "observe_routes"]
    assert active.read_bytes() == expected
    assert result.generation == 13
    assert result.slot is DeploymentSlot.GREEN
    assert result.deployment_binding_sha256 == BINDING


def test_validation_failure_never_replaces_or_reloads_active_routes(tmp_path: Path) -> None:
    active, old = _active(tmp_path)
    control = FakeNginxControl(active_include=active, fail_validation=True)

    with pytest.raises(GatewaySwitchError) as caught:
        AtomicNginxGatewaySwitcher(active_include=active, control=control).switch(
            target_slot=DeploymentSlot.GREEN,
            binding_sha256=BINDING,
            current_generation=12,
        )

    assert caught.value.error_code == "gateway_candidate_invalid"
    assert active.read_bytes() == old
    assert [call for call in control.calls if call == "reload"] == []


def test_mixed_route_generation_restores_old_include_and_reloads(tmp_path: Path) -> None:
    active, old = _active(tmp_path)
    observations = tuple(
        GatewayRouteObservation(
            surface=surface,
            generation=12 if surface is GatewaySurface.SSE else 13,
            slot=DeploymentSlot.GREEN,
        )
        for surface in GatewaySurface
    )
    control = FakeNginxControl(
        active_include=active,
        observations=observations,
    )

    with pytest.raises(GatewaySwitchError) as caught:
        AtomicNginxGatewaySwitcher(active_include=active, control=control).switch(
            target_slot=DeploymentSlot.GREEN,
            binding_sha256=BINDING,
            current_generation=12,
        )

    assert caught.value.error_code == "gateway_generation_verification_failed"
    assert active.read_bytes() == old
    assert [call for call in control.calls if call == "reload"] == ["reload", "reload"]
