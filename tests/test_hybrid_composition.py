from __future__ import annotations

import pytest
from typing import Any, cast
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
        allowed_hosts=(
            "scheduler.internal",
            "docling.internal",
            "paddle.internal",
            "embedding.internal",
            "reranker.internal",
        ),
        allowed_cidrs=("10.0.0.0/8",),
        parser_revision="docling+paddle@sha256:parser",
        model_digests=("sha256:model",),
        parser_configuration_sha256="b" * 64,
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


def test_publication_service_borrows_graph_embedding_and_never_closes_scheduler() -> None:
    scheduler_transport = SchedulerTransport()
    graph = compose_hybrid_knowledge(
        settings=_settings(),
        transports=_transports(scheduler_transport),
    )
    service = graph.compose_publication_service(
        repository=cast(Any, object()),
        artifact_store=cast(Any, object()),
        index=cast(Any, object()),
    )
    assert service.embedding is graph.embedding
    assert service.embedding.scheduler is graph.scheduler
    service.close()
    assert scheduler_transport.close_count == 0
    graph.close()
    assert scheduler_transport.close_count == 1


def test_retrieval_provider_borrows_graph_online_clients_and_shared_scheduler() -> None:
    scheduler_transport = SchedulerTransport()
    graph = compose_hybrid_knowledge(
        settings=_settings(),
        transports=_transports(scheduler_transport),
    )

    provider = graph.compose_retrieval_provider(
        authority=cast(Any, object()),
        index=cast(Any, object()),
    )

    assert provider.embedding is graph.embedding
    assert provider.reranker is graph.reranker
    assert provider.embedding.scheduler is graph.scheduler
    assert provider.reranker.scheduler is graph.scheduler
    assert graph.parser.scheduler is graph.scheduler
    assert graph.ingestion_worker.scheduler is graph.scheduler
    graph.close()


def test_default_production_composition_never_builds_an_in_memory_queue() -> None:
    graph = compose_hybrid_knowledge(settings=_settings())
    try:
        assert isinstance(graph.scheduler, PrivateKnowledgeModelWorkSchedulerClient)
        assert not isinstance(graph.scheduler, InMemoryKnowledgeModelWorkScheduler)
    finally:
        graph.close()


def test_composition_closes_every_transport_and_retries_only_failed_closer() -> None:
    class FailingParserTransport(ParserTransport):
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1
            if self.close_count == 1:
                raise RuntimeError("close failed")

    class CountingParserTransport(ParserTransport):
        def __init__(self) -> None:
            self.close_count = 0

        def close(self) -> None:
            self.close_count += 1

    scheduler_transport = SchedulerTransport()
    failing = FailingParserTransport()
    paddle = CountingParserTransport()
    embedding = EmbeddingTransport()
    reranker = RerankerTransport()
    graph = compose_hybrid_knowledge(
        settings=_settings(),
        transports=HybridKnowledgeTransportBundle(
            scheduler=scheduler_transport,
            docling=failing,
            paddle=paddle,
            embedding=embedding,
            reranker=reranker,
        ),
    )

    with pytest.raises(ExceptionGroup, match="composition close"):
        graph.close()
    assert scheduler_transport.close_count == 1
    assert paddle.close_count == 1

    graph.close()
    assert failing.close_count == 2
    assert scheduler_transport.close_count == 1
    assert paddle.close_count == 1


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


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://8.8.8.8",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://example.com",
        "https://user:password@scheduler.internal",
        "https://scheduler.internal/private/path",
        "https://scheduler.internal?token=value",
        "https://scheduler.internal#fragment",
        "https://scheduler.internal:not-a-port",
    ),
)
def test_private_scheduler_endpoint_rejects_ssrf_and_secret_bearing_origins(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        HybridKnowledgeModelSettings(
            scheduler_endpoint=endpoint,
            scheduler_namespace="insurance-knowledge",
            docling_endpoint="https://docling.internal",
            paddle_endpoint="https://paddle.internal",
            embedding_endpoint="https://embedding.internal",
            reranker_endpoint="https://reranker.internal",
            allowed_hosts=(
                "scheduler.internal",
                "docling.internal",
                "paddle.internal",
                "embedding.internal",
                "reranker.internal",
            ),
            allowed_cidrs=("10.0.0.0/8",),
            parser_revision="docling+paddle@sha256:parser",
            model_digests=("sha256:model",),
            parser_configuration_sha256="b" * 64,
        )


def test_enabled_composition_requires_explicit_private_host_allowlist() -> None:
    with pytest.raises(ValueError, match="PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS"):
        compose_hybrid_knowledge_from_env(
            {
                "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "1",
                "PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT": "https://scheduler.internal",
                "PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE": "insurance-knowledge",
                "PA_KNOWLEDGE_DOCLING_ENDPOINT": "https://docling.internal",
                "PA_KNOWLEDGE_PADDLE_ENDPOINT": "https://paddle.internal",
                "PA_KNOWLEDGE_EMBEDDING_ENDPOINT": "https://embedding.internal",
                "PA_KNOWLEDGE_RERANKER_ENDPOINT": "https://reranker.internal",
            }
        )


def test_enabled_composition_requires_explicit_private_cidr_allowlist() -> None:
    with pytest.raises(ValueError, match="PA_KNOWLEDGE_MODEL_ALLOWED_CIDRS"):
        compose_hybrid_knowledge_from_env(
            {
                "PA_HYBRID_KNOWLEDGE_MODELS_ENABLED": "1",
                "PA_KNOWLEDGE_MODEL_SCHEDULER_ENDPOINT": "https://scheduler.internal",
                "PA_KNOWLEDGE_MODEL_SCHEDULER_NAMESPACE": "insurance-knowledge",
                "PA_KNOWLEDGE_DOCLING_ENDPOINT": "https://docling.internal",
                "PA_KNOWLEDGE_PADDLE_ENDPOINT": "https://paddle.internal",
                "PA_KNOWLEDGE_EMBEDDING_ENDPOINT": "https://embedding.internal",
                "PA_KNOWLEDGE_RERANKER_ENDPOINT": "https://reranker.internal",
                "PA_KNOWLEDGE_MODEL_ALLOWED_HOSTS": ",".join(_settings().allowed_hosts),
            }
        )


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
