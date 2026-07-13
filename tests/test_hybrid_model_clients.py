from __future__ import annotations

from typing import Literal

import pytest

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    EmbeddingTransportResponse,
    ImmediateKnowledgeModelWorkScheduler,
    InMemoryKnowledgeModelWorkScheduler,
    KnowledgeModelCancellation,
    KnowledgeModelWorkCancelled,
    PrivateKnowledgeModelWorkSchedulerClient,
    PrivateEmbeddingClient,
    PrivateRerankerClient,
    RerankCandidate,
    RerankerTransportResponse,
    SchedulerLease,
)


class RecordingEmbeddingTransport:
    def __init__(self) -> None:
        self.requests = []

    def embed(
        self,
        request,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
    ) -> EmbeddingTransportResponse:
        self.requests.append(request)
        assert timeout_seconds > 0
        assert follow_redirects is False
        assert allow_runtime_downloads is False
        return EmbeddingTransportResponse(
            model_revision=request.model_revision,
            vectors=((0.1, 0.2),),
        )


def test_embedding_request_pins_revision_instruction_and_dimension() -> None:
    transport = RecordingEmbeddingTransport()
    scheduler = ImmediateKnowledgeModelWorkScheduler()
    client = PrivateEmbeddingClient(transport=transport, scheduler=scheduler)

    result = client.embed(
        texts=("insurance rule",),
        model_revision="qwen3-embedding-0.6b@sha256:model",
        instruction="Represent the insurance rule for retrieval",
        dimension=2,
        normalized=True,
        priority="offline",
        timeout_seconds=5.0,
    )

    assert transport.requests[0].model_revision.endswith("sha256:model")
    assert transport.requests[0].dimension == 2
    assert result.vectors == ((0.1, 0.2),)
    assert result.queue_time_ms >= 0
    assert result.service_time_ms >= 0


def test_embedding_rejects_malformed_vector_dimension() -> None:
    class WrongDimensionTransport(RecordingEmbeddingTransport):
        def embed(self, request, **kwargs) -> EmbeddingTransportResponse:
            del kwargs
            return EmbeddingTransportResponse(
                model_revision=request.model_revision,
                vectors=((0.1,),),
            )

    client = PrivateEmbeddingClient(
        transport=WrongDimensionTransport(),
        scheduler=ImmediateKnowledgeModelWorkScheduler(),
    )

    with pytest.raises(ValueError, match="dimension"):
        client.embed(
            texts=("insurance rule",),
            model_revision="qwen3-embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="offline",
            timeout_seconds=5.0,
        )


def test_cancelled_embedding_never_reaches_transport() -> None:
    transport = RecordingEmbeddingTransport()
    cancellation = KnowledgeModelCancellation()
    cancellation.cancel()
    client = PrivateEmbeddingClient(
        transport=transport,
        scheduler=ImmediateKnowledgeModelWorkScheduler(),
    )

    with pytest.raises(KnowledgeModelWorkCancelled):
        client.embed(
            texts=("insurance rule",),
            model_revision="qwen3-embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
            cancellation=cancellation,
        )

    assert transport.requests == []


def test_reranker_requires_exact_revision_and_candidate_echo() -> None:
    class WrongRevisionTransport:
        def rerank(self, request, **kwargs) -> RerankerTransportResponse:
            del kwargs
            return RerankerTransportResponse(
                model_revision="reranker@sha256:wrong",
                scores=((request.candidates[0].candidate_id, 0.9),),
            )

    client = PrivateRerankerClient(
        transport=WrongRevisionTransport(),
        scheduler=ImmediateKnowledgeModelWorkScheduler(),
    )

    with pytest.raises(ValueError, match="model_revision"):
        client.rerank(
            query="waiting period",
            candidates=(RerankCandidate(candidate_id="rule-1", text="Thirty days."),),
            model_revision="reranker@sha256:model",
            max_input_tokens=2048,
            priority="online",
            timeout_seconds=5.0,
        )


def test_embedding_rejects_wrong_revision_echo() -> None:
    class WrongRevisionTransport(RecordingEmbeddingTransport):
        def embed(self, request, **kwargs) -> EmbeddingTransportResponse:
            del request, kwargs
            return EmbeddingTransportResponse(
                model_revision="embedding@sha256:wrong",
                vectors=((0.1, 0.2),),
            )

    client = PrivateEmbeddingClient(
        transport=WrongRevisionTransport(),
        scheduler=ImmediateKnowledgeModelWorkScheduler(),
    )
    with pytest.raises(ValueError, match="model_revision"):
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="offline",
            timeout_seconds=5.0,
        )


def test_remote_scheduler_timeout_does_not_start_service_transport() -> None:
    class SlowQueueTransport:
        def __init__(self) -> None:
            self.cancelled = []

        def acquire(self, **kwargs) -> SchedulerLease:
            assert kwargs["follow_redirects"] is False
            return SchedulerLease(
                work_id="work-1",
                lease_token="lease-1",
                queue_time_ms=2000.0,
            )

        def complete(self, *args, **kwargs) -> None:
            raise AssertionError("timed-out work cannot complete")

        def cancel(self, endpoint, namespace, lease, **kwargs) -> None:
            self.cancelled.append((endpoint, namespace, lease.work_id, kwargs))

        def close(self) -> None:
            return None

    scheduler_transport = SlowQueueTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        transport=scheduler_transport,
    )
    embedding_transport = RecordingEmbeddingTransport()
    client = PrivateEmbeddingClient(transport=embedding_transport, scheduler=scheduler)

    with pytest.raises(TimeoutError, match="queue"):
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=1.0,
        )

    assert embedding_transport.requests == []
    assert scheduler_transport.cancelled[0][:3] == (
        "https://scheduler.internal",
        "insurance-knowledge",
        "work-1",
    )


def test_test_only_in_memory_scheduler_claims_online_before_offline() -> None:
    scheduler = InMemoryKnowledgeModelWorkScheduler()
    offline = scheduler.submit(kind="ocr", priority="offline")
    online = scheduler.submit(kind="rerank", priority="online")

    assert scheduler.claim_next() is online
    assert offline.state == "queued"


def test_remote_scheduler_cancellation_releases_lease_before_service_call() -> None:
    cancellation = KnowledgeModelCancellation()

    class CancellingSchedulerTransport:
        def __init__(self) -> None:
            self.cancelled = 0

        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            cancellation.cancel()
            return SchedulerLease(
                work_id="work-cancelled",
                lease_token="lease-cancelled",
                queue_time_ms=1.0,
            )

        def complete(self, *args, **kwargs) -> None:
            raise AssertionError((args, kwargs))

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            self.cancelled += 1

        def close(self) -> None:
            return None

    scheduler_transport = CancellingSchedulerTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        transport=scheduler_transport,
    )
    embedding_transport = RecordingEmbeddingTransport()
    client = PrivateEmbeddingClient(transport=embedding_transport, scheduler=scheduler)

    with pytest.raises(KnowledgeModelWorkCancelled):
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
            cancellation=cancellation,
        )

    assert embedding_transport.requests == []
    assert scheduler_transport.cancelled == 1
