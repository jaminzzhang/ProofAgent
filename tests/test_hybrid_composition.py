from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from proof_agent.bootstrap.composition import (
    HybridKnowledgeModelSettings,
    HybridKnowledgeTransportBundle,
    compose_hybrid_knowledge,
    compose_hybrid_knowledge_from_env,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import SchedulerLease
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    InMemoryKnowledgeModelWorkScheduler,
    PrivateKnowledgeModelWorkSchedulerClient,
)


class SchedulerTransport:
    def __init__(self) -> None:
        self.close_count = 0

    def acquire(self, **kwargs) -> SchedulerLease:
        del kwargs
        return SchedulerLease(work_id="work-1", lease_token="lease-1", queue_time_ms=0.0)

    def complete(self, *args, **kwargs) -> None:
        del args, kwargs

    def cancel(self, *args, **kwargs) -> None:
        del args, kwargs

    def close(self) -> None:
        self.close_count += 1


class ParserTransport:
    def parse(self, request, **kwargs):
        raise AssertionError((request, kwargs))

    def close(self) -> None:
        return None


class EmbeddingTransport:
    def embed(self, request, **kwargs):
        raise AssertionError((request, kwargs))

    def close(self) -> None:
        return None


class RerankerTransport:
    def rerank(self, request, **kwargs):
        raise AssertionError((request, kwargs))

    def close(self) -> None:
        return None


def _settings() -> HybridKnowledgeModelSettings:
    return HybridKnowledgeModelSettings(
        scheduler_endpoint="https://scheduler.internal",
        scheduler_namespace="insurance-knowledge",
        docling_endpoint="https://docling.internal",
        paddle_endpoint="https://paddle.internal",
        embedding_endpoint="https://embedding.internal",
        reranker_endpoint="https://reranker.internal",
    )


def _transports(scheduler: SchedulerTransport) -> HybridKnowledgeTransportBundle:
    return HybridKnowledgeTransportBundle(
        scheduler=scheduler,
        docling=ParserTransport(),
        paddle=ParserTransport(),
        embedding=EmbeddingTransport(),
        reranker=RerankerTransport(),
    )


def test_composition_injects_one_remote_scheduler_client_everywhere() -> None:
    scheduler_transport = SchedulerTransport()
    graph = compose_hybrid_knowledge(
        settings=_settings(),
        transports=_transports(scheduler_transport),
    )

    assert graph.parser.scheduler is graph.scheduler
    assert graph.parser.docling.scheduler is graph.scheduler
    assert graph.parser.paddle.scheduler is graph.scheduler
    assert graph.embedding.scheduler is graph.scheduler
    assert graph.reranker.scheduler is graph.scheduler
    assert graph.ingestion_worker.scheduler is graph.scheduler

    graph.close()
    graph.close()
    assert scheduler_transport.close_count == 1


def test_default_production_composition_never_builds_an_in_memory_queue() -> None:
    graph = compose_hybrid_knowledge(settings=_settings())
    try:
        assert isinstance(graph.scheduler, PrivateKnowledgeModelWorkSchedulerClient)
        assert not isinstance(graph.scheduler, InMemoryKnowledgeModelWorkScheduler)
    finally:
        graph.close()


def test_enabled_production_composition_fails_closed_without_complete_config() -> None:
    with pytest.raises(ValueError, match="PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE"):
        compose_hybrid_knowledge_from_env(
            {
                "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "1",
                "PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT": "https://scheduler.internal",
            }
        )


def test_disabled_local_composition_keeps_deterministic_path_unconfigured() -> None:
    assert compose_hybrid_knowledge_from_env({}) is None


def test_fastapi_lifespan_registers_and_closes_composition_once(monkeypatch) -> None:
    from proof_agent.delivery import api as delivery_api

    class Graph:
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    graph = Graph()
    monkeypatch.setattr(delivery_api, "compose_hybrid_knowledge_from_env", lambda: graph)
    app = FastAPI()
    app.include_router(delivery_api.router)

    with TestClient(app):
        assert app.state.hybrid_knowledge is graph

    assert graph.close_count == 1
