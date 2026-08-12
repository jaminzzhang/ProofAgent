"""Fail-closed client adapter for the independent Knowledge Source Service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from time import sleep as default_sleep
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, Field, ValidationError, model_validator

from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_candidates import (
    KnowledgeCandidateQuery,
    KnowledgeCandidateResult,
    KnowledgeQueryResultPayload,
    NonBlankText,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient, GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class _KnowledgeServiceProblem(StrictFrozenModel):
    type: NonBlankText
    title: NonBlankText
    status: int = Field(ge=400, le=599)
    code: NonBlankText
    detail: NonBlankText
    trace_id: NonBlankText
    retryable: bool
    blockers: tuple[Mapping[str, Any], ...] = ()


class _KnowledgeQueryLinks(StrictFrozenModel):
    self: NonBlankText
    cancel: NonBlankText


class _KnowledgeQueryResource(StrictFrozenModel):
    schema_version: Literal["knowledge-query.v1"]
    knowledge_query_id: NonBlankText
    knowledge_base_release_id: NonBlankText
    state: Literal["queued", "running", "succeeded", "failed", "cancelled", "expired"]
    submitted_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    deadline_at: AwareDatetime
    cancel_requested_at: AwareDatetime | None
    result_availability: Literal["pending", "available", "unavailable", "expired"]
    result_expires_at: AwareDatetime | None
    result: KnowledgeQueryResultPayload | None
    problem: _KnowledgeServiceProblem | None
    links: _KnowledgeQueryLinks

    @model_validator(mode="after")
    def require_success_result_shape(self) -> Self:
        if self.state == "succeeded" and self.result_availability == "available":
            if self.result is None or self.result_expires_at is None:
                raise ValueError("available success requires result and expiry")
        elif self.result is not None:
            raise ValueError("only available success may expose a result")
        return self


class KnowledgeSourceServiceClient:
    """Create and poll exact Knowledge Queries through the guarded egress boundary."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: GuardedHttpClient,
        authorization_header_factory: Callable[[], str],
        sleep: Callable[[float], None] = default_sleep,
        max_polls: int = 120,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self._endpoint = _validated_endpoint(endpoint)
        if max_polls <= 0:
            raise ValueError("max_polls must be positive")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._http_client = http_client
        self._authorization_header_factory = authorization_header_factory
        self._sleep = sleep
        self._max_polls = max_polls
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def query(self, request: KnowledgeCandidateQuery) -> KnowledgeCandidateResult:
        payload = request.model_dump(mode="json")
        idempotency_key = str(payload.pop("idempotency_key"))
        response = self._send(
            "POST",
            f"{self._endpoint}/v1/knowledge-queries",
            headers={
                **self._authorization_headers(),
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
                "Prefer": "respond-async",
            },
            body=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        )
        resource = self._resource_from_response(response)
        self._require_exact_release(resource, request)
        if resource.state == "succeeded":
            return _candidate_result(resource)
        if resource.state in {"failed", "cancelled", "expired"}:
            raise _terminal_query_error(resource)

        location = _poll_location(response.headers, resource.links.self)
        for _poll_attempt in range(self._max_polls):
            retry_after = _retry_after_seconds(response.headers)
            if retry_after > 0:
                self._sleep(retry_after)
            response = self._send(
                "GET",
                f"{self._endpoint}{location}",
                headers={**self._authorization_headers(), "Accept": "application/json"},
                body=None,
            )
            resource = self._resource_from_response(response)
            self._require_exact_release(resource, request)
            if resource.links.self != location:
                raise _contract_error("poll response changed Knowledge Query identity")
            if resource.state == "succeeded":
                return _candidate_result(resource)
            if resource.state in {"failed", "cancelled", "expired"}:
                raise _terminal_query_error(resource)
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "Knowledge Source Service polling exhausted before a terminal result.",
            "Retry the governed run after checking service capacity and Query latency.",
        )

    def _authorization_headers(self) -> dict[str, str]:
        try:
            value = self._authorization_header_factory()
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service client authorization is unavailable.",
                "Restore the configured service-client credential provider.",
            ) from error
        if not value.strip():
            raise _contract_error("service-client authorization header is blank")
        return {"Authorization": value}

    def _send(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> GuardedHttpResponse:
        try:
            response = self._http_client.request(
                method,
                url,
                headers=headers,
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
        except ProofAgentError:
            raise
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service request failed at the guarded HTTPS boundary.",
                "Check the active Egress Policy and Knowledge service readiness.",
            ) from error
        if 300 <= response.status_code < 400:
            raise _contract_error("Knowledge Source Service redirects are forbidden")
        if response.status_code not in {200, 201, 202}:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                f"Knowledge Source Service rejected the request with HTTP {response.status_code}.",
                "Inspect the trace-safe service problem and the Agent Knowledge binding.",
            )
        return response

    def _resource_from_response(
        self, response: GuardedHttpResponse
    ) -> _KnowledgeQueryResource:
        if len(response.body) > self._max_response_bytes:
            raise _contract_error("Knowledge Source Service response exceeds its byte limit")
        try:
            payload = json.loads(response.body)
            return _KnowledgeQueryResource.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise _contract_error("Knowledge Source Service returned an invalid Query contract") from error

    @staticmethod
    def _require_exact_release(
        resource: _KnowledgeQueryResource,
        request: KnowledgeCandidateQuery,
    ) -> None:
        if resource.knowledge_base_release_id != request.knowledge_base_release_id:
            raise _contract_error("Knowledge Query response changed the exact Release")


def _candidate_result(resource: _KnowledgeQueryResource) -> KnowledgeCandidateResult:
    if resource.result is None:
        raise _contract_error("succeeded Knowledge Query omitted its result")
    return KnowledgeCandidateResult.model_validate(
        {
            "knowledge_query_id": resource.knowledge_query_id,
            **resource.result.model_dump(mode="python"),
        }
    )


def _terminal_query_error(resource: _KnowledgeQueryResource) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        f"Knowledge Source Service Query reached terminal state {resource.state}.",
        "Inspect the Query trace ID and repair the governed Knowledge binding; no local fallback was used.",
    )


def _poll_location(headers: Mapping[str, str], fallback: str) -> str:
    location = _header(headers, "location") or fallback
    parsed = urlsplit(location)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/v1/knowledge-queries/")
        or parsed.path.endswith(":cancel")
    ):
        raise _contract_error("Knowledge Query poll Location is not a safe relative resource path")
    return parsed.path


def _retry_after_seconds(headers: Mapping[str, str]) -> float:
    value = _header(headers, "retry-after")
    if value is None:
        return 0.25
    try:
        parsed = float(value)
    except ValueError as error:
        raise _contract_error("Knowledge Query Retry-After is invalid") from error
    if parsed < 0 or parsed > 5:
        raise _contract_error("Knowledge Query Retry-After is outside the client bound")
    return parsed


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.casefold()
    return next((value for key, value in headers.items() if key.casefold() == expected), None)


def _validated_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Knowledge Source Service endpoint must be an HTTPS origin")
    return endpoint.rstrip("/")


def _contract_error(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        message,
        "Verify the Knowledge Source Service release and strict client contract.",
    )
