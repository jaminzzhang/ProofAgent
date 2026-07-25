from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType
from threading import Event, Lock, Thread
from typing import Any, Protocol
import signal

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.contracts.ports.worker_roles import (
    WorkerRoleLeaseLostError,
    WorkerRoleRepository,
)
from proof_agent.contracts.worker_roles import (
    ProductionWorkerRole,
    WorkerRoleActivation,
)
from proof_agent.delivery.production_status import ProductionReadiness


ReadinessProvider = Callable[[], ProductionReadiness]


class DeploymentSignalRoleController(Protocol):
    def begin_draining(self) -> object | None: ...

    def resume_active(self) -> object | None: ...


def install_worker_role_deployment_signals(
    controller: DeploymentSignalRoleController,
) -> dict[int, Any]:
    """Install Linux deployment drain/resume controls without stopping the process."""

    if not hasattr(signal, "SIGUSR1") or not hasattr(signal, "SIGUSR2"):
        raise RuntimeError("Worker deployment signals require a POSIX platform")
    previous: dict[int, Any] = {}

    def begin_draining(_signum: int, _frame: FrameType | None) -> None:
        try:
            controller.begin_draining()
        except Exception:
            # The deployment controller verifies PostgreSQL authority after the
            # signal. A transient handler failure must not crash the Worker.
            return

    def resume_active(_signum: int, _frame: FrameType | None) -> None:
        try:
            controller.resume_active()
        except Exception:
            return

    for signum, handler in (
        (signal.SIGUSR1, begin_draining),
        (signal.SIGUSR2, resume_active),
    ):
        previous[int(signum)] = signal.getsignal(signum)
        signal.signal(signum, handler)
    return previous


class WorkerRoleLeaseController:
    """Own, renew, drain and release one process-scoped worker role lease."""

    def __init__(
        self,
        *,
        repository: WorkerRoleRepository,
        role: ProductionWorkerRole,
        slot: int,
        owner_id: str,
        configured_state: RoleActivationState,
        lease_seconds: int = 15,
        heartbeat_interval_seconds: float = 5.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if slot not in {1, 2}:
            raise ValueError("Worker role slot must be 1 or 2")
        if not owner_id or owner_id.strip() != owner_id or len(owner_id) > 255:
            raise ValueError("Worker role owner id is invalid")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("Worker role lease is outside the supported envelope")
        if not 0 < heartbeat_interval_seconds < lease_seconds:
            raise ValueError("Worker role heartbeat must be shorter than its lease")
        self._repository = repository
        self._role = role
        self._slot = slot
        self._owner_id = owner_id
        self._configured_state = configured_state
        self._lease_seconds = lease_seconds
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._clock = clock or (lambda: datetime.now(UTC))
        self._activation: WorkerRoleActivation | None = None
        self._lease_lost = False
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def activation(self) -> WorkerRoleActivation | None:
        with self._lock:
            return self._activation

    def start(self, *, background: bool = True) -> WorkerRoleActivation | None:
        now = self._now()
        current = self._repository.get(self._role)
        if self._configured_state is RoleActivationState.STANDBY:
            activation = None
        elif self._configured_state is RoleActivationState.ACTIVE:
            activation = self._repository.activate(
                role=self._role,
                slot=self._slot,
                owner_id=self._owner_id,
                expected_epoch=current.activation_epoch,
                now=now,
                lease_seconds=self._lease_seconds,
            )
        else:
            if not worker_role_is_ready(
                configured_state=current.state,
                role=self._role,
                slot=self._slot,
                owner_id=self._owner_id,
                current=current,
                now=now,
                expected_epoch=current.activation_epoch,
            ):
                raise WorkerRoleLeaseLostError(
                    "A draining worker must already own the live role lease"
                )
            activation = (
                self._repository.begin_draining(current, now=now)
                if current.state is RoleActivationState.ACTIVE
                else current
            )
        with self._lock:
            self._activation = activation
            self._lease_lost = False
        if background and activation is not None:
            self._thread = Thread(
                target=self._heartbeat_loop,
                name=f"proof-agent-{self._role.value}-lease",
                daemon=True,
            )
            self._thread.start()
        return activation

    def heartbeat_once(self) -> bool:
        with self._lock:
            activation = self._activation
            if activation is None or self._lease_lost:
                return False
            try:
                renewed = self._repository.heartbeat(
                    activation,
                    now=self._now(),
                    lease_seconds=self._lease_seconds,
                )
            except WorkerRoleLeaseLostError:
                self._activation = None
                self._lease_lost = True
                return False
            self._activation = renewed
        return True

    def begin_draining(self) -> WorkerRoleActivation | None:
        with self._lock:
            activation = self._activation
            if activation is None or self._lease_lost:
                return None
            if activation.state is RoleActivationState.DRAINING:
                return activation
            try:
                draining = self._repository.begin_draining(
                    activation,
                    now=self._now(),
                )
            except WorkerRoleLeaseLostError:
                self._activation = None
                self._lease_lost = True
                return None
            self._configured_state = RoleActivationState.DRAINING
            self._activation = draining
            return draining

    def resume_active(self) -> WorkerRoleActivation | None:
        """Cancel a deployment drain while retaining the current fencing epoch."""

        with self._lock:
            activation = self._activation
            if activation is None or self._lease_lost:
                return None
            if activation.state is RoleActivationState.ACTIVE:
                self._configured_state = RoleActivationState.ACTIVE
                return activation
            try:
                active = self._repository.resume_active(
                    activation,
                    now=self._now(),
                )
            except WorkerRoleLeaseLostError:
                self._activation = None
                self._lease_lost = True
                return None
            self._configured_state = RoleActivationState.ACTIVE
            self._activation = active
            return active

    def release(self) -> None:
        with self._lock:
            activation = self._activation
            if activation is None:
                return
            try:
                self._repository.release(activation, now=self._now())
            except WorkerRoleLeaseLostError:
                self._lease_lost = True
            finally:
                self._activation = None

    def check_ready(self) -> bool:
        with self._lock:
            activation = self._activation
            lease_lost = self._lease_lost
            configured_state = self._configured_state
        if lease_lost:
            return False
        try:
            current = self._repository.get(self._role)
            return worker_role_is_ready(
                configured_state=configured_state,
                role=self._role,
                slot=self._slot,
                owner_id=self._owner_id,
                current=current,
                now=self._now(),
                expected_epoch=(
                    None if activation is None else activation.activation_epoch
                ),
            )
        except Exception:
            return False

    def can_claim(self) -> bool:
        with self._lock:
            if self._configured_state is not RoleActivationState.ACTIVE:
                return False
        return self.check_ready()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(5.0, self._heartbeat_interval_seconds + 1.0))
        self.release()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_interval_seconds):
            if not self.heartbeat_once():
                return

    def _now(self) -> datetime:
        value = self._clock()
        if value.utcoffset() is None:
            raise ValueError("Worker role controller clock must be timezone-aware")
        return value


