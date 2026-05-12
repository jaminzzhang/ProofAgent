import pytest

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.control.validators.evidence import evaluate_evidence


def test_enough_evidence_passes() -> None:
    chunks = [
        EvidenceChunk(
            source="customer-support-policy.md",
            content="Meals are reimbursed up to 50.",
            score=0.9,
            status=EvidenceStatus.CANDIDATE,
        ),
        EvidenceChunk(
            source="customer-support-policy.md",
            content="Receipts are required.",
            score=0.8,
            status=EvidenceStatus.CANDIDATE,
        ),
    ]
    result = evaluate_evidence(chunks, min_count=2, min_score=0.5)
    assert result.status == "passed"
    assert result.metadata["accepted_count"] == 2
    assert result.metadata["evidence"][0]["status"] == "accepted"


def test_weak_evidence_fails() -> None:
    result = evaluate_evidence([], min_count=2, min_score=0.5)
    assert result.status == "failed"


def test_low_score_candidate_is_rejected_by_validator() -> None:
    result = evaluate_evidence(
        [
            EvidenceChunk(
                source="customer-support-policy.md",
                content="Receipts are required.",
                score=0.1,
                status=EvidenceStatus.CANDIDATE,
            )
        ],
        min_count=1,
        min_score=0.5,
    )

    assert result.status == "failed"
    assert result.metadata["evidence"][0]["status"] == "rejected"


def test_evidence_metadata_is_immutable() -> None:
    chunk = EvidenceChunk(
        source="customer-support-policy.md",
        content="Receipts are required.",
        score=0.8,
        status=EvidenceStatus.CANDIDATE,
        metadata={"document_id": "policy"},
    )

    with pytest.raises(TypeError):
        chunk.metadata["document_id"] = "changed"
