from __future__ import annotations

import base64
import json
import os
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from proof_agent.contracts import KnowledgeSource
from proof_agent.errors import ProofAgentError


DEFAULT_INGESTION_PATH = "/api/v1/documents/ingest"


def ingest_pageindex_document(
    *,
    source: KnowledgeSource,
    filename: str,
    content_type: str,
    content: bytes,
) -> dict[str, object]:
    """Send one managed document revision to a PageIndex-compatible ingestion API."""

    params = source.params
    endpoint_env = str(params.get("ingestion_endpoint_env") or params.get("endpoint_env") or "")
    if not endpoint_env:
        raise ProofAgentError(
            "PA_KNOWLEDGE_001",
            "pageindex knowledge source is missing endpoint_env",
            "Set params.endpoint_env or params.ingestion_endpoint_env on the Knowledge Source.",
        )
    endpoint = _required_env(endpoint_env, "PageIndex endpoint")
    headers = {"Content-Type": "application/json"}
    api_key_env = params.get("api_key_env")
    if api_key_env:
        headers["Authorization"] = f"Bearer {_required_env(str(api_key_env), 'PageIndex API key')}"

    response = _post_json(
        _join_url(endpoint, str(params.get("ingestion_path") or DEFAULT_INGESTION_PATH)),
        body=_ingestion_body(source.params, filename, content_type, content),
        headers=headers,
        timeout_seconds=float(params.get("timeout_seconds") or 30.0),
    )
    return response


def _ingestion_body(
    params: Mapping[str, object],
    filename: str,
    content_type: str,
    content: bytes,
) -> dict[str, object]:
    return {
        "collection_id": str(params.get("document_id") or params.get("collection_id") or ""),
        "filename": filename,
        "content_type": content_type,
        "content_base64": base64.b64encode(content).decode("ascii"),
    }


def _required_env(env_name: str, label: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            f"{label} environment variable is not set: {env_name}",
            f"Set {env_name} or update the Knowledge Source params.",
        )
    return value


def _join_url(base_url: str, path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{base_url.rstrip('/')}{normalized_path}"


def _post_json(
    url: str,
    *,
    body: dict[str, object],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            f"PageIndex ingestion failed with HTTP {exc.code}",
            "Verify the PageIndex endpoint, document id, and API key configuration.",
        ) from exc
    except URLError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex ingestion request failed",
            "Verify the PageIndex server is reachable from this runtime.",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex ingestion response is not valid JSON",
            "Verify the PageIndex server is returning the ingestion API response shape.",
        ) from exc
    if not isinstance(parsed, dict):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex ingestion response must be a JSON object",
            "Verify the PageIndex server is returning the ingestion API response shape.",
        )
    return parsed
