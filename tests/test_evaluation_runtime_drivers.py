from types import SimpleNamespace

import pytest

from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation import runtime_drivers


class _EntryPoints:
    def __init__(self, entries):
        self.entries = entries

    def select(self, *, group: str, name: str):
        return tuple(
            entry
            for entry in self.entries
            if entry.group == group and entry.name == name
        )


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
