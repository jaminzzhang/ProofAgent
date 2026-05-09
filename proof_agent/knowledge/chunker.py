from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarkdownChunk:
    source: str
    heading: str
    content: str
    line_start: int
    line_end: int


def load_markdown_chunks(knowledge_path: Path) -> tuple[MarkdownChunk, ...]:
    chunks: list[MarkdownChunk] = []
    for path in sorted(knowledge_path.glob("*.md")):
        chunks.extend(chunk_markdown_file(path))
    return tuple(chunks)


def chunk_markdown_file(path: Path) -> tuple[MarkdownChunk, ...]:
    lines = path.read_text(encoding="utf-8").splitlines()
    chunks: list[MarkdownChunk] = []
    heading = path.stem
    start_line = 1
    buffer: list[str] = []

    def flush(end_line: int) -> None:
        content = "\n".join(line for line in buffer if line.strip()).strip()
        if content:
            chunks.append(
                MarkdownChunk(
                    source=path.name,
                    heading=heading,
                    content=content,
                    line_start=start_line,
                    line_end=end_line,
                )
            )

    for index, line in enumerate(lines, start=1):
        if line.startswith("#"):
            flush(index - 1)
            heading = line.lstrip("#").strip()
            start_line = index
            buffer = [line]
        else:
            buffer.append(line)
    flush(len(lines))
    return tuple(chunks)
