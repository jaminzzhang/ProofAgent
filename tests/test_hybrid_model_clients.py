from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, enumerate as enumerate_threads
from time import monotonic, sleep
from typing import Literal

import pytest

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    EmbeddingTransportResponse,
    HttpEmbeddingTransport,
    ImmediateKnowledgeModelWorkScheduler,
    InMemoryKnowledgeModelWorkScheduler,
    KnowledgeModelCancellation,
    KnowledgeModelWorkCancelled,
    PrivateKnowledgeModelWorkSchedulerClient,
    PrivateHostPolicy,
    PrivateEmbeddingClient,
    PrivateNetworkPolicy,
    PrivateRerankerClient,
    RerankCandidate,
    RerankerTransportResponse,
    SchedulerLease,
    _PinnedNetworkBackend,
    decode_bounded_json_bytes,
)


class StaticResolver:
    def __init__(self, answers: tuple[str, ...] = ("10.20.30.40",)) -> None:
        self.answers = answers
        self.calls: list[tuple[str, int, float]] = []

    def resolve(self, hostname, port, *, timeout_seconds):
        self.calls.append((hostname, port, timeout_seconds))
        return self.answers

    def close(self) -> None:
        return None


class RecordingSchedulerTransport:
    def __init__(self) -> None:
        self.completed = 0
        self.cancelled = 0

    def acquire(self, **kwargs) -> SchedulerLease:
        del kwargs
        return SchedulerLease(
            work_id="work-validation",
            lease_token="lease-validation",
            queue_time_ms=0.0,
        )

    def complete(self, *args, **kwargs) -> None:
        del args, kwargs
        self.completed += 1

    def cancel(self, *args, **kwargs) -> None:
        del args, kwargs
        self.cancelled += 1

    def close(self) -> None:
        return None


def remote_scheduler(transport, **kwargs) -> PrivateKnowledgeModelWorkSchedulerClient:
    return PrivateKnowledgeModelWorkSchedulerClient(
        endpoint="https://scheduler.internal",
        namespace="insurance-knowledge",
        allowed_hosts=PrivateHostPolicy.from_entries(("scheduler.internal",)),
        transport=transport,
        **kwargs,
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


def test_invalid_embedding_response_cancels_without_completing_remote_lease() -> None:
    class WrongDimensionTransport(RecordingEmbeddingTransport):
        def embed(self, request, **kwargs) -> EmbeddingTransportResponse:
            del kwargs
            return EmbeddingTransportResponse(
                model_revision=request.model_revision,
                vectors=((0.1,),),
            )

    scheduler_transport = RecordingSchedulerTransport()
    scheduler = remote_scheduler(scheduler_transport)
    client = PrivateEmbeddingClient(
        transport=WrongDimensionTransport(),
        scheduler=scheduler,
    )

    with pytest.raises(ValueError, match="dimension"):
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="offline",
            timeout_seconds=5.0,
        )

    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0
    scheduler.close()


def test_invalid_reranker_response_cancels_without_completing_remote_lease() -> None:
    class WrongRevisionTransport:
        def rerank(self, request, **kwargs) -> RerankerTransportResponse:
            del request, kwargs
            return RerankerTransportResponse(
                model_revision="reranker@sha256:wrong",
                scores=(("rule-1", 0.9),),
            )

    scheduler_transport = RecordingSchedulerTransport()
    scheduler = remote_scheduler(scheduler_transport)
    client = PrivateRerankerClient(
        transport=WrongRevisionTransport(),
        scheduler=scheduler,
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

    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0
    scheduler.close()


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


def test_blocked_scheduler_cancel_is_bounded_and_cannot_hold_shutdown_open() -> None:
    cancel_started = Event()
    release_cancel = Event()

    class BlockedCancelTransport(RecordingSchedulerTransport):
        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            return SchedulerLease(
                work_id="work-blocked-cancel",
                lease_token="lease-blocked-cancel",
                queue_time_ms=2000.0,
            )

        def cancel(self, *args, **kwargs) -> None:
            del args, kwargs
            cancel_started.set()
            assert release_cancel.wait(timeout=2)

    scheduler_transport = BlockedCancelTransport()
    scheduler = remote_scheduler(
        scheduler_transport,
        active_lease_limit=2,
        online_reserved_leases=1,
    )
    client = PrivateEmbeddingClient(
        transport=RecordingEmbeddingTransport(),
        scheduler=scheduler,
    )

    started = monotonic()
    with pytest.raises(TimeoutError, match="queue") as caught:
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="offline",
            timeout_seconds=1.0,
        )
    assert monotonic() - started < 0.75
    assert cancel_started.is_set()
    assert any("250 ms" in note for note in caught.value.__notes__)
    with pytest.raises(RuntimeError, match="offline lease admission is saturated"):
        scheduler.submit_and_wait(
            kind="ocr",
            priority="offline",
            timeout_seconds=1.0,
            operation=lambda _remaining, _cancellation: "must-not-run",
        )

    started = monotonic()
    scheduler.close()
    assert monotonic() - started < 0.75
    release_cancel.set()


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


