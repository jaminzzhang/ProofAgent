from __future__ import annotations

import re


TOKEN_RE = re.compile(r"[a-z0-9]+")


def token_overlap_score(query: str, content: str) -> float:
    query_tokens = set(TOKEN_RE.findall(query.lower()))
    content_tokens = set(TOKEN_RE.findall(content.lower()))
    if not query_tokens or not content_tokens:
        return 0.0
    return len(query_tokens.intersection(content_tokens)) / len(query_tokens)
