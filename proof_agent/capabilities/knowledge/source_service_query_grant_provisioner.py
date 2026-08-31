"""Guarded KSS transport for one exact runtime Query Grant."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from urllib.parse import urlsplit

from pydantic import ValidationError

from proof_agent.contracts import (
    ProductionAgentKnowledgeQueryGrantRequest,
    ProvisionedProductionAgentKnowledgeQueryGrant,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient, GuardedHttpResponse
from proof_agent.errors import ProofAgentError


class KnowledgeSourceServiceQueryGrantProvisioner:
    """Provision exact-Release Query authority through guarded KSS HTTPS."""

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

    def provision_query_grant(
        self,
        request: ProductionAgentKnowledgeQueryGrantRequest,
    ) -> ProvisionedProductionAgentKnowledgeQueryGrant:
        validated = ProductionAgentKnowledgeQueryGrantRequest.model_validate(
            request.model_dump(mode="python")
        )
        response = self._send(
            headers={
                "Authorization": self._authorization_header(),
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body=json.dumps(
                validated.model_dump(mode="json"),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode(),
        )
        receipt = self._receipt_from_response(response)
        if receipt.knowledge_base_release_id != validated.knowledge_base_release_id:
            raise _contract_error("KSS Query Grant response changed the exact Release")
        return receipt

    def _authorization_header(self) -> str:
        try:
            value = self._authorization_header_factory()
        except Exception as error:
            raise _contract_error("KSS Query Grant authorization is unavailable") from error
        if not isinstance(value, str):
            raise _contract_error("KSS Query Grant authorization is invalid")
        scheme, separator, token = value.partition(" ")
        if (
            not separator
            or scheme.casefold() != "bearer"
            or not token
            or token != token.strip()
            or any(character.isspace() for character in token)
        ):
            raise _contract_error("KSS Query Grant authorization is invalid")
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
                f"{self._endpoint}/v1/knowledge-query-grants",
                headers=headers,
                body=body,
                timeout_seconds=self._timeout_seconds,
            )
        except ProofAgentError:
            raise
        except Exception as error:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Knowledge Source Service Query Grant request failed at the guarded HTTPS boundary.",
                "Check the active Egress Policy and KSS operator readiness.",
            ) from error
        if 300 <= response.status_code < 400:
            raise _contract_error("KSS Query Grant redirects are forbidden")
        if response.status_code != 200:
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                f"Knowledge Source Service rejected Query Grant provisioning with HTTP {response.status_code}.",
                "Inspect the trace-safe service problem and exact Release binding.",
            )
        return response

    def _receipt_from_response(
        self,
        response: GuardedHttpResponse,
    ) -> ProvisionedProductionAgentKnowledgeQueryGrant:
        if len(response.body) > self._max_response_bytes:
            raise _contract_error("KSS Query Grant response exceeds its byte limit")
        try:
            payload = json.loads(response.body)
            return ProvisionedProductionAgentKnowledgeQueryGrant.model_validate(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
            raise _contract_error("KSS returned an invalid Query Grant contract") from error


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
        "Verify the KSS Query Grant endpoint and strict client contract.",
    )


__all__ = ["KnowledgeSourceServiceQueryGrantProvisioner"]
