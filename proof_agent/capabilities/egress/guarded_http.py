from __future__ import annotations

from collections.abc import Callable, Mapping
import http.client
import ipaddress
import socket
import ssl
from typing import Protocol
from urllib.parse import urljoin, urlsplit

from proof_agent.contracts.ports.guarded_http import GuardedHttpResponse
from proof_agent.control.security.egress import CompiledEgressPolicy, EgressDeniedError


_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_SENSITIVE_REDIRECT_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "proxy-authorization",
        "x-api-key",
        "x-auth-token",
        "x-vault-token",
    }
)


class AddressResolver(Protocol):
    def resolve(
        self,
        hostname: str,
        port: int,
        *,
        timeout_seconds: float,
    ) -> tuple[str, ...]: ...


class PinnedHttpTransport(Protocol):
    def send(
        self,
        method: str,
        url: str,
        *,
        connect_address: str,
        tls_hostname: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> GuardedHttpResponse: ...


class SystemAddressResolver:
    """Fresh system DNS lookup; the caller validates the complete answer set."""

    def resolve(
        self,
        hostname: str,
        port: int,
        *,
        timeout_seconds: float,
    ) -> tuple[str, ...]:
        del timeout_seconds
        records = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        answers: list[str] = []
        for record in records:
            address = str(record[4][0])
            if address not in answers:
                answers.append(address)
        return tuple(answers)


class StdlibPinnedHttpsTransport:
    """Connect to a numeric admitted IP while verifying TLS for the original host."""

    def __init__(self, *, ssl_context: ssl.SSLContext | None = None) -> None:
        self._ssl_context = ssl_context or ssl.create_default_context()

    def send(
        self,
        method: str,
        url: str,
        *,
        connect_address: str,
        tls_hostname: str,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> GuardedHttpResponse:
        ipaddress.ip_address(connect_address)
        parsed = urlsplit(url)
        port = parsed.port or 443
        if parsed.scheme.lower() != "https" or parsed.hostname != tls_hostname:
            raise ValueError("pinned HTTPS transport received inconsistent authority")
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        safe_headers = _validated_headers(headers)
        safe_headers["Connection"] = "close"
        raw_socket = socket.create_connection(
            (connect_address, port),
            timeout=timeout_seconds,
        )
        connection = http.client.HTTPConnection(
            host=tls_hostname,
            port=port,
            timeout=timeout_seconds,
        )
        try:
            connection.sock = self._ssl_context.wrap_socket(
                raw_socket,
                server_hostname=tls_hostname,
            )
            connection.request(method, target, body=body, headers=safe_headers)
            response = connection.getresponse()
            declared_length = response.getheader("content-length")
            if declared_length is not None:
                try:
                    parsed_length = int(declared_length)
                except ValueError as exc:
                    raise ValueError("guarded HTTPS response has invalid Content-Length") from exc
                if parsed_length < 0 or parsed_length > max_response_bytes:
                    raise ValueError("guarded HTTPS response exceeds byte limit")
            response_body = response.read(max_response_bytes + 1)
            if len(response_body) > max_response_bytes:
                raise ValueError("guarded HTTPS response exceeds byte limit")
            response_headers = {key.lower(): value for key, value in response.getheaders()}
            return GuardedHttpResponse(
                status_code=response.status,
                headers=response_headers,
                body=response_body,
            )
        finally:
            connection.close()
            if connection.sock is None:
                raw_socket.close()


class GuardedHttpsClient:
    """Default-deny HTTPS with fresh all-address validation before every connect."""

    def __init__(
        self,
        *,
        policy: CompiledEgressPolicy,
        resolver: AddressResolver | None = None,
        transport: PinnedHttpTransport | None = None,
        max_redirects: int = 3,
        max_attempts_per_hop: int = 1,
        max_dns_answers: int = 16,
        max_response_bytes: int = 10 * 1024 * 1024,
        denial_audit_sink: Callable[[str, str | None], None] | None = None,
    ) -> None:
        if max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if max_attempts_per_hop < 1:
            raise ValueError("max_attempts_per_hop must be positive")
        if max_dns_answers < 1 or max_response_bytes < 1:
            raise ValueError("guarded HTTPS bounds must be positive")
        self._policy = policy
        self._resolver = resolver or SystemAddressResolver()
        self._transport = transport or StdlibPinnedHttpsTransport()
        self._max_redirects = max_redirects
        self._max_attempts_per_hop = max_attempts_per_hop
        self._max_dns_answers = max_dns_answers
        self._max_response_bytes = max_response_bytes
        self._denial_audit_sink = denial_audit_sink

    def restricted(
        self,
        *,
        max_redirects: int,
        max_attempts_per_hop: int,
        max_response_bytes: int,
    ) -> GuardedHttpsClient:
        """Derive a stricter client while preserving the same active policy and I/O adapters."""

        return GuardedHttpsClient(
            policy=self._policy,
            resolver=self._resolver,
            transport=self._transport,
            max_redirects=min(max_redirects, self._max_redirects),
            max_attempts_per_hop=min(
                max_attempts_per_hop,
                self._max_attempts_per_hop,
            ),
            max_dns_answers=self._max_dns_answers,
            max_response_bytes=min(max_response_bytes, self._max_response_bytes),
            denial_audit_sink=self._denial_audit_sink,
        )

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
        timeout_seconds: float = 10.0,
    ) -> GuardedHttpResponse:
        if timeout_seconds <= 0:
            raise ValueError("guarded HTTPS timeout must be positive")
        normalized_method = _validated_method(method)
        current_url = url
        current_headers = _validated_headers(headers or {})
        current_body = body
        redirects = 0
        try:
            while True:
                response = self._request_hop(
                    normalized_method,
                    current_url,
                    headers=current_headers,
                    body=current_body,
                    timeout_seconds=timeout_seconds,
                )
                if response.status_code not in _REDIRECT_STATUSES:
                    return response
                location = _header(response.headers, "location")
                if location is None:
                    return response
                if redirects >= self._max_redirects:
                    raise EgressDeniedError(reason_code="redirect_limit_exceeded")
                next_url = urljoin(current_url, location)
                current_origin = self._policy.authorize_origin(current_url)
                next_origin = self._policy.authorize_origin(next_url)
                if current_origin != next_origin:
                    current_headers = {
                        key: value
                        for key, value in current_headers.items()
                        if key.lower() not in _SENSITIVE_REDIRECT_HEADERS
                    }
                if response.status_code == 303 or (
                    response.status_code in {301, 302} and normalized_method == "POST"
                ):
                    normalized_method = "GET"
                    current_body = None
                    current_headers = {
                        key: value
                        for key, value in current_headers.items()
                        if key.lower() not in {"content-length", "content-type"}
                    }
                current_url = next_url
                redirects += 1
        except EgressDeniedError as exc:
            self._audit_denial(exc)
            raise

    def _request_hop(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_seconds: float,
    ) -> GuardedHttpResponse:
        origin = self._policy.authorize_origin(url)
        for attempt in range(self._max_attempts_per_hop):
            try:
                answers = self._resolver.resolve(
                    origin.host,
                    origin.port,
                    timeout_seconds=timeout_seconds,
                )
            except Exception as exc:
                raise EgressDeniedError(
                    reason_code="dns_resolution_failed",
                    origin=origin.value,
                ) from exc
            if len(answers) > self._max_dns_answers:
                raise EgressDeniedError(
                    reason_code="dns_answer_limit_exceeded",
                    origin=origin.value,
                )
            admitted = self._policy.admit(url, resolved_addresses=answers)
            response = self._transport.send(
                method,
                url,
                connect_address=admitted.addresses[0],
                tls_hostname=admitted.origin.host,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
                max_response_bytes=self._max_response_bytes,
            )
            if response.status_code not in _RETRYABLE_STATUSES:
                return response
            if attempt + 1 == self._max_attempts_per_hop:
                return response
        raise AssertionError("bounded retry loop did not return")

    def _audit_denial(self, denial: EgressDeniedError) -> None:
        if self._denial_audit_sink is None:
            return
        try:
            self._denial_audit_sink(denial.reason_code, denial.origin)
        except Exception:
            pass


def _validated_method(method: str) -> str:
    normalized = method.upper()
    if not normalized or not normalized.isalpha() or len(normalized) > 16:
        raise ValueError("guarded HTTPS method is invalid")
    return normalized


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, value in headers.items():
        if (
            not key
            or not value
            or "\r" in key + value
            or "\n" in key + value
            or key.lower() in {"host", "connection", "transfer-encoding"}
        ):
            raise ValueError("guarded HTTPS header is invalid")
        validated[key] = value
    return validated


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), None)
