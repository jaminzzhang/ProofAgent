from __future__ import annotations

from typing import Literal, cast
import json

from pydantic import JsonValue

from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    EmbeddingRequest,
    EmbeddingTransportResponse,
    KnowledgeModelCancellation,
    RerankerRequest,
    RerankerTransportResponse,
    SchedulerLease,
    WorkKind,
    WorkPriority,
    decode_bounded_json_bytes,
)
from proof_agent.capabilities.knowledge.hybrid.parser_clients import (
    ParserServiceAttestation,
    ParserServiceRequest,
    canonical_vendor_json_bytes,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient


class GuardedHybridJsonClient:
    """Typed Hybrid service JSON boundary over the tenant active Egress Policy."""

    def __init__(self, client: GuardedHttpClient) -> None:
        self._client = client

    def post(
        self,
        url: str,
        payload: object,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        cancellation: KnowledgeModelCancellation,
        expect_json: bool = True,
    ) -> object:
        cancellation.raise_if_cancelled()
        response = self._client.request(
            "POST",
            url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            timeout_seconds=timeout_seconds,
        )
        cancellation.raise_if_cancelled()
        if 300 <= response.status_code < 400:
            raise ValueError("private Knowledge service redirects are forbidden")
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise ConnectionError("private Knowledge service is temporarily unavailable")
        if response.status_code >= 400:
            raise ValueError("private Knowledge service rejected the typed request")
        if not expect_json:
            return None
        if len(response.body) > max_response_bytes:
            raise ValueError("private Knowledge service response exceeds its byte limit")
        return decode_bounded_json_bytes(response.body)


class GuardedSchedulerTransport:
    def __init__(self, client: GuardedHttpClient) -> None:
        self._json = GuardedHybridJsonClient(client)

    def acquire(
        self,
        *,
        endpoint: str,
        namespace: str,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> SchedulerLease:
        _require_no_redirects(follow_redirects)
        response = self._json.post(
            f"{endpoint}/v1/work/acquire",
            {
                "namespace": namespace,
                "kind": kind,
                "priority": priority,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=timeout_seconds,
            max_response_bytes=64 * 1024,
            cancellation=cancellation,
        )
        return SchedulerLease.model_validate(response)

    def complete(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> None:
        _require_no_redirects(follow_redirects)
        self._json.post(
            f"{endpoint}/v1/work/complete",
            {"namespace": namespace, "work_id": lease.work_id, "lease_token": lease.lease_token},
            timeout_seconds=timeout_seconds,
            max_response_bytes=64 * 1024,
            cancellation=cancellation,
            expect_json=False,
        )

    def cancel(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
    ) -> None:
        _require_no_redirects(follow_redirects)
        self._json.post(
            f"{endpoint}/v1/work/cancel",
            {"namespace": namespace, "work_id": lease.work_id, "lease_token": lease.lease_token},
            timeout_seconds=timeout_seconds,
            max_response_bytes=64 * 1024,
            cancellation=KnowledgeModelCancellation(),
            expect_json=False,
        )

    def close(self) -> None:
        return None


class GuardedParserHttpTransport:
    def __init__(self, client: GuardedHttpClient, *, endpoint: str) -> None:
        self._json = GuardedHybridJsonClient(client)
        self._endpoint = endpoint.rstrip("/")

    def parse(
        self,
        request: ParserServiceRequest,
        *,
        follow_redirects: Literal[False],
    ) -> ParserServiceAttestation:
        return self.parse_scheduled(
            request,
            timeout_seconds=120.0,
            follow_redirects=follow_redirects,
            allow_runtime_downloads=False,
            cancellation=KnowledgeModelCancellation(),
        )

    def parse_scheduled(
        self,
        request: ParserServiceRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> ParserServiceAttestation:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("parser redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        response = self._json.post(
            f"{self._endpoint}/v1/parse",
            payload,
            timeout_seconds=timeout_seconds,
            max_response_bytes=64 * 1024 * 1024,
            cancellation=cancellation,
        )
        if not isinstance(response, dict):
            raise ValueError("private parser response root must be a JSON object")
        raw = dict(response)
        vendor_json = raw.pop("vendor_json", None)
        if not isinstance(vendor_json, dict):
            raise ValueError("private parser response requires a vendor_json object")
        raw["vendor_json_bytes"] = canonical_vendor_json_bytes(
            cast(dict[str, JsonValue], vendor_json)
        )
        return ParserServiceAttestation.model_validate(raw)

    def close(self) -> None:
        return None


class GuardedEmbeddingHttpTransport:
    def __init__(self, client: GuardedHttpClient, *, endpoint: str) -> None:
        self._json = GuardedHybridJsonClient(client)
        self._endpoint = endpoint.rstrip("/")

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> EmbeddingTransportResponse:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("embedding redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        return EmbeddingTransportResponse.model_validate(
            self._json.post(
                f"{self._endpoint}/v1/embeddings",
                payload,
                timeout_seconds=timeout_seconds,
                max_response_bytes=64 * 1024 * 1024,
                cancellation=cancellation,
            )
        )

    def close(self) -> None:
        return None


class GuardedRerankerHttpTransport:
    def __init__(self, client: GuardedHttpClient, *, endpoint: str) -> None:
        self._json = GuardedHybridJsonClient(client)
        self._endpoint = endpoint.rstrip("/")

    def rerank(
        self,
        request: RerankerRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> RerankerTransportResponse:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("reranker redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        return RerankerTransportResponse.model_validate(
            self._json.post(
                f"{self._endpoint}/v1/rerank",
                payload,
                timeout_seconds=timeout_seconds,
                max_response_bytes=16 * 1024 * 1024,
                cancellation=cancellation,
            )
        )

    def close(self) -> None:
        return None


def _require_no_redirects(value: Literal[False]) -> None:
    if value is not False:
        raise ValueError("private Knowledge service redirects are forbidden")
