"""Bounded external-Knowledge HTTP; authority stays with guarded transport and secrets."""

import json
from math import isfinite
from typing import Any

from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.contracts.external_knowledge import ExternalKnowledgeBinding
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.errors import ProofAgentError


def knowledge_error(reason: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002", f"External Knowledge request failed: {reason}.",
        "Check the configured source, server credential reference and permitted Service API endpoint.",
    )


def validate_query(question: str) -> None:
    if not isinstance(question, str) or not question.strip() or len(question) > 250:
        raise knowledge_error("query_invalid")


class ExternalKnowledgeHttp:
    def __init__(self, *, binding: ExternalKnowledgeBinding, http_client: GuardedHttpClient,
                 secret_provider: SecretProvider, timeout_seconds: float = 10.0,
                 max_response_bytes: int = 1024 * 1024) -> None:
        if (not isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60
                or not 0 < max_response_bytes <= 4 * 1024 * 1024):
            raise ValueError("External Knowledge request limits are invalid")
        self._binding = binding
        self._http = (http_client.restricted(max_redirects=0, max_attempts_per_hop=1,
                       max_response_bytes=max_response_bytes)
                      if isinstance(http_client, GuardedHttpsClient) else http_client)
        self._secrets = secret_provider
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        binding = self._binding
        try:
            handle = binding.credential_ref
            if handle.protocol_id != self._secrets.protocol_id:
                raise ValueError("credential protocol mismatch")
            material = self._secrets.resolve(handle)
            if material.provider_version_id != handle.version_id:
                raise ValueError("credential version mismatch")
            token = material.reveal_for_use().decode("utf-8")
            if not token or len(token) > 16_384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise ValueError("invalid credential material")
        except Exception:
            raise knowledge_error("credential_unavailable") from None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
        if binding.tenant_id is not None:
            headers["x-tenant-id"] = binding.tenant_id
        try:
            response = self._http.request("POST", f"{binding.endpoint}{path}", headers=headers,
                body=json.dumps(payload, ensure_ascii=False).encode(), timeout_seconds=self._timeout)
        except Exception:
            raise knowledge_error("transport_failed") from None
        if response.status_code != 200:
            reason = {401: "unauthorized", 403: "forbidden", 429: "rate_limited",
                      404: "dataset_unavailable" if binding.provider == "dify" else "namespace_unavailable"}.get(response.status_code, "http_failed")
            raise knowledge_error(reason)
        content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            raise knowledge_error("response_invalid")
        if len(response.body) > self._max_bytes:
            raise knowledge_error("response_too_large")
        try:
            return json.loads(response.body)
        except (ValueError, RecursionError):
            raise knowledge_error("response_invalid") from None
