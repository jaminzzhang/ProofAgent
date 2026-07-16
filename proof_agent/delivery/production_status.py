from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ProductionReadiness:
    ready: bool
    components: Mapping[str, str]

    def public_payload(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "components": dict(sorted(self.components.items())),
        }


class ProductionReadinessProbe:
    """Run bounded deployment-owned dependency checks with sanitized results."""

    def __init__(self, checks: Mapping[str, Callable[[], bool | None]]) -> None:
        if not checks or any(not _safe_component(name) for name in checks):
            raise ValueError("production readiness checks require safe component names")
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
            components=components,
        )


def _safe_component(value: str) -> bool:
    return bool(value) and len(value) <= 64 and all(
        char.islower() or char.isdigit() or char == "_" for char in value
    )


__all__ = ["ProductionReadiness", "ProductionReadinessProbe"]
