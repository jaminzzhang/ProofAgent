from __future__ import annotations

import re


TOKEN_RE = re.compile(r"[a-z0-9]+")
CJK_RE = re.compile(r"[\u3400-\u9fff]+")


def token_overlap_score(query: str, content: str) -> float:
    """Simple deterministic relevance score used instead of model embeddings in v1."""

    query_tokens = set(TOKEN_RE.findall(query.lower()))
    content_tokens = set(TOKEN_RE.findall(content.lower()))
    token_score = 0.0
    if query_tokens and content_tokens:
        token_score = len(query_tokens.intersection(content_tokens)) / len(query_tokens)
    return max(token_score, _cjk_phrase_overlap_score(query, content))


def _cjk_phrase_overlap_score(query: str, content: str) -> float:
    query_text = "".join(CJK_RE.findall(query))
    content_text = "".join(CJK_RE.findall(content))
    if not query_text or not content_text:
        return 0.0
    longest = _longest_common_substring_length(query_text, content_text)
    if longest < 2:
        return 0.0
    return min(1.0, longest / 4)


def _longest_common_substring_length(left: str, right: str) -> int:
    previous = [0] * (len(right) + 1)
    best = 0
    for left_char in left:
        current = [0] * (len(right) + 1)
        for index, right_char in enumerate(right, start=1):
            if left_char != right_char:
                continue
            current[index] = previous[index - 1] + 1
            best = max(best, current[index])
        previous = current
    return best
