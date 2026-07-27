from __future__ import annotations

from typing import Any

from proof_agent.bootstrap.production_roles import ProductionKnowledgeWorker


class _Worker:
    def __init__(self, outcomes: list[object | None]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def run_once(self) -> object | None:
        self.calls += 1
        return self.outcomes.pop(0) if self.outcomes else None


def test_production_knowledge_worker_polls_both_queues_without_starvation() -> None:
    hybrid: Any = _Worker(["hybrid-1", "hybrid-2"])
    metadata: Any = _Worker(["metadata-1", None])
    worker = ProductionKnowledgeWorker(
        hybrid_worker=hybrid,
        metadata_worker=metadata,
    )

    assert worker.run_once() == "hybrid-1"
    assert worker.run_once() == "metadata-1"
    assert worker.run_once() == "hybrid-2"
    assert hybrid.calls == 2
    assert metadata.calls == 1


def test_production_knowledge_worker_checks_second_queue_when_first_is_idle() -> None:
    hybrid: Any = _Worker([None])
    metadata: Any = _Worker(["metadata-1"])
    worker = ProductionKnowledgeWorker(
        hybrid_worker=hybrid,
        metadata_worker=metadata,
    )

    assert worker.run_once() == "metadata-1"
    assert hybrid.calls == 1
    assert metadata.calls == 1
