from __future__ import annotations

from pydantic import Field, HttpUrl

from proof_agent.contracts._base import FrozenModel


class UntrustedWebResult(FrozenModel):
    """One normalized public web search result that is not controlled evidence."""

    title: str
    url: HttpUrl
    snippet: str
    provider: str
    rank: int = Field(ge=1)
    domain: str
    published_at: str | None = None


class UntrustedWebContext(FrozenModel):
    """Bounded untrusted web context safe to keep separate from EvidenceChunk."""

    sanitized_query: str
    sanitization_applied: bool
    sanitization_categories: tuple[str, ...] = ()
    searchable: bool = True
    results: tuple[UntrustedWebResult, ...] = ()
