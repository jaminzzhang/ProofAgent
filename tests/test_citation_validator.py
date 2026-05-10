from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ValidationStatus
from proof_agent.validators.citations import validate_citations_supported_by_evidence


def test_citation_validator_accepts_known_evidence_source() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts. Citation: discount-policy.md#travel:L1-L3",
        (
            EvidenceChunk(
                source="discount-policy.md",
                content="Travel meals require receipts.",
                score=0.8,
                status=EvidenceStatus.ACCEPTED,
            ),
        ),
    )

    assert result.status == ValidationStatus.PASSED


def test_citation_validator_rejects_unknown_source() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts. Citation: unknown.md#travel:L1-L3",
        (
            EvidenceChunk(
                source="discount-policy.md",
                content="Travel meals require receipts.",
                score=0.8,
                status=EvidenceStatus.ACCEPTED,
            ),
        ),
    )

    assert result.status == ValidationStatus.FAILED
    assert result.metadata["unsupported_sources"] == ("unknown.md",)
