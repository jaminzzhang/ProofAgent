from __future__ import annotations

from collections.abc import Iterable

from proof_agent.contracts import EvidenceChunk, ValidationResult


def evaluate_evidence(
    chunks: Iterable[EvidenceChunk], *, min_count: int, min_score: float
) -> ValidationResult:
    chunk_tuple = tuple(chunks)
    accepted = tuple(
        chunk
        for chunk in chunk_tuple
        if chunk.status == "accepted" and chunk.score >= min_score
    )
    passed = len(accepted) >= min_count
    return ValidationResult(
        validator_name="evidence",
        status="passed" if passed else "failed",
        reason="Evidence threshold passed." if passed else "Evidence threshold failed.",
        metadata={
            "accepted_count": len(accepted),
            "rejected_count": len(chunk_tuple) - len(accepted),
            "accepted_sources": tuple(chunk.source for chunk in accepted),
            "min_count": min_count,
            "min_score": min_score,
        },
    )
