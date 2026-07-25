from __future__ import annotations

from datetime import UTC, datetime

import pytest

from proof_agent.deployment.choreography import (
    BlueGreenChoreographer,
    DeploymentActionError,
)
from proof_agent.deployment.gateway import GatewayRoutingGeneration
from proof_agent.deployment.state import (
    BlueGreenDeploymentRequest,
    CandidateBinding,
    DeploymentOutcome,
    DeploymentSlot,
    DeploymentStepName,
    DeploymentStepStatus,
    rollback_asset_retention_deadline,
)


NOW = datetime(2026, 7, 13, 2, 0, tzinfo=UTC)


def _binding() -> CandidateBinding:
    return CandidateBinding(
        release_id="release-2026.07.13.1",
        image_reference=f"registry.example.test/proof-agent@sha256:{'a' * 64}",
        deployment_compatibility_manifest_sha256="b" * 64,
        migration_set_sha256="c" * 64,
        schema_revision="0011_worker_role_leases",
    )


def _request() -> BlueGreenDeploymentRequest:
    return BlueGreenDeploymentRequest(
        binding=_binding(),
        old_slot=DeploymentSlot.BLUE,
        candidate_slot=DeploymentSlot.GREEN,
        old_activation_epoch=7,
        active_gateway_generation=12,
    )


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[DeploymentSlot, int]] = []

    def switch(
        self,
        *,
        target_slot: DeploymentSlot,
        binding_sha256: str,
        current_generation: int,
    ) -> GatewayRoutingGeneration:
        self.calls.append((target_slot, current_generation))
        return GatewayRoutingGeneration(
            generation=current_generation + 1,
            slot=target_slot,
            deployment_binding_sha256=binding_sha256,
            include_sha256="d" * 64,
        )


