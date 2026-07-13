from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Condition
from time import monotonic
from typing import Generic, Literal, TypeVar

import pytest

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    PrivateRerankerClient,
    RerankCandidate,
    RerankerTransportResponse,
    ScheduledWorkResult,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceAttestation,
    ParserServiceRequest,
    PrivatePaddleClient,
    canonical_vendor_json_bytes,
)
from proof_agent.capabilities.knowledge.ingestion.hybrid_worker import (
    HybridKnowledgeWorkerFactory,
)
from proof_agent.contracts.knowledge_index import ExactArtifactRef


T = TypeVar("T")


@dataclass
class PendingWork(Generic[T]):
    kind: str
    priority: str
    operation: Callable[[float], T]
    timeout_seconds: float
    released: bool = False
    result: ScheduledWorkResult[T] | None = None


class PausedScheduler:
    def __init__(self) -> None:
        self._condition = Condition()
        self.pending: list[PendingWork] = []

    def submit_and_wait(self, *, kind, priority, timeout_seconds, operation, cancellation=None):
        del cancellation
        work = PendingWork(
            kind=kind,
            priority=priority,
            operation=operation,
            timeout_seconds=timeout_seconds,
        )
        with self._condition:
            self.pending.append(work)
            self._condition.notify_all()
            while not work.released:
                self._condition.wait()
        started = monotonic()
        from proof_agent.capabilities.knowledge.hybrid.model_clients import (
            KnowledgeModelCancellation,
        )

        value = work.operation(work.timeout_seconds, KnowledgeModelCancellation())
        work.result = ScheduledWorkResult(
            value=value,
            queue_time_ms=1.0,
            service_time_ms=(monotonic() - started) * 1000,
        )
        return work.result

    def wait_for_pending(self, count: int) -> None:
        deadline = monotonic() + 2
        with self._condition:
            while len(self.pending) < count and monotonic() < deadline:
                self._condition.wait(timeout=0.05)
        assert len(self.pending) == count

    def release_next(self) -> PendingWork:
        with self._condition:
            queued = [work for work in self.pending if not work.released]
            work = min(
                queued, key=lambda item: (item.priority != "online", self.pending.index(item))
            )
            work.released = True
            self._condition.notify_all()
            return work

    def close(self) -> None:
        return None


class RecordingPaddleTransport:
    def __init__(self, response: ParserServiceAttestation) -> None:
        self.response = response
        self.calls = 0

    def parse(
        self, request: ParserServiceRequest, *, follow_redirects: Literal[False]
    ) -> ParserServiceAttestation:
        self.calls += 1
        return self.response


class RecordingRerankTransport:
    def __init__(self) -> None:
        self.calls = 0

    def rerank(self, request, **kwargs) -> RerankerTransportResponse:
        del kwargs
        self.calls += 1
        return RerankerTransportResponse(
            model_revision=request.model_revision,
            scores=((request.candidates[0].candidate_id, 0.9),),
        )


def _parser_request_and_attestation() -> tuple[ParserServiceRequest, ParserServiceAttestation]:
    original = ExactArtifactRef(
        artifact_uri="s3://knowledge/original.pdf",
        version_id=f"sha256:{'a' * 64}",
        sha256="a" * 64,
        size_bytes=10,
        media_type="application/pdf",
    )
    request = ParserServiceRequest(
        original_ref=original,
        page_numbers=(1,),
        parser_revision="paddle@sha256:model",
        model_digests=("sha256:model",),
        configuration_sha256="b" * 64,
    )
    payload = {
        "document_id": "doc-1",
        "revision_id": "rev-1",
        "source_sha256": "a" * 64,
        "page": {"page_number": 1},
    }
    content = canonical_vendor_json_bytes(payload)
    from hashlib import sha256

    attestation = ParserServiceAttestation(
        parser_adapter="paddle",
        original_ref=original,
        page_numbers=(1,),
        parser_revision=request.parser_revision,
        model_digests=request.model_digests,
        configuration_sha256=request.configuration_sha256,
        vendor_json_sha256=sha256(content).hexdigest(),
        vendor_json_bytes=content,
    )
    return request, attestation


def test_online_rerank_preempts_queued_ingestion_across_real_adapters() -> None:
    scheduler = PausedScheduler()
    request, attestation = _parser_request_and_attestation()
    paddle_transport = RecordingPaddleTransport(attestation)
    rerank_transport = RecordingRerankTransport()
    parser = PrivatePaddleClient(transport=paddle_transport, scheduler=scheduler)
    reranker = PrivateRerankerClient(transport=rerank_transport, scheduler=scheduler)

    with ThreadPoolExecutor(max_workers=2) as executor:
        offline = executor.submit(parser.parse, request)
        scheduler.wait_for_pending(1)
        online = executor.submit(
            reranker.rerank,
            query="waiting period",
            candidates=(RerankCandidate(candidate_id="rule-1", text="Thirty days."),),
            model_revision="reranker@sha256:model",
            max_input_tokens=2048,
            priority="online",
            timeout_seconds=5.0,
        )
        scheduler.wait_for_pending(2)

        assert paddle_transport.calls == 0
        assert rerank_transport.calls == 0
        assert scheduler.release_next().kind == "rerank"
        assert online.result(timeout=2).scores[0][0] == "rule-1"
        assert scheduler.release_next().kind == "ocr"
        assert offline.result(timeout=2).adapter == "paddle"

    assert paddle_transport.calls == 1
    assert rerank_transport.calls == 1


def test_hybrid_worker_factory_requires_exact_composed_scheduler_property() -> None:
    scheduler = PausedScheduler()
    factory = HybridKnowledgeWorkerFactory(scheduler=scheduler)

    class MissingSchedulerPipeline:
        def build(self, request):
            raise AssertionError(request)

    with pytest.raises(ValueError, match="composed scheduler"):
        factory.create(
            lifecycle=object(),  # type: ignore[arg-type]
            original_store=object(),  # type: ignore[arg-type]
            artifact_store=object(),  # type: ignore[arg-type]
            pipeline=MissingSchedulerPipeline(),  # type: ignore[arg-type]
            worker_id="worker-1",
        )

    class ComposedPipeline(MissingSchedulerPipeline):
        def __init__(self) -> None:
            self.scheduler = scheduler

    worker = factory.create(
        lifecycle=object(),  # type: ignore[arg-type]
        original_store=object(),  # type: ignore[arg-type]
        artifact_store=object(),  # type: ignore[arg-type]
        pipeline=ComposedPipeline(),  # type: ignore[arg-type]
        worker_id="worker-1",
    )

    assert worker.scheduler is scheduler
