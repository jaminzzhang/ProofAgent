from __future__ import annotations

from pathlib import Path

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.knowledge.chunker import MarkdownChunk, load_markdown_chunks
from proof_agent.knowledge.citations import citation_for_chunk
from proof_agent.knowledge.evaluator import token_overlap_score


class LocalKnowledgeProvider:
    def __init__(self, knowledge_path: Path) -> None:
        self.knowledge_path = knowledge_path
        self._chunks = load_markdown_chunks(knowledge_path)

    def retrieve(self, query: str, *, top_k: int = 3) -> tuple[EvidenceChunk, ...]:
        scored = sorted(
            (
                (token_overlap_score(query, chunk.content), chunk)
                for chunk in self._chunks
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        evidence: list[EvidenceChunk] = []
        for score, chunk in scored[:top_k]:
            if score <= 0:
                continue
            evidence.append(_evidence_from_chunk(chunk, score))
        return tuple(evidence)


def _evidence_from_chunk(chunk: MarkdownChunk, score: float) -> EvidenceChunk:
    return EvidenceChunk(
        source=chunk.source,
        content=f"{chunk.content}\n\nCitation: {citation_for_chunk(chunk)}",
        score=score,
        status=EvidenceStatus.ACCEPTED,
    )
