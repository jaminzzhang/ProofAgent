from __future__ import annotations

from proof_agent.knowledge.chunker import MarkdownChunk


def citation_for_chunk(chunk: MarkdownChunk) -> str:
    return f"{chunk.source}#{chunk.heading.lower().replace(' ', '-')}:L{chunk.line_start}-L{chunk.line_end}"