@pytest.mark.parametrize(
    "answers",
    [
        (),
        ("203.0.113.10",),
        ("127.0.0.1",),
        ("169.254.10.20",),
        ("10.20.30.40", "203.0.113.10"),
    ],
)
def test_private_network_policy_rejects_empty_public_special_and_mixed_dns_answers(
    answers: tuple[str, ...],
) -> None:
    policy = PrivateNetworkPolicy.from_entries(("10.0.0.0/8",))

    with pytest.raises(ConnectionError):
        policy.resolve_connection(
            hostname="embedding.internal",
            port=443,
            resolver=StaticResolver(answers),
            timeout_seconds=5.0,
        )


def test_private_network_policy_rejects_resolution_errors_and_unsafe_cidrs() -> None:
    class FailingResolver(StaticResolver):
        def resolve(self, hostname, port, *, timeout_seconds):
            del hostname, port, timeout_seconds
            raise OSError("resolver unavailable")

    with pytest.raises(ValueError, match="RFC1918"):
        PrivateNetworkPolicy.from_entries(("203.0.113.0/24",))
    with pytest.raises(ValueError, match="must be configured"):
        PrivateNetworkPolicy.from_entries(())
    with pytest.raises(ConnectionError, match="failed closed"):
        PrivateNetworkPolicy.from_entries(("10.0.0.0/8",)).resolve_connection(
            hostname="embedding.internal",
            port=443,
            resolver=FailingResolver(),
            timeout_seconds=5.0,
        )


def test_pinned_backend_connects_validated_ip_once_and_preserves_host_and_tls_name() -> None:
    import httpcore

    class RebindingResolver(StaticResolver):
        def resolve(self, hostname, port, *, timeout_seconds):
            self.calls.append((hostname, port, timeout_seconds))
            if len(self.calls) == 1:
                return ("10.20.30.40",)
            return ("203.0.113.10",)

    class MemoryStream:
        def __init__(self) -> None:
            self.writes: list[bytes] = []
            self.server_hostname: str | None = None
            self._response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"

        def read(self, max_bytes, timeout=None):
            del max_bytes, timeout
            response, self._response = self._response, b""
            return response

        def write(self, buffer, timeout=None):
            del timeout
            self.writes.append(buffer)

        def close(self):
            return None

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            del ssl_context, timeout
            self.server_hostname = server_hostname
            return self

        def get_extra_info(self, info):
            if info == "is_readable":
                return False
            return None

    class MemoryBackend:
        def __init__(self) -> None:
            self.stream = MemoryStream()
            self.hosts: list[str] = []

        def connect_tcp(self, *, host, **kwargs):
            del kwargs
            self.hosts.append(host)
            return self.stream

    resolver = RebindingResolver()
    connector = MemoryBackend()
    backend = _PinnedNetworkBackend(
        policy=PrivateNetworkPolicy.from_entries(("10.0.0.0/8",)),
        resolver=resolver,
        backend=connector,
    )
    pool = httpcore.ConnectionPool(network_backend=backend)

    response = pool.handle_request(
        httpcore.Request(
            method=b"POST",
            url=b"https://embedding.internal/v1/embeddings",
            headers=[(b"Host", b"embedding.internal"), (b"Content-Length", b"2")],
            content=b"{}",
        )
    )
    response.read()
    response.close()
    pool.close()

    assert resolver.calls == [("embedding.internal", 443, 2.0)]
    assert connector.hosts == ["10.20.30.40"]
    assert connector.stream.server_hostname == "embedding.internal"
    assert b"Host: embedding.internal\r\n" in b"".join(connector.stream.writes)


