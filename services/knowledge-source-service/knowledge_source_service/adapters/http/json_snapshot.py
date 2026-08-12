"""Bounded static HTTPS JSON snapshot reader with SSRF defenses."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from knowledge_source_service.domain.identities import sha256_text
from knowledge_source_service.ports.snapshots import JsonSnapshot


class HttpJsonSnapshotError(RuntimeError):
    """The configured upstream failed or violated the snapshot profile."""


class HttpJsonSnapshotReader:
    """Read exactly one static, allowlisted HTTPS JSON resource."""

    def __init__(
        self,
        *,
        endpoint: str,
        bearer_token: str | None,
        max_response_bytes: int,
        clock: Callable[[], datetime],
        resolve_host: Callable[[str], tuple[str, ...]] | None = None,
        allowed_networks: tuple[str, ...] = (),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        hostname = _validated_endpoint(endpoint)
        if bearer_token is not None and (
            len(bearer_token) < 16
            or bearer_token != bearer_token.strip()
            or any(character.isspace() for character in bearer_token)
        ):
            raise ValueError("HTTP snapshot Bearer credential is invalid")
        if max_response_bytes < 1 or max_response_bytes > 64 * 1024 * 1024:
            raise ValueError("HTTP snapshot response bound is invalid")
        try:
            networks = tuple(ipaddress.ip_network(value) for value in allowed_networks)
        except ValueError as error:
            raise ValueError("HTTP snapshot allowed network is invalid") from error
        self._endpoint = endpoint
        self._hostname = hostname
        self._max_response_bytes = max_response_bytes
        self._clock = clock
        self._resolve_host = resolve_host or _resolve_host
        self._allowed_networks = networks
        headers = {"Accept": "application/json"}
        if bearer_token is not None:
            headers["Authorization"] = f"Bearer {bearer_token}"
        self._client = httpx.Client(
            timeout=httpx.Timeout(15, connect=3),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers=headers,
        )

    def close(self) -> None:
        self._client.close()

    def read(self) -> JsonSnapshot:
        before = self._validated_addresses()
        try:
            with self._client.stream("GET", self._endpoint) as response:
                if response.status_code != 200:
                    raise HttpJsonSnapshotError(
                        "HTTP JSON snapshot returned a non-success status"
                    )
                content_type = response.headers.get("Content-Type", "").partition(";")[0]
                if content_type.casefold() != "application/json":
                    raise HttpJsonSnapshotError(
                        "HTTP JSON snapshot returned an invalid media type"
                    )
                declared_length = response.headers.get("Content-Length")
                if declared_length is not None and (
                    not declared_length.isdecimal()
                    or int(declared_length) > self._max_response_bytes
                ):
                    raise HttpJsonSnapshotError(
                        "HTTP JSON snapshot declared an invalid response size"
                    )
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self._max_response_bytes:
                        raise HttpJsonSnapshotError(
                            "HTTP JSON snapshot exceeded its response bound"
                        )
                etag = response.headers.get("ETag")
                last_modified = response.headers.get("Last-Modified")
        except HttpJsonSnapshotError:
            raise
        except httpx.HTTPError as error:
            raise HttpJsonSnapshotError("HTTP JSON snapshot request failed") from error
        if not body:
            raise HttpJsonSnapshotError("HTTP JSON snapshot response is empty")
        if self._validated_addresses() != before:
            raise HttpJsonSnapshotError("HTTP JSON snapshot DNS identity changed")
        observed_at = self._clock()
        try:
            return JsonSnapshot(
                content=bytes(body),
                source_identity_digest=sha256_text(self._endpoint),
                observed_at=observed_at,
                etag=etag,
                last_modified=last_modified,
            )
        except ValueError as error:
            raise HttpJsonSnapshotError(
                "HTTP JSON snapshot metadata failed validation"
            ) from error

    def _validated_addresses(self) -> frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        try:
            addresses = frozenset(
                ipaddress.ip_address(value)
                for value in self._resolve_host(self._hostname)
            )
        except (OSError, ValueError) as error:
            raise HttpJsonSnapshotError(
                "HTTP JSON snapshot host resolution failed"
            ) from error
        if not addresses or any(
            not address.is_global
            and not any(address in network for network in self._allowed_networks)
            for address in addresses
        ):
            raise HttpJsonSnapshotError(
                "HTTP JSON snapshot resolved outside its allowed networks"
            )
        return addresses


def _validated_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("HTTP JSON snapshot endpoint must be a static HTTPS URL")
    return parsed.hostname


def _resolve_host(hostname: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(item[4][0])
                for item in socket.getaddrinfo(
                    hostname,
                    None,
                    type=socket.SOCK_STREAM,
                )
            }
        )
    )
