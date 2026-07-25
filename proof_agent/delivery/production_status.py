from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread

from proof_agent.contracts.health import ProductionDeploymentIdentity


@dataclass(frozen=True)
class ProductionReadiness:
    ready: bool
    identity: ProductionDeploymentIdentity
    components: Mapping[str, str]

    def public_payload(self) -> dict[str, object]:
        identity = self.identity
        return {
            "status": "ready" if self.ready else "not_ready",
            "release_id": identity.release_id,
            "image_digest": identity.image_digest,
            "deployment_slot": identity.deployment_slot,
            "role": identity.role,
            "activation_state": identity.activation_state.value.upper(),
            "schema": {
                "revision": identity.schema_revision,
                "compatible_from": identity.schema_compatible_from,
                "compatible_through": identity.schema_compatible_through,
            },
            "deployment_compatibility_manifest_sha256": (
                identity.deployment_compatibility_manifest_sha256
            ),
            "components": dict(sorted(self.components.items())),
        }


class ProductionReadinessProbe:
    """Run bounded deployment-owned dependency checks with sanitized results."""

    def __init__(
        self,
        *,
        identity: ProductionDeploymentIdentity,
        checks: Mapping[str, Callable[[], bool | None]],
    ) -> None:
        if not checks or any(not _safe_component(name) for name in checks):
            raise ValueError("production readiness checks require safe component names")
        self._identity = identity
        self._checks = dict(checks)

    def __call__(self) -> ProductionReadiness:
        components: dict[str, str] = {}
        for name, check in sorted(self._checks.items()):
            try:
                result = check()
            except Exception:
                components[name] = "unavailable"
            else:
                components[name] = "ready" if result is not False else "not_ready"
        return ProductionReadiness(
            ready=all(value == "ready" for value in components.values()),
            identity=self._identity,
            components=components,
        )


class PeriodicFreshnessProbe:
    """Cache only recent background successes for a bounded dependency check."""

    def __init__(
        self,
        *,
        check: Callable[[], bool | None],
        max_age: timedelta,
        interval: timedelta,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if max_age <= timedelta(0) or not timedelta(0) < interval <= max_age:
            raise ValueError("freshness probe timing is invalid")
        self._check = check
        self._max_age = max_age
        self._interval = interval
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_success: datetime | None = None
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = Thread(
                target=self._run,
                name="proof-agent-readiness-probe",
                daemon=True,
            )
            self._thread.start()

    def refresh(self) -> bool:
        try:
            succeeded = self._check() is not False
        except Exception:
            succeeded = False
        if succeeded:
            checked_at = self._clock()
            if checked_at.utcoffset() is None:
                raise ValueError("freshness probe clock must be timezone-aware")
            with self._lock:
                self._last_success = checked_at
        return succeeded

    def __call__(self) -> bool:
        now = self._clock()
        if now.utcoffset() is None:
            return False
        with self._lock:
            last_success = self._last_success
        return bool(
            last_success is not None
            and last_success <= now
            and now - last_success <= self._max_age
        )

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)

    def _run(self) -> None:
        self.refresh()
        while not self._stop.wait(self._interval.total_seconds()):
            self.refresh()


def _safe_component(value: str) -> bool:
    return bool(value) and len(value) <= 64 and all(
        char.islower() or char.isdigit() or char == "_" for char in value
    )


__all__ = [
    "PeriodicFreshnessProbe",
    "ProductionReadiness",
    "ProductionReadinessProbe",
]
