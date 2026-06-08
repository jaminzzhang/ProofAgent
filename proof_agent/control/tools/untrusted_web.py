from __future__ import annotations

import re

from proof_agent.contracts.untrusted_web import UntrustedWebContext


_SANITIZATION_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "internal_url",
        "[INTERNAL_URL]",
        re.compile(r"https?://(?:localhost|127\.0\.0\.1|[^/\s]*\.(?:local|internal))\S*"),
    ),
    (
        "contact",
        "[CONTACT]",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "contact",
        "[CONTACT]",
        re.compile(r"(?:\+?\d[\s.-]?){10,}\d"),
    ),
    (
        "customer_id",
        "[CUSTOMER_ID]",
        re.compile(r"\bCUST[-_][A-Za-z0-9-]+\b", re.IGNORECASE),
    ),
    (
        "resource_id",
        "[RESOURCE_ID]",
        re.compile(r"\b(?:CLM|POL|CLAIM|POLICY)[-_][A-Za-z0-9-]+\b", re.IGNORECASE),
    ),
    (
        "secret",
        "[SECRET]",
        re.compile(r"\b(?:sk|pk|api|token)[-_][A-Za-z0-9]{16,}\b", re.IGNORECASE),
    ),
)


def sanitize_web_search_query(query: str) -> UntrustedWebContext:
    """Return a deterministic sanitized query before public web search."""

    sanitized = query
    categories: set[str] = set()
    for category, replacement, pattern in _SANITIZATION_PATTERNS:
        sanitized, count = pattern.subn(replacement, sanitized)
        if count:
            categories.add(category)
    return UntrustedWebContext(
        sanitized_query=sanitized,
        sanitization_applied=bool(categories),
        sanitization_categories=tuple(sorted(categories)),
        searchable=_is_searchable(sanitized),
    )


def _is_searchable(sanitized_query: str) -> bool:
    remaining = re.sub(r"\[[A-Z_]+\]", " ", sanitized_query)
    remaining = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", " ", remaining)
    return bool(remaining.strip())
