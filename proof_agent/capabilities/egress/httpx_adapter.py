from __future__ import annotations

import asyncio
from collections.abc import Mapping
from functools import partial

import httpx

from proof_agent.contracts.ports.guarded_http import GuardedHttpClient


class GuardedHttpxTransport(httpx.BaseTransport):
    """Sync HTTPX bridge whose only I/O is the guarded HTTPS port."""

    def __init__(self, guarded_client: GuardedHttpClient) -> None:
        self._guarded_client = guarded_client

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._guarded_client.request(
            request.method,
            str(request.url),
            headers=_headers(request.headers),
            body=request.read(),
            timeout_seconds=_timeout(request),
        )
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.body,
            request=request,
        )


class GuardedAsyncHttpxTransport(httpx.AsyncBaseTransport):
    """Async HTTPX bridge for SDKs such as Streamable HTTP MCP."""

    def __init__(self, guarded_client: GuardedHttpClient) -> None:
        self._guarded_client = guarded_client

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        operation = partial(
            self._guarded_client.request,
            request.method,
            str(request.url),
            headers=_headers(request.headers),
            body=body,
            timeout_seconds=_timeout(request),
        )
        response = await asyncio.to_thread(operation)
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=response.body,
            request=request,
        )


def _headers(headers: httpx.Headers) -> Mapping[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in {"host", "connection", "transfer-encoding"}
    }


def _timeout(request: httpx.Request) -> float:
    timeout = request.extensions.get("timeout")
    if isinstance(timeout, dict):
        candidates = [
            float(value)
            for value in timeout.values()
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0
        ]
        if candidates:
            return min(candidates)
    return 10.0
