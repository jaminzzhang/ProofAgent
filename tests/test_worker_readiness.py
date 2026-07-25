from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import signal

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from proof_agent.bootstrap import production_roles
from proof_agent.contracts.health import ProductionDeploymentIdentity
from proof_agent.contracts.run_execution import RoleActivationState
from proof_agent.contracts.worker_roles import (
    ProductionWorkerRole,
    WorkerRoleActivation,
)
from proof_agent.contracts.ports.worker_roles import WorkerRoleLeaseLostError
from proof_agent.delivery.cli import app
from proof_agent.delivery.production_status import ProductionReadinessProbe
from proof_agent.delivery.worker_health import (
    WorkerRoleLeaseController,
    create_worker_health_application,
    install_worker_role_deployment_signals,
    worker_role_is_ready,
)


NOW = datetime(2026, 7, 25, 9, tzinfo=UTC)


class RecordingExecutor:
    def __init__(self) -> None:
        self.run_calls = 0
        self.activation_calls = 0

    def run_until_idle(self) -> int:
        self.run_calls += 1
        return 0

    def activate(self) -> object:
        self.activation_calls += 1
        raise AssertionError("continuous activation is outside this test")

    def stop(self) -> None:
        return None


class RecordingKnowledgeWorker:
    def __init__(self) -> None:
        self.run_calls = 0

    def run_once(self) -> None:
        self.run_calls += 1
        return None


@dataclass
class Composition:
    executor: RecordingExecutor | None = None
    worker: RecordingKnowledgeWorker | None = None
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def test_standby_executor_once_never_activates_or_claims(monkeypatch) -> None:
    executor = RecordingExecutor()
    composition = Composition(executor=executor)
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")
    monkeypatch.setenv("PROOF_AGENT_ACTIVATION_STATE", "standby")
    monkeypatch.setattr(
        production_roles,
        "compose_production_run_executor",
        lambda **_kwargs: composition,
    )

    result = CliRunner().invoke(app, ["run-executor", "--once"])

    assert result.exit_code == 0
    assert '"activation_state": "STANDBY"' in result.stdout
    assert executor.activation_calls == 0
    assert executor.run_calls == 0
    assert composition.closed is True


def test_active_executor_once_may_claim(monkeypatch) -> None:
    executor = RecordingExecutor()
    composition = Composition(executor=executor)
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")
    monkeypatch.setenv("PROOF_AGENT_ACTIVATION_STATE", "active")
    monkeypatch.setattr(
        production_roles,
        "compose_production_run_executor",
        lambda **_kwargs: composition,
    )

    result = CliRunner().invoke(app, ["run-executor", "--once"])

    assert result.exit_code == 0
    assert executor.run_calls == 1
    assert composition.closed is True


def test_standby_knowledge_worker_once_never_claims(monkeypatch) -> None:
    worker = RecordingKnowledgeWorker()
    composition = Composition(worker=worker)
    monkeypatch.setenv("PROOF_AGENT_MODE", "production")
    monkeypatch.setenv("PROOF_AGENT_ACTIVATION_STATE", "standby")
    monkeypatch.setattr(
        production_roles,
        "compose_production_knowledge_worker",
        lambda **_kwargs: composition,
    )

    result = CliRunner().invoke(app, ["knowledge-worker", "--once"])

    assert result.exit_code == 0
    assert '"activation_state": "STANDBY"' in result.stdout
    assert worker.run_calls == 0
    assert composition.closed is True


def _worker_identity() -> ProductionDeploymentIdentity:
    return ProductionDeploymentIdentity(
        release_id="proofagent-2026.07.25-rc1",
        image_digest="a" * 64,
        deployment_slot="green",
        role="run_executor",
        activation_state=RoleActivationState.ACTIVE,
        schema_revision="0011_worker_role_leases",
        schema_compatible_from="0011_worker_role_leases",
        schema_compatible_through="0011_worker_role_leases",
        deployment_compatibility_manifest_sha256="b" * 64,
    )


def _activation(
    *,
    state: RoleActivationState = RoleActivationState.ACTIVE,
    slot: int = 2,
    owner_id: str | None = "executor-green",
    expires_at: datetime | None = NOW + timedelta(seconds=15),
) -> WorkerRoleActivation:
    owned = state in {RoleActivationState.ACTIVE, RoleActivationState.DRAINING}
    heartbeat_at = (
        NOW - timedelta(seconds=15)
        if owned and expires_at is not None and expires_at <= NOW
        else NOW
    )
    return WorkerRoleActivation(
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=slot,
        state=state,
        activation_epoch=4,
        owner_id=owner_id if owned else None,
        heartbeat_at=heartbeat_at if owned else None,
        lease_expires_at=expires_at if owned else None,
        updated_at=NOW,
    )


def test_worker_role_readiness_requires_exact_live_owner_but_allows_standby() -> None:
    current = _activation()

    assert worker_role_is_ready(
        configured_state=RoleActivationState.STANDBY,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=1,
        owner_id="executor-blue",
        current=current,
        now=NOW,
    )
    assert worker_role_is_ready(
        configured_state=RoleActivationState.ACTIVE,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=2,
        owner_id="executor-green",
        current=current,
        now=NOW,
    )
    assert not worker_role_is_ready(
        configured_state=RoleActivationState.ACTIVE,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=1,
        owner_id="executor-blue",
        current=current,
        now=NOW,
    )
    assert not worker_role_is_ready(
        configured_state=RoleActivationState.ACTIVE,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=2,
        owner_id="executor-green",
        current=_activation(expires_at=NOW),
        now=NOW,
    )


