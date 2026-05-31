from __future__ import annotations

from collections.abc import Iterable

from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ValidationResult, ValidationStatus


def evaluate_evidence(
    chunks: Iterable[EvidenceChunk], *, min_count: int, min_score: float
) -> ValidationResult:
    """Accept only evidence chunks that meet both status and score thresholds."""

    chunk_tuple = tuple(chunks)
    accepted = tuple(
        chunk
        for chunk in chunk_tuple
        if chunk.status != EvidenceStatus.REJECTED
        and chunk.admission_score is not None
        and chunk.admission_score >= min_score
    )
    passed = len(accepted) >= min_count
    accepted_ids = {id(chunk) for chunk in accepted}
    return ValidationResult(
        validator_name="evidence",
        status=ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        reason="Evidence threshold passed." if passed else "Evidence threshold failed.",
        metadata={
            "accepted_count": len(accepted),
            "rejected_count": len(chunk_tuple) - len(accepted),
            "accepted_sources": tuple(chunk.source for chunk in accepted),
            "evidence": tuple(
                {
                    "source": chunk.source,
                    "citation": chunk.citation,
                    "admission_score": chunk.admission_score,
                    "provider_native_score": chunk.provider_native_score,
                    "fusion_rank": chunk.fusion_rank,
                    "status": "accepted" if id(chunk) in accepted_ids else "rejected",
                }
                for chunk in chunk_tuple
            ),
            "admission_scores": tuple(chunk.admission_score for chunk in chunk_tuple),
            "min_count": min_count,
            "min_score": min_score,
        },
    )
