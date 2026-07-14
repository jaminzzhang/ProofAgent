from types import SimpleNamespace

import pytest

from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation import runtime_drivers


class _EntryPoints:
    def __init__(self, entries):
        self.entries = entries

    def select(self, *, group: str, name: str):
        return tuple(entry for entry in self.entries if entry.group == group and entry.name == name)


def test_capacity_driver_resolves_one_trusted_entry_point(monkeypatch) -> None:
    driver = SimpleNamespace(run_sample=lambda *args: None, run_ingestion=lambda: None)
    entry = SimpleNamespace(
        group=runtime_drivers.CAPACITY_DRIVER_GROUP,
        name="private-capacity",
        load=lambda: lambda environ: driver,
    )
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints((entry,)))

    loaded = runtime_drivers.load_capacity_driver(
        {"PA_KNOWLEDGE_CAPACITY_DRIVER": "private-capacity"}
    )

    assert loaded is driver


def test_shadow_driver_resolves_live_execution_methods(monkeypatch) -> None:
    driver = SimpleNamespace(
        snapshot_active_pointers=lambda: None,
        run_binding=lambda **kwargs: None,
    )
    entry = SimpleNamespace(
        group=runtime_drivers.SHADOW_DRIVER_GROUP,
        name="private-shadow",
        load=lambda: lambda environ: driver,
    )
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints((entry,)))

    loaded = runtime_drivers.load_shadow_driver({"PA_KNOWLEDGE_SHADOW_DRIVER": "private-shadow"})

    assert loaded is driver


def test_acceptance_driver_and_verifier_are_resolved_from_separate_groups(
    monkeypatch,
) -> None:
    driver = SimpleNamespace(run_acceptance=lambda **kwargs: None)
    verifier = SimpleNamespace(verify_attestation=lambda attestation: True)
    entries = (
        SimpleNamespace(
            group=runtime_drivers.ACCEPTANCE_DRIVER_GROUP,
            name="private-evaluator",
            load=lambda: lambda environ: driver,
        ),
        SimpleNamespace(
            group=runtime_drivers.ACCEPTANCE_VERIFIER_GROUP,
            name="corporate-trust-store",
            load=lambda: lambda environ: verifier,
        ),
    )
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints(entries))

    assert (
        runtime_drivers.load_acceptance_driver(
            {"PA_KNOWLEDGE_ACCEPTANCE_DRIVER": "private-evaluator"}
        )
        is driver
    )
    assert (
        runtime_drivers.load_acceptance_verifier(
            {"PA_KNOWLEDGE_ACCEPTANCE_VERIFIER": "corporate-trust-store"}
        )
        is verifier
    )


def test_operations_provider_resolves_production_read_method(monkeypatch) -> None:
    provider = SimpleNamespace(read_operations=lambda source_id: None)
    entry = SimpleNamespace(
        group=runtime_drivers.OPERATIONS_PROVIDER_GROUP,
        name="private-http",
        load=lambda: lambda environ: provider,
    )
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints((entry,)))

    assert (
        runtime_drivers.load_operations_provider(
            {"PA_KNOWLEDGE_OPERATIONS_PROVIDER": "private-http"}
        )
        is provider
    )


def test_release_evidence_authority_resolves_independent_verification_method(
    monkeypatch,
) -> None:
    authority = SimpleNamespace(verify_release_record=lambda record: True)
    entry = SimpleNamespace(
        group=runtime_drivers.RELEASE_AUTHORITY_GROUP,
        name="private-http",
        load=lambda: lambda environ: authority,
    )
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints((entry,)))

    assert (
        runtime_drivers.load_release_authority({"PA_KNOWLEDGE_RELEASE_AUTHORITY": "private-http"})
        is authority
    )


def test_recovery_driver_requires_both_disposable_authority_markers(monkeypatch) -> None:
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints(()))

    with pytest.raises(EvaluationInputError, match="bucket lacks"):
        runtime_drivers.load_recovery_driver(
            {
                "HYBRID_TEST_DISPOSABLE_MARKER": "1",
                "HYBRID_TEST_REPOSITORY_MARKER": "disposable-test",
                "PA_KNOWLEDGE_RECOVERY_DRIVER": "private-recovery",
            }
        )


def test_driver_name_cannot_be_an_arbitrary_module_path(monkeypatch) -> None:
    monkeypatch.setattr(runtime_drivers, "entry_points", lambda: _EntryPoints(()))

    with pytest.raises(EvaluationInputError, match="trusted entry point"):
        runtime_drivers.load_capacity_driver(
            {"PA_KNOWLEDGE_CAPACITY_DRIVER": "some.module:factory"}
        )
