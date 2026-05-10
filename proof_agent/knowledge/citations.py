from __future__ import annotations

from proof_agent.knowledge.chunker import MarkdownChunk


def citation_for_chunk(chunk: MarkdownChunk) -> str:
    """Build a stable citation string from chunk source, heading, and line range."""

    return f"{chunk.source}#{chunk.heading.lower().replace(' ', '-')}:L{chunk.line_start}-L{chunk.line_end}"
