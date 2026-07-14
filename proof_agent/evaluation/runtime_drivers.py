"""Trusted deployment-driver resolution for executable Knowledge evaluations."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.metadata import entry_points
from typing import Any

from proof_agent.evaluation.errors import EvaluationInputError


CAPACITY_DRIVER_GROUP = "proof_agent.knowledge_capacity_drivers"
RECOVERY_DRIVER_GROUP = "proof_agent.knowledge_recovery_drivers"
SHADOW_DRIVER_GROUP = "proof_agent.knowledge_shadow_drivers"
ACCEPTANCE_DRIVER_GROUP = "proof_agent.knowledge_acceptance_drivers"
ACCEPTANCE_VERIFIER_GROUP = "proof_agent.knowledge_acceptance_verifiers"
OPERATIONS_PROVIDER_GROUP = "proof_agent.knowledge_operations_providers"
RELEASE_AUTHORITY_GROUP = "proof_agent.knowledge_release_authorities"


def load_release_authority(environ: Mapping[str, str]) -> Any:
    authority = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_RELEASE_AUTHORITY",
        group=RELEASE_AUTHORITY_GROUP,
    )
    _require_methods(authority, "verify_release_record")
    return authority


def load_operations_provider(environ: Mapping[str, str]) -> Any:
    provider = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_OPERATIONS_PROVIDER",
        group=OPERATIONS_PROVIDER_GROUP,
    )
    _require_methods(provider, "read_operations")
    return provider


def load_acceptance_driver(environ: Mapping[str, str]) -> Any:
    """Load the private evaluator that owns the sealed cohort execution."""

    driver = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_ACCEPTANCE_DRIVER",
        group=ACCEPTANCE_DRIVER_GROUP,
    )
    _require_methods(driver, "run_acceptance")
    return driver


def load_acceptance_verifier(environ: Mapping[str, str]) -> Any:
    """Load signature verification independently from the evaluator driver."""

    verifier = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_ACCEPTANCE_VERIFIER",
        group=ACCEPTANCE_VERIFIER_GROUP,
    )
    _require_methods(verifier, "verify_attestation")
    return verifier


def load_capacity_driver(environ: Mapping[str, str]) -> Any:
    """Load one installed capacity adapter; never import an arbitrary module path."""

    driver = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_CAPACITY_DRIVER",
        group=CAPACITY_DRIVER_GROUP,
    )
    _require_methods(driver, "run_sample", "run_ingestion")
    return driver


def load_recovery_driver(environ: Mapping[str, str]) -> Any:
    """Load one installed recovery adapter only inside an explicitly disposable scope."""

    if environ.get("HYBRID_TEST_DISPOSABLE_MARKER") != "1":
        raise EvaluationInputError(
            "recovery fault injection requires HYBRID_TEST_DISPOSABLE_MARKER=1"
        )
    if environ.get("HYBRID_TEST_REPOSITORY_MARKER") != "disposable-test":
        raise EvaluationInputError("recovery repository lacks the disposable-test marker")
    if environ.get("HYBRID_TEST_BUCKET_MARKER") != "disposable-test":
        raise EvaluationInputError("recovery bucket lacks the disposable-test marker")
    driver = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_RECOVERY_DRIVER",
        group=RECOVERY_DRIVER_GROUP,
    )
    _require_methods(
        driver,
        "prove_disposable_authority",
        "snapshot_pointers",
        "run_fault",
    )
    return driver


def load_shadow_driver(environ: Mapping[str, str]) -> Any:
    """Load the adapter that executes both pinned shadow bindings live."""

    driver = _load_driver(
        environ=environ,
        setting="PA_KNOWLEDGE_SHADOW_DRIVER",
        group=SHADOW_DRIVER_GROUP,
    )
    _require_methods(driver, "snapshot_active_pointers", "run_binding")
    return driver


def _load_driver(
    *,
    environ: Mapping[str, str],
    setting: str,
    group: str,
) -> Any:
    name = environ.get(setting, "").strip()
    if not name:
        raise EvaluationInputError(f"{setting} must name an installed evaluation driver")
    matches = tuple(entry_points().select(group=group, name=name))
    if len(matches) != 1:
        raise EvaluationInputError(
            f"{setting} must resolve exactly one trusted entry point; found {len(matches)}"
        )
    factory = matches[0].load()
    if not callable(factory):
        raise EvaluationInputError(f"{setting} entry point must be a driver factory")
    try:
        return factory(environ)
    except EvaluationInputError:
        raise
    except Exception as exc:
        raise EvaluationInputError(f"Unable to initialize {setting} driver") from exc


def _require_methods(driver: Any, *names: str) -> None:
    missing = tuple(name for name in names if not callable(getattr(driver, name, None)))
    if missing:
        raise EvaluationInputError(
            "Knowledge evaluation driver is missing required methods: " + ", ".join(missing)
        )


__all__ = [
    "ACCEPTANCE_DRIVER_GROUP",
    "ACCEPTANCE_VERIFIER_GROUP",
    "CAPACITY_DRIVER_GROUP",
    "OPERATIONS_PROVIDER_GROUP",
    "RELEASE_AUTHORITY_GROUP",
    "RECOVERY_DRIVER_GROUP",
    "SHADOW_DRIVER_GROUP",
    "load_capacity_driver",
    "load_operations_provider",
    "load_release_authority",
    "load_acceptance_driver",
    "load_acceptance_verifier",
    "load_recovery_driver",
    "load_shadow_driver",
]
