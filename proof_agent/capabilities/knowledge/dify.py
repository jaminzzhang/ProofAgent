"""Dify Knowledge API adapter; returns candidates only and never follows redirects."""

from hashlib import sha256
from typing import Any

from pydantic import TypeAdapter, ValidationError

from proof_agent.contracts.external_knowledge import (
    Identifier,
    ExternalKnowledgeBinding,
    ExternalKnowledgeCandidate,
    ExternalKnowledgeResult,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.structured_evidence import parse_structured_evidence
from proof_agent.capabilities.knowledge.external_http import ExternalKnowledgeHttp, knowledge_error as _error, validate_query


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
        if binding.provider != "dify":
            raise ValueError("Dify adapter requires a Dify binding")
        self._binding = binding
        self._transport = ExternalKnowledgeHttp(binding=binding, http_client=http_client,
            secret_provider=secret_provider, timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes)

    def query(self, question: str) -> ExternalKnowledgeResult:
        validate_query(question)
        binding = self._binding
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
        data = self._transport.post(f"/datasets/{binding.dataset_id}/retrieve", payload)
        try:
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
        document_id=TypeAdapter(Identifier).validate_python(segment["document_id"]),
        chunk_id=TypeAdapter(Identifier).validate_python(segment["id"]),
        content=content,
        content_sha256=sha256(content.encode()).hexdigest(),
        native_score=row["score"],
        available=enabled and segment.get("status") == "completed",
        structured_data=(parse_structured_evidence(content) if binding.content_format == "structured_json" else None),
    )