def test_pinned_http_transport_conforms_to_installed_public_httpx_contract(monkeypatch) -> None:
    import httpx

    class Stream:
        def __init__(self) -> None:
            self.response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"

        def read(self, max_bytes, timeout=None):
            del max_bytes, timeout
            response, self.response = self.response, b""
            return response

        def write(self, buffer, timeout=None):
            del buffer, timeout

        def close(self):
            return None

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            del ssl_context, server_hostname, timeout
            return self

        def get_extra_info(self, info):
            return False if info == "is_readable" else None

    class Backend:
        def connect_tcp(self, **kwargs):
            del kwargs
            return Stream()

    transport = HttpEmbeddingTransport(
        endpoint="https://embedding.internal",
        allowed_hosts=PrivateHostPolicy.from_entries(("embedding.internal",)),
        network_policy=PrivateNetworkPolicy.from_entries(("10.0.0.0/8",)),
        resolver=StaticResolver(),
    )
    monkeypatch.setattr(transport._httpcore, "SyncBackend", Backend)
    client = transport._create_pinned_client()
    try:
        assert isinstance(client._transport, httpx.BaseTransport)
        assert not isinstance(client._transport, httpx.HTTPTransport)
        assert callable(client._transport.handle_request)
        assert callable(client._transport.close)
        response = client.post("https://embedding.internal/conformance", content=b"{}")
        assert response.status_code == 200
        assert response.json() == {}
    finally:
        client.close()
        transport.close()


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


def test_cancellation_during_blocked_complete_cancels_without_success() -> None:
    complete_started = Event()
    cancellation = KnowledgeModelCancellation()

    class BlockedCompleteTransport(RecordingSchedulerTransport):
        def complete(self, *args, cancellation, **kwargs) -> None:
            del args, kwargs
            complete_started.set()
            while not cancellation.is_cancelled():
                sleep(0.005)
            cancellation.raise_if_cancelled()

    scheduler_transport = BlockedCompleteTransport()
    scheduler = remote_scheduler(scheduler_transport)
    client = PrivateEmbeddingClient(
        transport=RecordingEmbeddingTransport(),
        scheduler=scheduler,
    )

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
        assert complete_started.wait(timeout=1)
        cancellation.cancel()
        with pytest.raises(KnowledgeModelWorkCancelled):
            result.result(timeout=1)

    assert scheduler_transport.cancelled == 1
    assert scheduler_transport.completed == 0
    scheduler.close()


def test_acknowledged_complete_is_only_terminal_state_when_cancellation_races() -> None:
    class AcknowledgingCompleteTransport(RecordingSchedulerTransport):
        def complete(self, *args, cancellation, **kwargs) -> None:
            del args, kwargs
            self.completed += 1
            cancellation.cancel()

    scheduler_transport = AcknowledgingCompleteTransport()
    scheduler = remote_scheduler(scheduler_transport)
    client = PrivateEmbeddingClient(
        transport=RecordingEmbeddingTransport(),
        scheduler=scheduler,
    )

    with pytest.raises(KnowledgeModelWorkCancelled):
        client.embed(
            texts=("insurance rule",),
            model_revision="embedding@sha256:model",
            instruction="Represent for retrieval",
            dimension=2,
            normalized=True,
            priority="online",
            timeout_seconds=5.0,
        )

    assert scheduler_transport.completed == 1
    assert scheduler_transport.cancelled == 0
    scheduler.close()


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


