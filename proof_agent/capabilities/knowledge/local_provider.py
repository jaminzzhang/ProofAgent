from __future__ import annotations

from pathlib import Path
from typing import Self

from proof_agent.capabilities.knowledge.capabilities import RetrievalCapabilities
from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.capabilities.knowledge.chunker import MarkdownChunk, load_markdown_chunks
from proof_agent.capabilities.knowledge.citations import citation_for_chunk
from proof_agent.capabilities.knowledge.evaluator import token_overlap_score
from proof_agent.contracts.manifest import KnowledgeConfig


class LocalMarkdownProvider:
    """In-memory deterministic retriever for the local Enterprise QA template."""

    def __init__(self, knowledge_path: Path) -> None:
        self.knowledge_path = knowledge_path
        self._chunks = load_markdown_chunks(knowledge_path)

    @classmethod
    def from_config(cls, knowledge_config: KnowledgeConfig) -> Self:
        return cls(Path(knowledge_config.params["path"]))

    @property
    def provider_name(self) -> str:
        return "local_markdown"

    @property
    def capabilities(self) -> RetrievalCapabilities:
        return RetrievalCapabilities()

    def retrieve(self, query: str, *, top_k: int | None = None) -> tuple[EvidenceChunk, ...]:
        """Rank Markdown chunks by simple token overlap for reproducible tests."""

        limit = top_k or 3
        scored = sorted(
            (
                (token_overlap_score(query, chunk.content), chunk)
                for chunk in self._chunks
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        evidence: list[EvidenceChunk] = []
        for score, chunk in scored[:limit]:
            if score <= 0:
                continue
            evidence.append(_evidence_from_chunk(chunk, score))
        return tuple(evidence)


def _evidence_from_chunk(chunk: MarkdownChunk, score: float) -> EvidenceChunk:
    """Attach a source citation directly to the evidence content."""

    return EvidenceChunk(
        source=chunk.source,
        content=chunk.content,
        provider_native_score=score,
        admission_score=score,
        status=EvidenceStatus.CANDIDATE,
        citation=citation_for_chunk(chunk),
        metadata={"heading": chunk.heading, "line_start": chunk.line_start, "line_end": chunk.line_end},
    )


LocalKnowledgeProvider = LocalMarkdownProvider
