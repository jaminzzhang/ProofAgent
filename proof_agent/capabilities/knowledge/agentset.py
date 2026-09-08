"""Agentset namespace Search API; opaque chunk identity, candidates only."""

from hashlib import sha256

from proof_agent.capabilities.knowledge.external_http import ExternalKnowledgeHttp, knowledge_error, validate_query
from proof_agent.contracts.external_knowledge import (
    AgentsetRetrievalSettings, ExternalKnowledgeBinding, ExternalKnowledgeCandidate, ExternalKnowledgeResult,
)
from proof_agent.contracts.ports.guarded_http import GuardedHttpClient
from proof_agent.contracts.ports.secret_provider import SecretProvider
from proof_agent.contracts.structured_evidence import parse_structured_evidence


class AgentsetKnowledgeProvider:
    def __init__(self, *, binding: ExternalKnowledgeBinding, http_client: GuardedHttpClient,
                 secret_provider: SecretProvider, timeout_seconds: float = 10.0,
                 max_response_bytes: int = 1024 * 1024) -> None:
        if binding.provider != "agentset" or not isinstance(binding.retrieval, AgentsetRetrievalSettings):
            raise ValueError("Agentset adapter requires an Agentset binding")
        self._binding = binding
        self._settings = binding.retrieval
        self._transport = ExternalKnowledgeHttp(binding=binding, http_client=http_client,
            secret_provider=secret_provider, timeout_seconds=timeout_seconds, max_response_bytes=max_response_bytes)

    def query(self, question: str) -> ExternalKnowledgeResult:
        validate_query(question)
        settings = self._settings
        data = self._transport.post(f"/namespace/{self._binding.namespace_id}/search", {
            "query": question, "topK": settings.top_k, "minScore": settings.score_threshold,
            "mode": settings.search_method, "rerank": settings.rerank,
            "rerankLimit": settings.top_k, "rerankModel": settings.rerank_model,
            "includeMetadata": False, "includeRelationships": False,
        })
        try:
            if data["success"] is not True or not isinstance(data["data"], list) or len(data["data"]) > 100:
                raise ValueError("invalid search response")
            candidates = tuple(ExternalKnowledgeCandidate(
                chunk_id=row["id"], content=row["text"],
                content_sha256=sha256(row["text"].encode()).hexdigest(), native_score=row["score"],
                # A successful Search row is retrievable; no Dify document status is inferred.
                available=True,
                structured_data=(parse_structured_evidence(row["text"]) if self._binding.content_format == "structured_json" else None),
            ) for row in data["data"])
            if len({item.chunk_id for item in candidates}) != len(candidates):
                raise ValueError("duplicate chunk identity")
            return ExternalKnowledgeResult(binding_id=self._binding.binding_id, query=question,
                candidates=candidates[:settings.top_k])
        except (ValueError, KeyError, TypeError, AttributeError, RecursionError):
            raise knowledge_error("response_invalid") from None