def test_online_rerank_reaches_remote_scheduler_while_offline_acquires_are_blocked() -> None:
    offline_started = Event()
    release_offline = Event()
    online_acquired = Event()

    class PriorityTransport(RecordingSchedulerTransport):
        def __init__(self) -> None:
            super().__init__()
            self._sequence = 0

        def acquire(self, *, priority, **kwargs) -> SchedulerLease:
            del kwargs
            self._sequence += 1
            if priority == "offline":
                offline_started.set()
                assert release_offline.wait(timeout=2)
            else:
                online_acquired.set()
            return SchedulerLease(
                work_id=f"work-{self._sequence}",
                lease_token=f"lease-{self._sequence}",
                queue_time_ms=0.0,
            )

    transport = PriorityTransport()
    scheduler = remote_scheduler(
        transport,
        acquire_workers_per_lane=2,
        acquire_pending_per_lane=1,
        active_lease_limit=3,
        online_reserved_leases=1,
    )

    class RerankTransport:
        def rerank(self, request, **kwargs):
            del kwargs
            return RerankerTransportResponse(
                model_revision=request.model_revision,
                scores=((request.candidates[0].candidate_id, 0.9),),
            )

    reranker = PrivateRerankerClient(
        transport=RerankTransport(),
        scheduler=scheduler,
    )

    def offline_operation(_remaining, _cancellation):
        return "offline"

    with ThreadPoolExecutor(max_workers=3) as callers:
        offline_calls = tuple(
            callers.submit(
                scheduler.submit_and_wait,
                kind="ocr",
                priority="offline",
                timeout_seconds=5.0,
                operation=offline_operation,
            )
            for _ in range(2)
        )
        deadline = monotonic() + 1
        while transport._sequence < 2 and monotonic() < deadline:
            sleep(0.005)
        assert transport._sequence == 2

        online = callers.submit(
            reranker.rerank,
            query="waiting period",
            candidates=(RerankCandidate(candidate_id="rule-1", text="Thirty days."),),
            model_revision="reranker@sha256:model",
            max_input_tokens=2048,
            priority="online",
            timeout_seconds=5.0,
        )
        assert online_acquired.wait(timeout=0.5)
        assert online.result(timeout=1).scores == (("rule-1", 0.9),)

        release_offline.set()
        assert tuple(call.result(timeout=1).value for call in offline_calls) == (
            "offline",
            "offline",
        )

    scheduler.close()


def test_service_lane_saturation_after_acquire_uses_reserved_cancel_lane_once() -> None:
    service_started = Event()
    release_service = Event()

    class TerminalTransport(RecordingSchedulerTransport):
        def __init__(self) -> None:
            super().__init__()
            self.acquired: list[str] = []
            self.completed_ids: list[str] = []
            self.cancelled_ids: list[str] = []

        def acquire(self, **kwargs):
            del kwargs
            work_id = f"work-{len(self.acquired) + 1}"
            self.acquired.append(work_id)
            return SchedulerLease(
                work_id=work_id,
                lease_token=f"lease-{work_id}",
                queue_time_ms=0.0,
            )

        def complete(self, _endpoint, _namespace, lease, **kwargs):
            del kwargs
            self.completed_ids.append(lease.work_id)

        def cancel(self, _endpoint, _namespace, lease, **kwargs):
            del kwargs
            self.cancelled_ids.append(lease.work_id)

    transport = TerminalTransport()
    scheduler = remote_scheduler(
        transport,
        executor_workers=1,
        executor_pending=1,
        active_lease_limit=4,
        online_reserved_leases=1,
    )

    def blocked_operation(_remaining, _cancellation):
        service_started.set()
        assert release_service.wait(timeout=2)
        return "done"

    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=blocked_operation,
        )
        assert service_started.wait(timeout=1)
        second = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=lambda _remaining, _cancellation: "queued",
        )
        deadline = monotonic() + 1
        while scheduler._service_executor.pending_count() != 1 and monotonic() < deadline:
            sleep(0.005)
        assert scheduler._service_executor.pending_count() == 1

        with pytest.raises(RuntimeError, match="saturated"):
            scheduler.submit_and_wait(
                kind="embedding",
                priority="online",
                timeout_seconds=5.0,
                operation=lambda _remaining, _cancellation: "must-not-run",
            )
        assert transport.cancelled_ids == ["work-3"]
        assert "work-3" not in transport.completed_ids

        release_service.set()
        assert first.result(timeout=1).value == "done"
        assert second.result(timeout=1).value == "queued"

    scheduler.close()