def test_worker_livez_is_process_only_and_readyz_is_sanitized() -> None:
    ready = [False]
    readiness = ProductionReadinessProbe(
        identity=_worker_identity(),
        checks={"postgresql": lambda: True, "role_lease": lambda: ready[0]},
    )
    client = TestClient(create_worker_health_application(readiness))

    assert client.get("/livez").status_code == 200
    unavailable = client.get("/readyz")
    assert unavailable.status_code == 503
    assert unavailable.json()["components"] == {
        "postgresql": "ready",
        "role_lease": "not_ready",
    }

    ready[0] = True
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["role"] == "run_executor"
    assert "owner_id" not in response.text


class InMemoryWorkerRoles:
    def __init__(self) -> None:
        self.current = _activation(
            state=RoleActivationState.STANDBY,
            slot=1,
            owner_id=None,
            expires_at=None,
        ).model_copy(update={"activation_epoch": 0})
        self.fail_heartbeat = False

    def get(self, _role: ProductionWorkerRole) -> WorkerRoleActivation:
        return self.current

    def activate(self, **kwargs) -> WorkerRoleActivation:
        assert kwargs["expected_epoch"] == self.current.activation_epoch
        self.current = WorkerRoleActivation(
            role=kwargs["role"],
            slot=kwargs["slot"],
            state=RoleActivationState.ACTIVE,
            activation_epoch=self.current.activation_epoch + 1,
            owner_id=kwargs["owner_id"],
            heartbeat_at=kwargs["now"],
            lease_expires_at=kwargs["now"]
            + timedelta(seconds=kwargs["lease_seconds"]),
            updated_at=kwargs["now"],
        )
        return self.current

    def heartbeat(self, activation, **kwargs) -> WorkerRoleActivation:
        if self.fail_heartbeat:
            raise WorkerRoleLeaseLostError("fenced")
        self.current = activation.model_copy(
            update={
                "heartbeat_at": kwargs["now"],
                "lease_expires_at": kwargs["now"]
                + timedelta(seconds=kwargs["lease_seconds"]),
                "updated_at": kwargs["now"],
            }
        )
        return self.current

    def begin_draining(self, activation, **kwargs) -> WorkerRoleActivation:
        self.current = activation.model_copy(
            update={
                "state": RoleActivationState.DRAINING,
                "updated_at": kwargs["now"],
            }
        )
        return self.current

    def resume_active(self, activation, **kwargs) -> WorkerRoleActivation:
        self.current = activation.model_copy(
            update={
                "state": RoleActivationState.ACTIVE,
                "updated_at": kwargs["now"],
            }
        )
        return self.current

    def release(self, activation, **kwargs) -> WorkerRoleActivation:
        self.current = activation.model_copy(
            update={
                "state": RoleActivationState.STANDBY,
                "owner_id": None,
                "heartbeat_at": None,
                "lease_expires_at": None,
                "updated_at": kwargs["now"],
            }
        )
        return self.current


def test_worker_role_controller_activates_renews_drains_and_releases() -> None:
    repository = InMemoryWorkerRoles()
    current = [NOW]
    controller = WorkerRoleLeaseController(
        repository=repository,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=2,
        owner_id="executor-green",
        configured_state=RoleActivationState.ACTIVE,
        lease_seconds=15,
        heartbeat_interval_seconds=5,
        clock=lambda: current[0],
    )

    activation = controller.start(background=False)
    assert activation is not None
    assert activation.activation_epoch == 1
    assert controller.check_ready()

    current[0] += timedelta(seconds=5)
    assert controller.heartbeat_once()
    draining = controller.begin_draining()
    assert draining is not None
    assert draining.state is RoleActivationState.DRAINING
    assert controller.check_ready()

    resumed = controller.resume_active()
    assert resumed is not None
    assert resumed.state is RoleActivationState.ACTIVE
    assert resumed.activation_epoch == activation.activation_epoch
    assert resumed.owner_id == activation.owner_id
    assert controller.can_claim()

    controller.release()
    assert repository.current.state is RoleActivationState.STANDBY
    assert not controller.check_ready()


def test_worker_role_controller_fails_readiness_after_heartbeat_fencing() -> None:
    repository = InMemoryWorkerRoles()
    controller = WorkerRoleLeaseController(
        repository=repository,
        role=ProductionWorkerRole.RUN_EXECUTOR,
        slot=2,
        owner_id="executor-green",
        configured_state=RoleActivationState.ACTIVE,
        lease_seconds=15,
        heartbeat_interval_seconds=5,
        clock=lambda: NOW,
    )
    controller.start(background=False)
    repository.fail_heartbeat = True

    assert not controller.heartbeat_once()
    assert not controller.check_ready()


def test_deployment_signals_drain_and_resume_without_stopping_worker(
    monkeypatch,
) -> None:
    calls: list[str] = []
    installed: dict[int, object] = {}

    class Controller:
        def begin_draining(self) -> None:
            calls.append("drain")

        def resume_active(self) -> None:
            calls.append("resume")

    monkeypatch.setattr("signal.getsignal", lambda signum: f"old-{signum}")
    monkeypatch.setattr(
        "signal.signal",
        lambda signum, handler: installed.__setitem__(signum, handler),
    )

    previous = install_worker_role_deployment_signals(Controller())
    drain_signum = int(signal.SIGUSR1)
    resume_signum = int(signal.SIGUSR2)
    drain_handler = installed[drain_signum]
    resume_handler = installed[resume_signum]
    assert callable(drain_handler)
    assert callable(resume_handler)
    drain_handler(drain_signum, None)
    resume_handler(resume_signum, None)

    assert calls == ["drain", "resume"]
    assert previous == {
        drain_signum: f"old-{signal.SIGUSR1}",
        resume_signum: f"old-{signal.SIGUSR2}",
    }
