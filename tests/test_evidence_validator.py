from proof_agent.contracts import EvidenceChunk
from proof_agent.control.validators.evidence import evaluate_evidence


def test_enough_evidence_passes() -> None:
    chunks = [
        EvidenceChunk(
            source="customer-support-policy.md",
            content="Meals are reimbursed up to 50.",
            score=0.9,
            status="accepted",
        ),
        EvidenceChunk(
            source="customer-support-policy.md",
            content="Receipts are required.",
            score=0.8,
            status="accepted",
        ),
    ]
    result = evaluate_evidence(chunks, min_count=2, min_score=0.5)
    assert result.status == "passed"


def test_weak_evidence_fails() -> None:
    result = evaluate_evidence([], min_count=2, min_score=0.5)
    assert result.status == "failed"