def worker_role_is_ready(
    *,
    configured_state: RoleActivationState,
    role: ProductionWorkerRole,
    slot: int,
    owner_id: str,
    current: WorkerRoleActivation,
    now: datetime,
    expected_epoch: int | None = None,
) -> bool:
    """Evaluate sanitized readiness against current PostgreSQL role authority."""

    if current.role is not role:
        return False
    if configured_state is RoleActivationState.STANDBY:
        return not (
            current.is_live(at=now)
            and current.slot == slot
            and current.owner_id == owner_id
        )
    return bool(
        current.state is configured_state
        and current.slot == slot
        and current.owner_id == owner_id
        and (expected_epoch is None or current.activation_epoch == expected_epoch)
        and current.is_live(at=now)
    )


def create_worker_health_application(
    readiness: ReadinessProvider,
) -> FastAPI:
    """Create the loopback-only worker liveness/readiness HTTP application."""

    application = FastAPI(
        title="Proof Agent Worker Health",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/livez")
    def livez() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/readyz")
    def readyz() -> JSONResponse:
        result = readiness()
        return JSONResponse(
            result.public_payload(),
            status_code=200 if result.ready else 503,
        )

    return application


class WorkerHealthServer:
    """Background loopback server owned by one worker process."""

    def __init__(
        self,
        *,
        readiness: ReadinessProvider,
        host: str,
        port: int,
    ) -> None:
        if host not in {"127.0.0.1", "::1"}:
            raise ValueError("Worker health server must bind to loopback")
        if not 1 <= port <= 65535:
            raise ValueError("Worker health server port is invalid")
        import uvicorn

        self._server = uvicorn.Server(
            uvicorn.Config(
                create_worker_health_application(readiness),
                host=host,
                port=port,
                log_level="warning",
                access_log=False,
            )
        )
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._server.run,
            name="proof-agent-worker-health",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5.0)


__all__ = [
    "WorkerHealthServer",
    "WorkerRoleLeaseController",
    "create_worker_health_application",
    "worker_role_is_ready",
]
