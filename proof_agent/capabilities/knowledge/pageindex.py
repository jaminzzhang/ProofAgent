from __future__ import annotations

import json
import os
from typing import Self
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.contracts.manifest import KnowledgeConfig
from proof_agent.errors import ProofAgentError


DEFAULT_RETRIEVAL_PATH = "/api/v1/retrieval/retrieve"


class PageIndexProvider:
    """Remote PageIndex adapter that normalizes retrieval nodes into evidence."""

    def __init__(
        self,
        *,
        endpoint_env: str,
        document_id: str,
        api_key_env: str | None = None,
        retrieval_path: str = DEFAULT_RETRIEVAL_PATH,
        timeout_seconds: float = 10.0,
        thinking: bool = True,
    ) -> None:
        self.endpoint_env = endpoint_env
        self.api_key_env = api_key_env
        self.document_id = document_id
        self.retrieval_path = retrieval_path
        self.timeout_seconds = timeout_seconds
        self.thinking = thinking

    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        params = knowledge_config.params
        return cls(
            endpoint_env=str(params["endpoint_env"]),
            api_key_env=str(params["api_key_env"]) if params.get("api_key_env") else None,
            document_id=str(params["document_id"]),
            retrieval_path=str(params.get("retrieval_path") or DEFAULT_RETRIEVAL_PATH),
            timeout_seconds=float(params.get("timeout_seconds") or 10.0),
            thinking=bool(params.get("thinking", True)),
        )

    @property
    def provider_name(self) -> str:
        return "pageindex"

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        endpoint = _required_env(self.endpoint_env, "PageIndex endpoint")
        headers = {"Content-Type": "application/json"}
        if self.api_key_env is not None:
            api_key = _required_env(self.api_key_env, "PageIndex API key")
            headers["Authorization"] = f"Bearer {api_key}"

        response = _post_json(
            _join_url(endpoint, self.retrieval_path),
            body={
                "query": query,
                "document_id": self.document_id,
                "top_k": top_k,
                "thinking": self.thinking,
            },
            headers=headers,
            timeout_seconds=self.timeout_seconds,
        )
        return _normalize_pageindex_response(response, document_id=self.document_id)


def _required_env(env_name: str, label: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            f"{label} environment variable is not set: {env_name}",
            f"Set {env_name} or update the pageindex Knowledge Source params.",
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
            f"PageIndex retrieval failed with HTTP {exc.code}",
            "Verify the PageIndex endpoint, document_id, and API key configuration.",
        ) from exc
    except URLError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieval request failed",
            "Verify the PageIndex server is reachable from this runtime.",
        ) from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieval response is not valid JSON",
            "Verify the PageIndex server is returning the retrieval API response shape.",
        ) from exc
    if not isinstance(parsed, dict):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieval response must be a JSON object",
            "Verify the PageIndex server is returning the retrieval API response shape.",
        )
    return parsed


def _normalize_pageindex_response(
    response: dict[str, object], *, document_id: str
) -> tuple[EvidenceChunk, ...]:
    nodes = response.get("retrieved_nodes")
    if not isinstance(nodes, list):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieval response is missing retrieved_nodes",
            "Return a retrieved_nodes list from the PageIndex retrieval API.",
        )
    return tuple(_normalize_pageindex_node(node, document_id=document_id) for node in nodes)


def _normalize_pageindex_node(node: object, *, document_id: str) -> EvidenceChunk:
    if not isinstance(node, dict):
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieved_nodes item must be a JSON object",
            "Return object items with content and relevance_score fields.",
        )

    content = node.get("content")
    if not isinstance(content, str) or not content:
        raise ProofAgentError(
            "PA_KNOWLEDGE_002",
            "PageIndex retrieved node is missing content",
            "Return non-empty content for every retrieved node.",
        )

    node_id = _string_or_none(node.get("id"))
    file_name = _string_or_none(node.get("file_name"))
    page_number = node.get("page_number")
    source = file_name or f"pageindex://{document_id}#{node_id or 'node'}"
    citation = _pageindex_citation(
        citation=_string_or_none(node.get("citation")),
        file_name=file_name,
        page_number=page_number,
        document_id=document_id,
        node_id=node_id,
    )
    metadata = {
        "provider": "pageindex",
        "document_id": document_id,
        "node_id": node_id,
        "file_name": file_name,
        "page_number": page_number,
    }
    return EvidenceChunk(
        source=source,
        content=content,
        provider_native_score=_score(node.get("relevance_score")),
        admission_score=_score(node.get("relevance_score")),
        status=EvidenceStatus.CANDIDATE,
        citation=citation,
        metadata={key: value for key, value in metadata.items() if value is not None},
    )


def _string_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _score(value: object) -> float:
    if not isinstance(value, int | float | str):
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _pageindex_citation(
    *,
    citation: str | None,
    file_name: str | None,
    page_number: object,
    document_id: str,
    node_id: str | None,
) -> str | None:
    if citation:
        return citation
    if file_name and page_number not in (None, ""):
        return f"{file_name}#page-{page_number}"
    if node_id:
        return f"pageindex://{document_id}#{node_id}"
    return None
