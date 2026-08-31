"""Guarded client registrar for one exact KSS Release Reference."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, ValidationError

from proof_agent.contracts import (
    ProductionAgentReleaseReferenceRequest,
    RegisteredProductionAgentReleaseReference,
)
from proof_agent.contracts._base import StrictFrozenModel
from proof_agent.contracts.knowledge_service_management import KnowledgeServiceIdentifier
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient, GuardedHttpResponse
from proof_agent.errors import ProofAgentError


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class _KnowledgeBaseReleaseReferenceResource(StrictFrozenModel):
    schema_version: Literal["knowledge-base-release-reference.v1"]
    knowledge_space_id: KnowledgeServiceIdentifier
    knowledge_base_id: KnowledgeServiceIdentifier
    knowledge_base_release_id: KnowledgeServiceIdentifier
    external_resource_kind: Literal["published_agent_version"]
    external_resource_id: KnowledgeServiceIdentifier
    purpose: Literal["execution_or_rollback"]
    release_reference_id: KnowledgeServiceIdentifier
    authenticated_client_id: KnowledgeServiceIdentifier
    registered_at: AwareDatetime
    state: Literal["active"]


class KnowledgeSourceServiceReleaseReferenceRegistrar:
    """Register a future Published Agent Version through the KSS client boundary."""

    def __init__(
        self,
        *,
        endpoint: str,
        http_client: GuardedHttpClient,
        authorization_header_factory: Callable[[], str],
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        self._endpoint = _validated_endpoint(endpoint)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._http_client = http_client
        self._authorization_header_factory = authorization_header_factory
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def register_release_reference(
        self,
        request: ProductionAgentReleaseReferenceRequest,
        *,
        idempotency_key: str,
    ) -> RegisteredProductionAgentReleaseReference:
        if not isinstance(idempotency_key, str) or not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
            raise _contract_error("KSS Release Reference idempotency key is invalid")
        response = self._send(
            headers={
                "Authorization": self._authorization_header(),
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            body=json.dumps(
                request.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode(),
        )
        resource = self._resource_from_response(response)
        _require_exact_reference(resource, request)
        try:
            return RegisteredProductionAgentReleaseReference.model_validate(
                resource.model_dump(mode="python", exclude={"schema_version"})
            )
        except ValidationError as error:
            raise _contract_error("KSS returned an invalid Release Reference receipt") from error

    def _authorization_header(self) -> str:
        try:
            value = self._authorization_header_factory()
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service Reference authorization is unavailable.",
                "Restore the dedicated service-client credential provider.",
            ) from error
        if not isinstance(value, str):
            raise _contract_error("KSS Reference client authorization is invalid")
        scheme, separator, token = value.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not token
            or token != token.strip()
            or any(character.isspace() for character in token)
        ):
            raise _contract_error("KSS Reference client authorization is invalid")
        return value

    def _send(
        self,
        *,
        headers: Mapping[str, str],
        body: bytes,
    ) -> GuardedHttpResponse:
        try:
            response = self._http_client.request(
                "POST",
                f"{self._endpoint}/v1/knowledge-base-release-references",
                headers=headers,
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
        except ProofAgentError:
            raise
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service Reference request failed at the guarded HTTPS boundary.",
                "Check the active Egress Policy and KSS client readiness.",
            ) from error
        if 300 <= response.status_code < 400:
            raise _contract_error("KSS Release Reference redirects are forbidden")
        if response.status_code != 200:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                f"Knowledge Source Service rejected Reference registration with HTTP {response.status_code}.",
                "Inspect the trace-safe service problem and exact Release binding.",
            )
        return response

    def _resource_from_response(
        self,
        response: GuardedHttpResponse,
    ) -> _KnowledgeBaseReleaseReferenceResource:
        if len(response.body) > self._max_response_bytes:
            raise _contract_error("KSS Release Reference response exceeds its byte limit")
        try:
            payload = json.loads(response.body)
            return _KnowledgeBaseReleaseReferenceResource.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise _contract_error("KSS returned an invalid Release Reference contract") from error


def _require_exact_reference(
    resource: _KnowledgeBaseReleaseReferenceResource,
    request: ProductionAgentReleaseReferenceRequest,
) -> None:
    expected = request.model_dump(mode="python")
    observed = resource.model_dump(
        mode="python",
        include=set(expected),
    )
    if observed != expected:
        raise _contract_error("KSS Release Reference response changed the exact request")


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
        "Verify the KSS Release Reference endpoint and strict client contract.",
    )


__all__ = ["KnowledgeSourceServiceReleaseReferenceRegistrar"]
