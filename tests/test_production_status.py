from __future__ import annotations

from datetime import UTC, datetime, timedelta

from proof_agent.contracts.health import ProductionDeploymentIdentity
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.delivery.production_status import (
    PeriodicFreshnessProbe,
    ProductionReadinessProbe,
)


def _identity() -> ProductionDeploymentIdentity:
    return ProductionDeploymentIdentity(
        release_id="proofagent-2026.07.25-rc1",
        image_digest="a" * 64,
        deployment_slot="green",
        role="api",
        activation_state=RoleActivationState.STANDBY,
        schema_revision="0010_hybrid_knowledge_workflow",
        schema_compatible_from="0010_hybrid_knowledge_workflow",
        schema_compatible_through="0010_hybrid_knowledge_workflow",
        deployment_compatibility_manifest_sha256="b" * 64,
    )


def test_readiness_reports_candidate_identity_and_standby_as_healthy() -> None:
    readiness = ProductionReadinessProbe(
        identity=_identity(),
        checks={"postgresql": lambda: True, "s3": lambda: True},
    )()

    assert readiness.ready is True
    assert readiness.public_payload() == {
        "status": "ready",
        "release_id": "proofagent-2026.07.25-rc1",
        "image_digest": "a" * 64,
        "deployment_slot": "green",
        "role": "api",
        "activation_state": "STANDBY",
        "schema": {
            "revision": "0010_hybrid_knowledge_workflow",
            "compatible_from": "0010_hybrid_knowledge_workflow",
            "compatible_through": "0010_hybrid_knowledge_workflow",
        },
        "deployment_compatibility_manifest_sha256": "b" * 64,
        "components": {"postgresql": "ready", "s3": "ready"},
    }


def test_readiness_identity_rejects_unsafe_or_unbound_values() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _identity().model_copy(update={"release_id": "secret\nvalue"}, deep=True).__class__(
            **{
                **_identity().model_dump(mode="python"),
                "release_id": "secret\nvalue",
            }
        )

    with pytest.raises(ValidationError):
        ProductionDeploymentIdentity(
            **{
                **_identity().model_dump(mode="python"),
                "image_digest": "latest",
            }
        )


def test_periodic_probe_is_ready_only_while_latest_success_is_fresh() -> None:
    now = datetime(2026, 7, 25, 1, 2, 3, tzinfo=UTC)
    current = [now]
    outcomes = iter((True, False))
    probe = PeriodicFreshnessProbe(
        check=lambda: next(outcomes),
        max_age=timedelta(seconds=60),
        interval=timedelta(seconds=30),
        clock=lambda: current[0],
    )

    assert probe() is False
    assert probe.refresh() is True
    assert probe() is True

    current[0] += timedelta(seconds=61)
    assert probe() is False
    assert probe.refresh() is False
    assert probe() is False