class FakeOperations:
    def __init__(
        self,
        *,
        old_claims_drained: bool = True,
        queue_compatible: bool = True,
    ) -> None:
        self.calls: list[object] = []
        self.old_claims_drained = old_claims_drained
        self.queue_compatible = queue_compatible

    def validate_prechecks(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("validate_prechecks")

    def run_locked_expand_migration(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("run_locked_expand_migration")

    def start_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("start_candidate_standby")

    def assert_candidate_ready(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("assert_candidate_ready")

    def run_isolated_smoke(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("run_isolated_smoke")

    def queue_contracts_are_bidirectionally_compatible(
        self, request: BlueGreenDeploymentRequest
    ) -> bool:
        self.calls.append("queue_contracts_are_bidirectionally_compatible")
        return self.queue_compatible

    def pause_admission(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("pause_admission")

    def resume_admission(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("resume_admission")

    def begin_old_workers_draining(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("begin_old_workers_draining")

    def wait_old_claims_zero(
        self, request: BlueGreenDeploymentRequest, *, timeout_seconds: int
    ) -> bool:
        self.calls.append(("wait_old_claims_zero", timeout_seconds))
        return self.old_claims_drained

    def restore_old_workers_active(
        self, request: BlueGreenDeploymentRequest, *, expected_epoch: int
    ) -> None:
        self.calls.append(("restore_old_workers_active", expected_epoch))

    def keep_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("keep_candidate_standby")

    def activate_candidate_workers(
        self, request: BlueGreenDeploymentRequest, *, previous_epoch: int
    ) -> int:
        self.calls.append(("activate_candidate_workers", previous_epoch))
        return previous_epoch + 1

    def run_stable_origin_smoke(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("run_stable_origin_smoke")

    def soak(self, request: BlueGreenDeploymentRequest, *, seconds: int) -> None:
        self.calls.append(("soak", seconds))

    def stop_old_compute(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("stop_old_compute")

    def assert_old_api_ready(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("assert_old_api_ready")

    def begin_candidate_workers_draining(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self.calls.append("begin_candidate_workers_draining")

    def wait_candidate_claims_zero(
        self, request: BlueGreenDeploymentRequest, *, timeout_seconds: int
    ) -> bool:
        self.calls.append(("wait_candidate_claims_zero", timeout_seconds))
        return True

    def fence_candidate_and_wait_for_lease_expiry(
        self, request: BlueGreenDeploymentRequest
    ) -> None:
        self.calls.append("fence_candidate_and_wait_for_lease_expiry")

    def activate_old_workers(
        self, request: BlueGreenDeploymentRequest, *, previous_epoch: int
    ) -> int:
        self.calls.append(("activate_old_workers", previous_epoch))
        return previous_epoch + 1

    def fail_lost_candidate_attempts(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("fail_lost_candidate_attempts")


def test_happy_path_runs_the_approved_forward_order_and_records_binding() -> None:
    operations = FakeOperations()
    gateway = FakeGateway()

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=gateway,
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.DEPLOYED
    assert operations.calls == [
        "validate_prechecks",
        "run_locked_expand_migration",
        "start_candidate_standby",
        "assert_candidate_ready",
        "run_isolated_smoke",
        "queue_contracts_are_bidirectionally_compatible",
        "begin_old_workers_draining",
        ("wait_old_claims_zero", 150),
        ("activate_candidate_workers", 7),
        "run_stable_origin_smoke",
        ("soak", 1800),
        "stop_old_compute",
    ]
    assert gateway.calls == [(DeploymentSlot.GREEN, 12)]
    assert result.gateway_generation == 13
    assert result.candidate_activation_epoch == 8
    assert result.retention_until is not None
    assert all(
        step.deployment_binding_sha256 == _binding().binding_sha256
        for step in result.steps
    )
    assert [step.name for step in result.steps] == [
        DeploymentStepName.VALIDATE_PRECHECKS,
        DeploymentStepName.LOCKED_EXPAND_MIGRATION,
        DeploymentStepName.START_CANDIDATE_STANDBY,
        DeploymentStepName.CANDIDATE_READINESS,
        DeploymentStepName.ISOLATED_SMOKE,
        DeploymentStepName.BIDIRECTIONAL_QUEUE_CONTRACT,
        DeploymentStepName.OLD_WORKERS_DRAINING,
        DeploymentStepName.OLD_CLAIMS_ZERO,
        DeploymentStepName.GATEWAY_SWITCH,
        DeploymentStepName.CANDIDATE_ACTIVATION,
        DeploymentStepName.STABLE_ORIGIN_SMOKE,
        DeploymentStepName.SOAK,
        DeploymentStepName.STOP_OLD_COMPUTE,
    ]


def test_drain_timeout_aborts_before_switch_at_the_same_old_epoch() -> None:
    operations = FakeOperations(old_claims_drained=False)
    gateway = FakeGateway()

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=gateway,
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.ABORTED
    assert gateway.calls == []
    assert ("restore_old_workers_active", 7) in operations.calls
    assert "keep_candidate_standby" in operations.calls
    assert not any(
        isinstance(call, tuple) and call[0] == "activate_candidate_workers"
        for call in operations.calls
    )
    failed = [step for step in result.steps if step.status is DeploymentStepStatus.FAILED]
    assert [(step.name, step.error_code) for step in failed] == [
        (DeploymentStepName.OLD_CLAIMS_ZERO, "old_claims_drain_timeout")
    ]


class FailedAbortContainmentOperations(FakeOperations):
    def restore_old_workers_active(
        self, request: BlueGreenDeploymentRequest, *, expected_epoch: int
    ) -> None:
        self.calls.append(("restore_old_workers_active", expected_epoch))
        raise DeploymentActionError("old_workers_resume_failed")


def test_abort_reports_containment_failure_instead_of_claiming_clean_abort() -> None:
    result = BlueGreenChoreographer(
        operations=FailedAbortContainmentOperations(old_claims_drained=False),
        gateway=FakeGateway(),
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.ABORT_FAILED
    failed = [step for step in result.steps if step.status is DeploymentStepStatus.FAILED]
    assert failed[-1].name is DeploymentStepName.ABORT_OLD_WORKERS_ACTIVE
    assert failed[-1].error_code == "old_workers_resume_failed"


def test_incompatible_queue_contract_aborts_unless_pause_is_explicitly_authorized() -> None:
    operations = FakeOperations(queue_compatible=False)
    gateway = FakeGateway()

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=gateway,
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.ABORTED
    assert gateway.calls == []
    assert "pause_admission" not in operations.calls
    assert "begin_old_workers_draining" not in operations.calls
    assert "keep_candidate_standby" in operations.calls
    assert [
        step.error_code
        for step in result.steps
        if step.status is DeploymentStepStatus.FAILED
    ] == ["queue_contract_incompatible"]


def test_authorized_pause_spans_the_entire_incompatible_switch_window() -> None:
    operations = FakeOperations(queue_compatible=False)
    gateway = FakeGateway()
    request = _request().model_copy(update={"admission_pause_authorized": True})

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=gateway,
        clock=lambda: NOW,
    ).deploy(request)

    assert result.outcome is DeploymentOutcome.DEPLOYED
    assert operations.calls.index("pause_admission") < operations.calls.index(
        "begin_old_workers_draining"
    )
    assert operations.calls.index("resume_admission") > operations.calls.index(
        "stop_old_compute"
    )


class StableSmokeFailureOperations(FakeOperations):
    def run_stable_origin_smoke(self, request: BlueGreenDeploymentRequest) -> None:
        self.calls.append("run_stable_origin_smoke")
        raise DeploymentActionError("stable_origin_smoke_failed")


def test_post_switch_failure_routes_old_first_then_fences_and_reactivates_higher() -> None:
    operations = StableSmokeFailureOperations()
    gateway = FakeGateway()

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=gateway,
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.ROLLED_BACK
    assert gateway.calls == [
        (DeploymentSlot.GREEN, 12),
        (DeploymentSlot.BLUE, 13),
    ]
    rollback_calls = operations.calls[operations.calls.index("assert_old_api_ready") :]
    assert rollback_calls == [
        "assert_old_api_ready",
        "begin_candidate_workers_draining",
        ("wait_candidate_claims_zero", 150),
        ("activate_old_workers", 8),
        "fail_lost_candidate_attempts",
    ]
    assert result.gateway_generation == 14
    assert result.candidate_activation_epoch == 8
    assert result.retention_until is not None


class CandidateDrainTimeoutOperations(StableSmokeFailureOperations):
    def wait_candidate_claims_zero(
        self, request: BlueGreenDeploymentRequest, *, timeout_seconds: int
    ) -> bool:
        self.calls.append(("wait_candidate_claims_zero", timeout_seconds))
        return False


def test_rollback_drain_timeout_requires_explicit_candidate_fencing() -> None:
    operations = CandidateDrainTimeoutOperations()

    result = BlueGreenChoreographer(
        operations=operations,
        gateway=FakeGateway(),
        clock=lambda: NOW,
    ).deploy(_request())

    assert result.outcome is DeploymentOutcome.ROLLED_BACK
    assert "fence_candidate_and_wait_for_lease_expiry" in operations.calls
    assert operations.calls.index(
        "fence_candidate_and_wait_for_lease_expiry"
    ) < operations.calls.index(("activate_old_workers", 8))
    failed = [step for step in result.steps if step.status is DeploymentStepStatus.FAILED]
    assert failed[-1].name is DeploymentStepName.ROLLBACK_CANDIDATE_CLAIMS_ZERO
    assert failed[-1].error_code == "candidate_claims_drain_timeout"


@pytest.mark.parametrize(
    ("switched_at", "expected"),
    [
        (
            datetime.fromisoformat("2026-07-13T08:00:00+08:00"),
            datetime.fromisoformat("2026-07-14T08:00:00+08:00"),
        ),
        (
            datetime.fromisoformat("2026-07-17T19:00:00+08:00"),
            datetime.fromisoformat("2026-07-20T18:00:00+08:00"),
        ),
    ],
)
def test_rollback_assets_cover_24_hours_and_the_next_complete_support_window(
    switched_at: datetime,
    expected: datetime,
) -> None:
    assert rollback_asset_retention_deadline(switched_at) == expected
