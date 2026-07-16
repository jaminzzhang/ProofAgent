from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any
from urllib.parse import urlencode

from proof_agent.contracts.egress import ExactHttpsOrigin
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProviderResolutionError


class GuardedVaultJsonTransport:
    """Vault JSON reads routed exclusively through the admitted HTTPS boundary."""

    def __init__(
        self,
        client: GuardedHttpClient,
        *,
        endpoint_origin: str,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        if max_response_bytes < 1:
            raise ValueError("Vault response bound must be positive")
        self._client = client
        self._origin = ExactHttpsOrigin.parse(endpoint_origin)
        self._max_response_bytes = max_response_bytes

    def get_json(
        self,
        path: str,
        *,
        headers: Mapping[str, str],
        query: Mapping[str, str],
    ) -> Mapping[str, Any]:
        if (
            not path.startswith("/")
            or "//" in path
            or "?" in path
            or "#" in path
            or any(segment in {".", ".."} for segment in path.split("/"))
        ):
            raise SecretProviderResolutionError("provider_path_invalid")
        encoded_query = urlencode(query)
        url = f"{self._origin.value}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        response = self._client.request(
            "GET",
            url,
            headers={"Accept": "application/json", **dict(headers)},
        )
        if response.status_code >= 400:
            raise SecretProviderResolutionError("provider_unavailable")
        if len(response.body) > self._max_response_bytes:
            raise SecretProviderResolutionError("provider_response_invalid")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretProviderResolutionError("provider_response_invalid") from exc
        if not isinstance(payload, dict):
            raise SecretProviderResolutionError("provider_response_invalid")
        return payload
