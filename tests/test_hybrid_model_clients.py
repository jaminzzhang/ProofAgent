from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from typing import Literal

import pytest

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    EmbeddingTransportResponse,
    ImmediateKnowledgeModelWorkScheduler,
    InMemoryKnowledgeModelWorkScheduler,
    KnowledgeModelCancellation,
    KnowledgeModelWorkCancelled,
    PrivateKnowledgeModelWorkSchedulerClient,
    PrivateHostPolicy,
    PrivateEmbeddingClient,
    PrivateRerankerClient,
    RerankCandidate,
    RerankerTransportResponse,
    SchedulerLease,
    decode_bounded_json_bytes,
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
        cancellation: KnowledgeModelCancellation,
    ) -> EmbeddingTransportResponse:
        self.requests.append(request)
        assert timeout_seconds > 0
        assert follow_redirects is False
        assert allow_runtime_downloads is False
        assert cancellation.is_cancelled() is False
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
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
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


def test_scheduler_cancel_cleanup_failure_preserves_primary_timeout() -> None:
    class CleanupFailureTransport:
        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            return SchedulerLease(
                work_id="work-timeout",
                lease_token="lease-timeout",
                queue_time_ms=2000.0,
            )

        def complete(self, *args, **kwargs) -> None:
            raise AssertionError((args, kwargs))

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            raise ConnectionError("scheduler unavailable")

        def close(self) -> None:
            return None

    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=CleanupFailureTransport(),
    )
    client = PrivateEmbeddingClient(
        transport=RecordingEmbeddingTransport(),
        scheduler=scheduler,
    )

    with pytest.raises(TimeoutError, match="queue") as caught:
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=1.0,
        )

    assert any("cleanup also failed" in note for note in caught.value.__notes__)


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
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
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


def test_private_model_json_rejects_excessive_depth_before_contract_validation() -> None:
    payload = b'{"x":' * 40 + b"null" + b"}" * 40
    with pytest.raises(ValueError, match="depth"):
        decode_bounded_json_bytes(payload)


def test_private_model_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="bounded JSON"):
        decode_bounded_json_bytes(b'{"vectors":[NaN]}')


def test_cancellation_during_blocked_acquire_cancels_late_lease_without_service() -> None:
    acquire_started = Event()
    lease_cancelled = Event()

    class BlockedAcquireTransport:
        def __init__(self) -> None:
            self.completed = 0

        def acquire(self, *, cancellation, **kwargs) -> SchedulerLease:
            del kwargs
            acquire_started.set()
            while not cancellation.is_cancelled():
                sleep(0.005)
            return SchedulerLease(
                work_id="work-mid-acquire",
                lease_token="lease-mid-acquire",
                queue_time_ms=1.0,
            )

        def complete(self, *args, **kwargs) -> None:
            del args, kwargs
            self.completed += 1

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            lease_cancelled.set()

        def close(self) -> None:
            return None

    scheduler_transport = BlockedAcquireTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=scheduler_transport,
    )
    embedding_transport = RecordingEmbeddingTransport()
    client = PrivateEmbeddingClient(transport=embedding_transport, scheduler=scheduler)
    cancellation = KnowledgeModelCancellation()

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            client.embed,
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
            cancellation=cancellation,
        )
        assert acquire_started.wait(timeout=1)
        started = monotonic()
        cancellation.cancel()
        with pytest.raises(KnowledgeModelWorkCancelled):
            result.result(timeout=1)
        assert monotonic() - started < 0.5

    assert lease_cancelled.wait(timeout=1)
    assert embedding_transport.requests == []
    assert scheduler_transport.completed == 0


def test_cancellation_during_model_operation_never_completes_remote_lease() -> None:
    service_started = Event()
    service_stopped = Event()

    class SchedulerTransport:
        def __init__(self) -> None:
            self.completed = 0
            self.cancelled = 0

        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            return SchedulerLease(
                work_id="work-mid-service",
                lease_token="lease-mid-service",
                queue_time_ms=1.0,
            )

        def complete(self, *args, **kwargs) -> None:
            del args, kwargs
            self.completed += 1

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            self.cancelled += 1

        def close(self) -> None:
            return None

    class BlockingEmbeddingTransport(RecordingEmbeddingTransport):
        def embed(self, request, *, cancellation, **kwargs) -> EmbeddingTransportResponse:
            del kwargs
            service_started.set()
            while not cancellation.is_cancelled():
                sleep(0.005)
            service_stopped.set()
            return EmbeddingTransportResponse(
                model_revision=request.model_revision,
                vectors=((0.1, 0.2),),
            )

    scheduler_transport = SchedulerTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=scheduler_transport,
    )
    client = PrivateEmbeddingClient(
        transport=BlockingEmbeddingTransport(),
        scheduler=scheduler,
    )
    cancellation = KnowledgeModelCancellation()

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(
            client.embed,
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
            cancellation=cancellation,
        )
        assert service_started.wait(timeout=1)
        cancellation.cancel()
        with pytest.raises(KnowledgeModelWorkCancelled):
            result.result(timeout=1)

    assert service_stopped.wait(timeout=1)
    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0


def test_scheduler_close_cancels_active_call_before_closing_transport() -> None:
    service_started = Event()
    service_stopped = Event()

    class CloseAwareSchedulerTransport:
        def __init__(self) -> None:
            self.completed = 0
            self.cancelled = 0
            self.closed = 0

        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            return SchedulerLease(
                work_id="work-close",
                lease_token="lease-close",
                queue_time_ms=0.0,
            )

        def complete(self, *args, **kwargs) -> None:
            del args, kwargs
            self.completed += 1

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            self.cancelled += 1

        def close(self) -> None:
            assert service_stopped.is_set()
            self.closed += 1

    class ClosingEmbeddingTransport(RecordingEmbeddingTransport):
        def embed(self, request, *, cancellation, **kwargs) -> EmbeddingTransportResponse:
            del kwargs
            service_started.set()
            while not cancellation.is_cancelled():
                sleep(0.005)
            service_stopped.set()
            return EmbeddingTransportResponse(
                model_revision=request.model_revision,
                vectors=((0.1, 0.2),),
            )

    scheduler_transport = CloseAwareSchedulerTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=scheduler_transport,
    )
    client = PrivateEmbeddingClient(
        transport=ClosingEmbeddingTransport(),
        scheduler=scheduler,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        call = executor.submit(
            client.embed,
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
        )
        assert service_started.wait(timeout=1)
        closed = executor.submit(scheduler.close)
        closed.result(timeout=1)
        with pytest.raises(KnowledgeModelWorkCancelled):
            call.result(timeout=1)

    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0
    assert scheduler_transport.closed == 1


def test_concurrent_scheduler_close_closes_transport_once() -> None:
    close_started = Event()
    release_close = Event()

    class SlowCloseTransport:
        def __init__(self) -> None:
            self.close_count = 0

        def acquire(self, **kwargs) -> SchedulerLease:
            raise AssertionError(kwargs)

        def complete(self, *args, **kwargs) -> None:
            raise AssertionError((args, kwargs))

        def cancel(self, *args, **kwargs) -> None:
            raise AssertionError((args, kwargs))

        def close(self) -> None:
            self.close_count += 1
            close_started.set()
            assert release_close.wait(timeout=1)

    transport = SlowCloseTransport()
    scheduler = PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=transport,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scheduler.close)
        assert close_started.wait(timeout=1)
        second = executor.submit(scheduler.close)
        sleep(0.02)
        release_close.set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert transport.close_count == 1
