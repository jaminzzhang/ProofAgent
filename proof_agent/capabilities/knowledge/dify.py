"""Dify Knowledge API adapter; returns candidates only and never follows redirects."""

import json
from hashlib import sha256
from math import isfinite
from typing import Any

from pydantic import ValidationError

from proof_agent.contracts.external_knowledge import (
    ExternalKnowledgeBinding,
    ExternalKnowledgeCandidate,
    ExternalKnowledgeResult,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.capabilities.egress.guarded_http import GuardedHttpsClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.errors import ProofAgentError
from proof_agent.contracts.structured_evidence import parse_structured_evidence


class DifyKnowledgeProvider:
    def __init__(
        self,
        *,
        binding: ExternalKnowledgeBinding,
        http_client: GuardedHttpClient,
        secret_provider: SecretProvider,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1024 * 1024,
    ) -> None:
        if (
            not isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 60
            or not 0 < max_response_bytes <= 4 * 1024 * 1024
        ):
            raise ValueError("External Knowledge request limits are invalid")
        self._binding = binding
        self._http = (
            http_client.restricted(
                max_redirects=0, max_attempts_per_hop=1, max_response_bytes=max_response_bytes
            )
            if isinstance(http_client, GuardedHttpsClient)
            else http_client
        )
        self._secrets = secret_provider
        self._timeout = timeout_seconds
        self._max_bytes = max_response_bytes

    def query(self, question: str) -> ExternalKnowledgeResult:
        if not isinstance(question, str) or not question.strip() or len(question) > 250:
            raise _error("query_invalid")
        binding = self._binding
        try:
            handle = binding.credential_ref
            if handle.protocol_id != self._secrets.protocol_id:
                raise ValueError("credential protocol mismatch")
            material = self._secrets.resolve(handle)
            if handle.version_id is not None and material.provider_version_id != handle.version_id:
                raise ValueError("credential version mismatch")
            token = material.reveal_for_use().decode("utf-8")
            if not token or len(token) > 16_384 or any(ord(c) < 33 or ord(c) > 126 for c in token):
                raise ValueError("invalid credential material")
        except Exception:
            raise _error("credential_unavailable") from None
        payload = {
            "query": question,
            "retrieval_model": {
                "search_method": binding.retrieval.search_method,
                "reranking_enable": False,
                "top_k": binding.retrieval.top_k,
                "score_threshold_enabled": True,
                "score_threshold": binding.retrieval.score_threshold,
            },
        }
        try:
            response = self._http.request(
                "POST",
                f"{binding.endpoint}/datasets/{binding.dataset_id}/retrieve",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=json.dumps(payload, ensure_ascii=False).encode(),
                timeout_seconds=self._timeout,
            )
        except Exception:
            raise _error("transport_failed") from None
        if response.status_code != 200:
            reason = {
                401: "unauthorized",
                403: "forbidden",
                404: "dataset_unavailable",
                429: "rate_limited",
            }.get(response.status_code, "http_failed")
            raise _error(reason)
        content_type = next(
            (value for key, value in response.headers.items() if key.lower() == "content-type"), ""
        )
        if content_type.split(";")[0].strip().lower() != "application/json":
            raise _error("response_invalid")
        if len(response.body) > self._max_bytes:
            raise _error("response_too_large")
        try:
            data = json.loads(response.body)
            returned_query = data["query"]
            if isinstance(returned_query, dict):
                returned_query = returned_query["content"]
            if (
                returned_query != question
                or not isinstance(data["records"], list)
                or len(data["records"]) > 100
            ):
                raise ValueError("mismatched response")
            candidates = tuple(_candidate(row, binding=binding) for row in data["records"])
            if len({(c.document_id, c.chunk_id) for c in candidates}) != len(candidates):
                raise ValueError("duplicate candidate identity")
            return ExternalKnowledgeResult(
                binding_id=binding.binding_id,
                query=question,
                candidates=candidates[: binding.retrieval.top_k],
            )
        except (ValueError, KeyError, TypeError, AttributeError, ValidationError, RecursionError):
            raise _error("response_invalid") from None


def _candidate(row: dict[str, Any], *, binding: ExternalKnowledgeBinding) -> ExternalKnowledgeCandidate:
    segment = row["segment"]
    content = segment["content"]
    answer = segment.get("answer")
    if binding.content_format == "structured_json" and answer not in (None, ""):
        raise ValueError("Structured records cannot be mixed with Q&A answers")
    if answer is not None:
        if not isinstance(answer, str):
            raise ValueError("invalid answer")
        if answer:
            content += "\n" + answer
    document = segment.get("document")
    if document is not None and document["id"] != segment["document_id"]:
        raise ValueError("document identity mismatch")
    enabled = segment.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("invalid availability")
    return ExternalKnowledgeCandidate(
        document_id=segment["document_id"],
        chunk_id=segment["id"],
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        native_score=row["score"],
        available=enabled and segment.get("status") == "completed",
        structured_data=(parse_structured_evidence(content) if binding.content_format == "structured_json" else None),
    )


def _error(reason: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_KNOWLEDGE_002",
        f"External Knowledge request failed: {reason}.",
        "Check the configured Dataset, server credential reference and permitted Service API endpoint.",
    )