def test_complete_lane_saturation_after_service_uses_reserved_cancel_lane_once() -> None:
    complete_started = Event()
    release_complete = Event()

    class BlockingCompleteTransport(RecordingSchedulerTransport):
        def __init__(self) -> None:
            super().__init__()
            self.acquired: list[str] = []
            self.completed_ids: list[str] = []
            self.cancelled_ids: list[str] = []

        def acquire(self, **kwargs):
            del kwargs
            work_id = f"work-{len(self.acquired) + 1}"
            self.acquired.append(work_id)
            return SchedulerLease(
                work_id=work_id,
                lease_token=f"lease-{work_id}",
                queue_time_ms=0.0,
            )

        def complete(self, _endpoint, _namespace, lease, **kwargs):
            del kwargs
            if not self.completed_ids:
                complete_started.set()
                assert release_complete.wait(timeout=2)
            self.completed_ids.append(lease.work_id)

        def cancel(self, _endpoint, _namespace, lease, **kwargs):
            del kwargs
            self.cancelled_ids.append(lease.work_id)

    transport = BlockingCompleteTransport()
    scheduler = remote_scheduler(
        transport,
        terminal_workers=1,
        complete_pending=1,
        active_lease_limit=4,
        online_reserved_leases=1,
    )

    def operation(_remaining, _cancellation):
        return "done"

    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=operation,
        )
        assert complete_started.wait(timeout=1)
        second = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=operation,
        )
        deadline = monotonic() + 1
        while scheduler._complete_executor.pending_count() != 1 and monotonic() < deadline:
            sleep(0.005)
        assert scheduler._complete_executor.pending_count() == 1

        with pytest.raises(RuntimeError, match="saturated"):
            scheduler.submit_and_wait(
                kind="embedding",
                priority="online",
                timeout_seconds=5.0,
                operation=operation,
            )
        assert transport.cancelled_ids == ["work-3"]
        assert "work-3" not in transport.completed_ids

        release_complete.set()
        assert first.result(timeout=1).value == "done"
        assert second.result(timeout=1).value == "done"

    scheduler.close()


def test_scheduler_executor_is_bounded_saturates_closed_and_uses_daemon_workers() -> None:
    acquire_started = Event()
    release_acquire = Event()

    class IgnoringAcquireTransport(RecordingSchedulerTransport):
        def acquire(self, **kwargs) -> SchedulerLease:
            del kwargs
            acquire_started.set()
            assert release_acquire.wait(timeout=2)
            return super().acquire()

    before = tuple(
        thread for thread in enumerate_threads() if thread.name.startswith("knowledge-model-")
    )
    scheduler_transport = IgnoringAcquireTransport()
    scheduler = remote_scheduler(
        scheduler_transport,
        executor_workers=1,
        executor_pending=1,
        acquire_workers_per_lane=1,
        acquire_pending_per_lane=1,
        terminal_workers=1,
        active_lease_limit=4,
        online_reserved_leases=1,
    )

    def operation(_remaining, _cancellation):
        return "unreachable"

    with ThreadPoolExecutor(max_workers=3) as callers:
        first = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=operation,
        )
        assert acquire_started.wait(timeout=1)
        second = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=operation,
        )
        third = callers.submit(
            scheduler.submit_and_wait,
            kind="embedding",
            priority="online",
            timeout_seconds=5.0,
            operation=operation,
        )
        with pytest.raises(RuntimeError, match="saturated"):
            third.result(timeout=1)

        workers = tuple(
            thread
            for thread in enumerate_threads()
            if thread.name.startswith("knowledge-model-") and thread not in before
        )
        assert len(workers) == 5
        assert all(worker.daemon for worker in workers)

        started = monotonic()
        scheduler.close()
        assert monotonic() - started < 1.0
        with pytest.raises(KnowledgeModelWorkCancelled):
            first.result(timeout=1)
        with pytest.raises(KnowledgeModelWorkCancelled):
            second.result(timeout=1)

    release_acquire.set()
