"""Fail-closed fenced Blue/Green deployment and rollback choreography."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from proof_agent.deployment.gateway import (
    GatewayRoutingGeneration,
    GatewaySwitchError,
    GatewaySwitcher,
)
from proof_agent.deployment.state import (
    BlueGreenDeploymentRequest,
    BlueGreenDeploymentResult,
    DeploymentOutcome,
    DeploymentSlot,
    DeploymentStepName,
    DeploymentStepRecord,
    DeploymentStepStatus,
    rollback_asset_retention_deadline,
)


_T = TypeVar("_T")


class DeploymentActionError(RuntimeError):
    """A safe, machine-readable deployment action failure."""

    def __init__(self, error_code: str) -> None:
        if (
            not error_code
            or len(error_code) > 128
            or any(
                not (char.islower() or char.isdigit() or char in "._-")
                for char in error_code
            )
        ):
            raise ValueError("deployment error code is not trace-safe")
        super().__init__(error_code)
        self.error_code = error_code


class BlueGreenOperations(Protocol):
    def validate_prechecks(self, request: BlueGreenDeploymentRequest) -> None: ...

    def run_locked_expand_migration(
        self, request: BlueGreenDeploymentRequest
    ) -> None: ...

    def start_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None: ...

    def assert_candidate_ready(self, request: BlueGreenDeploymentRequest) -> None: ...

    def run_isolated_smoke(self, request: BlueGreenDeploymentRequest) -> None: ...

    def queue_contracts_are_bidirectionally_compatible(
        self, request: BlueGreenDeploymentRequest
    ) -> bool: ...

    def pause_admission(self, request: BlueGreenDeploymentRequest) -> None: ...

    def resume_admission(self, request: BlueGreenDeploymentRequest) -> None: ...

    def begin_old_workers_draining(
        self, request: BlueGreenDeploymentRequest
    ) -> None: ...

    def wait_old_claims_zero(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        timeout_seconds: int,
    ) -> bool: ...

    def restore_old_workers_active(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        expected_epoch: int,
    ) -> None: ...

    def keep_candidate_standby(self, request: BlueGreenDeploymentRequest) -> None: ...

    def activate_candidate_workers(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        previous_epoch: int,
    ) -> int: ...

    def run_stable_origin_smoke(self, request: BlueGreenDeploymentRequest) -> None: ...

    def soak(self, request: BlueGreenDeploymentRequest, *, seconds: int) -> None: ...

    def stop_old_compute(self, request: BlueGreenDeploymentRequest) -> None: ...

    def assert_old_api_ready(self, request: BlueGreenDeploymentRequest) -> None: ...

    def begin_candidate_workers_draining(
        self, request: BlueGreenDeploymentRequest
    ) -> None: ...

    def wait_candidate_claims_zero(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        timeout_seconds: int,
    ) -> bool: ...

    def fence_candidate_and_wait_for_lease_expiry(
        self, request: BlueGreenDeploymentRequest
    ) -> None: ...

    def activate_old_workers(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        previous_epoch: int,
    ) -> int: ...

    def fail_lost_candidate_attempts(
        self, request: BlueGreenDeploymentRequest
    ) -> None: ...


class _StepFailed(RuntimeError):
    pass


class BlueGreenChoreographer:
    """Run the approved sequence and contain failures on the correct switch side."""

    def __init__(
        self,
        *,
        operations: BlueGreenOperations,
        gateway: GatewaySwitcher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._operations = operations
        self._gateway = gateway
        self._clock = clock or (lambda: datetime.now(UTC))
        self._steps: list[DeploymentStepRecord] = []

    def deploy(self, request: BlueGreenDeploymentRequest) -> BlueGreenDeploymentResult:
        self._steps = []
        candidate_started = False
        old_workers_draining = False
        admission_paused = False
        gateway: GatewayRoutingGeneration | None = None
        switched_at: datetime | None = None
        candidate_epoch: int | None = None
        try:
            self._run(
                request,
                DeploymentStepName.VALIDATE_PRECHECKS,
                lambda: self._operations.validate_prechecks(request),
            )
            self._run(
                request,
                DeploymentStepName.LOCKED_EXPAND_MIGRATION,
                lambda: self._operations.run_locked_expand_migration(request),
            )
            self._run(
                request,
                DeploymentStepName.START_CANDIDATE_STANDBY,
                lambda: self._operations.start_candidate_standby(request),
            )
            candidate_started = True
            self._run(
                request,
                DeploymentStepName.CANDIDATE_READINESS,
                lambda: self._operations.assert_candidate_ready(request),
            )
            self._run(
                request,
                DeploymentStepName.ISOLATED_SMOKE,
                lambda: self._operations.run_isolated_smoke(request),
            )
            compatible = self._run(
                request,
                DeploymentStepName.BIDIRECTIONAL_QUEUE_CONTRACT,
                lambda: self._require_queue_policy(request),
            )
            if not compatible:
                self._run(
                    request,
                    DeploymentStepName.PAUSE_ADMISSION,
                    lambda: self._operations.pause_admission(request),
                )
                admission_paused = True
            self._run(
                request,
                DeploymentStepName.OLD_WORKERS_DRAINING,
                lambda: self._operations.begin_old_workers_draining(request),
            )
            old_workers_draining = True
            self._run(
                request,
                DeploymentStepName.OLD_CLAIMS_ZERO,
                lambda: self._require_old_claims_zero(request),
            )
            gateway = self._run(
                request,
                DeploymentStepName.GATEWAY_SWITCH,
                lambda: self._switch_gateway(
                    request,
                    target_slot=request.candidate_slot,
                    current_generation=request.active_gateway_generation,
                ),
            )
            switched_at = self._now()
            candidate_epoch = self._run(
                request,
                DeploymentStepName.CANDIDATE_ACTIVATION,
                lambda: self._activate_candidate(request),
            )
            self._run(
                request,
                DeploymentStepName.STABLE_ORIGIN_SMOKE,
                lambda: self._operations.run_stable_origin_smoke(request),
            )
            self._run(
                request,
                DeploymentStepName.SOAK,
                lambda: self._operations.soak(request, seconds=request.soak_seconds),
            )
            self._run(
                request,
                DeploymentStepName.STOP_OLD_COMPUTE,
                lambda: self._operations.stop_old_compute(request),
            )
            if admission_paused:
                self._run(
                    request,
                    DeploymentStepName.RESUME_ADMISSION,
                    lambda: self._operations.resume_admission(request),
                )
            return self._result(
                request,
                outcome=DeploymentOutcome.DEPLOYED,
                gateway=gateway,
                candidate_epoch=candidate_epoch,
                switched_at=switched_at,
            )
        except _StepFailed:
            if gateway is None:
                abort_ok = self._abort_before_switch(
                    request,
                    candidate_started=candidate_started,
                    old_workers_draining=old_workers_draining,
                    admission_paused=admission_paused,
                )
                return self._result(
                    request,
                    outcome=(
                        DeploymentOutcome.ABORTED
                        if abort_ok
                        else DeploymentOutcome.ABORT_FAILED
                    ),
                )
            rollback_ok, rollback_gateway = self._rollback_after_switch(
                request,
                current_generation=gateway.generation,
                authority_epoch=candidate_epoch or request.old_activation_epoch,
                admission_paused=admission_paused,
            )
            return self._result(
                request,
                outcome=(
                    DeploymentOutcome.ROLLED_BACK
                    if rollback_ok
                    else DeploymentOutcome.ROLLBACK_FAILED
                ),
                gateway=rollback_gateway or gateway,
                candidate_epoch=candidate_epoch,
                switched_at=switched_at,
            )

    def _require_queue_policy(self, request: BlueGreenDeploymentRequest) -> bool:
        compatible = self._operations.queue_contracts_are_bidirectionally_compatible(
            request
        )
        if not compatible and not request.admission_pause_authorized:
            raise DeploymentActionError("queue_contract_incompatible")
        return compatible

    def _require_old_claims_zero(self, request: BlueGreenDeploymentRequest) -> None:
        if not self._operations.wait_old_claims_zero(
            request,
            timeout_seconds=request.drain_timeout_seconds,
        ):
            raise DeploymentActionError("old_claims_drain_timeout")

    def _activate_candidate(self, request: BlueGreenDeploymentRequest) -> int:
        epoch = self._operations.activate_candidate_workers(
            request,
            previous_epoch=request.old_activation_epoch,
        )
        if epoch <= request.old_activation_epoch:
            raise DeploymentActionError("candidate_activation_epoch_not_higher")
        return epoch

    def _switch_gateway(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        target_slot: DeploymentSlot,
        current_generation: int,
    ) -> GatewayRoutingGeneration:
        try:
            result = self._gateway.switch(
                target_slot=target_slot,
                binding_sha256=request.binding.binding_sha256,
                current_generation=current_generation,
            )
        except GatewaySwitchError as exc:
            raise DeploymentActionError(exc.error_code) from exc
        if (
            result.slot is not target_slot
            or result.generation != current_generation + 1
            or result.deployment_binding_sha256 != request.binding.binding_sha256
        ):
            raise DeploymentActionError("gateway_generation_mismatch")
        return result

    def _abort_before_switch(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        candidate_started: bool,
        old_workers_draining: bool,
        admission_paused: bool,
    ) -> bool:
        ok = True
        if old_workers_draining:
            ok &= self._recover(
                request,
                DeploymentStepName.ABORT_OLD_WORKERS_ACTIVE,
                lambda: self._operations.restore_old_workers_active(
                    request,
                    expected_epoch=request.old_activation_epoch,
                ),
            )
        if candidate_started:
            ok &= self._recover(
                request,
                DeploymentStepName.ABORT_CANDIDATE_STANDBY,
                lambda: self._operations.keep_candidate_standby(request),
            )
        if admission_paused:
            ok &= self._recover(
                request,
                DeploymentStepName.RESUME_ADMISSION,
                lambda: self._operations.resume_admission(request),
            )
        return ok

    def _rollback_after_switch(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        current_generation: int,
        authority_epoch: int,
        admission_paused: bool,
    ) -> tuple[bool, GatewayRoutingGeneration | None]:
        ok = True
        rollback_gateway: GatewayRoutingGeneration | None = None
        ok &= self._recover(
            request,
            DeploymentStepName.ROLLBACK_OLD_API_READINESS,
            lambda: self._operations.assert_old_api_ready(request),
        )

        def route_old() -> None:
            nonlocal rollback_gateway
            rollback_gateway = self._switch_gateway(
                request,
                target_slot=request.old_slot,
                current_generation=current_generation,
            )

        ok &= self._recover(request, DeploymentStepName.ROLLBACK_GATEWAY, route_old)
        candidate_drain_started = self._recover(
            request,
            DeploymentStepName.ROLLBACK_CANDIDATE_DRAINING,
            lambda: self._operations.begin_candidate_workers_draining(request),
        )
        ok &= candidate_drain_started

        def wait_candidate() -> None:
            candidate_drained = self._operations.wait_candidate_claims_zero(
                request,
                timeout_seconds=request.drain_timeout_seconds,
            )
            if not candidate_drained:
                raise DeploymentActionError("candidate_claims_drain_timeout")

        drained_ok = (
            self._recover(
                request,
                DeploymentStepName.ROLLBACK_CANDIDATE_CLAIMS_ZERO,
                wait_candidate,
            )
            if candidate_drain_started
            else False
        )
        if not drained_ok:
            ok &= self._recover(
                request,
                DeploymentStepName.ROLLBACK_CANDIDATE_FENCED,
                lambda: self._operations.fence_candidate_and_wait_for_lease_expiry(
                    request
                ),
            )

        def activate_old() -> None:
            epoch = self._operations.activate_old_workers(
                request,
                previous_epoch=authority_epoch,
            )
            if epoch <= authority_epoch:
                raise DeploymentActionError("rollback_activation_epoch_not_higher")

        ok &= self._recover(
            request,
            DeploymentStepName.ROLLBACK_OLD_ACTIVATION,
            activate_old,
        )
        ok &= self._recover(
            request,
            DeploymentStepName.ROLLBACK_FAIL_LOST_ATTEMPTS,
            lambda: self._operations.fail_lost_candidate_attempts(request),
        )
        if admission_paused:
            ok &= self._recover(
                request,
                DeploymentStepName.RESUME_ADMISSION,
                lambda: self._operations.resume_admission(request),
            )
        return ok, rollback_gateway

    def _run(
        self,
        request: BlueGreenDeploymentRequest,
        name: DeploymentStepName,
        action: Callable[[], _T],
    ) -> _T:
        started_at = self._now()
        try:
            result = action()
        except DeploymentActionError as exc:
            self._append_step(
                request,
                name,
                started_at=started_at,
                status=DeploymentStepStatus.FAILED,
                error_code=exc.error_code,
            )
            raise _StepFailed from exc
        except Exception as exc:
            self._append_step(
                request,
                name,
                started_at=started_at,
                status=DeploymentStepStatus.FAILED,
                error_code="deployment_operation_failed",
            )
            raise _StepFailed from exc
        self._append_step(
            request,
            name,
            started_at=started_at,
            status=DeploymentStepStatus.SUCCEEDED,
        )
        return result

    def _recover(
        self,
        request: BlueGreenDeploymentRequest,
        name: DeploymentStepName,
        action: Callable[[], object],
    ) -> bool:
        try:
            self._run(request, name, action)
        except _StepFailed:
            return False
        return True

    def _append_step(
        self,
        request: BlueGreenDeploymentRequest,
        name: DeploymentStepName,
        *,
        started_at: datetime,
        status: DeploymentStepStatus,
        error_code: str | None = None,
    ) -> None:
        self._steps.append(
            DeploymentStepRecord(
                name=name,
                status=status,
                deployment_binding_sha256=request.binding.binding_sha256,
                candidate_release_id=request.binding.release_id,
                started_at=started_at,
                completed_at=self._now(),
                error_code=error_code,
            )
        )

    def _result(
        self,
        request: BlueGreenDeploymentRequest,
        *,
        outcome: DeploymentOutcome,
        gateway: GatewayRoutingGeneration | None = None,
        candidate_epoch: int | None = None,
        switched_at: datetime | None = None,
    ) -> BlueGreenDeploymentResult:
        return BlueGreenDeploymentResult(
            outcome=outcome,
            deployment_binding_sha256=request.binding.binding_sha256,
            steps=tuple(self._steps),
            gateway_generation=None if gateway is None else gateway.generation,
            candidate_activation_epoch=candidate_epoch,
            switched_at=switched_at,
            retention_until=(
                None
                if switched_at is None
                else rollback_asset_retention_deadline(switched_at)
            ),
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise ValueError("deployment clock must be timezone-aware")
        return value


__all__ = [
    "BlueGreenChoreographer",
    "BlueGreenOperations",
    "DeploymentActionError",
]
