from proof_agent.contracts import EvidenceChunk, EvidenceStatus, ValidationStatus
from proof_agent.control.validators.citations import validate_citations_supported_by_evidence


def test_citation_validator_accepts_known_evidence_source() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts. Citation: discount-policy.md#travel:L1-L3",
        (
            EvidenceChunk(
                source="discount-policy.md",
                content="Travel meals require receipts.",
                admission_score=0.8,
                status=EvidenceStatus.CANDIDATE,
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
                admission_score=0.8,
                status=EvidenceStatus.CANDIDATE,
            ),
        ),
    )

    assert result.status == ValidationStatus.FAILED
    assert result.metadata["unsupported_sources"] == ("unknown.md",)


def test_citation_validator_accepts_evidence_citation_field() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts. Citation: travel-policy.md#meals:L10-L18",
        (
            EvidenceChunk(
                source="policy://travel#meals",
                content="Travel meals require receipts.",
                admission_score=0.8,
                status=EvidenceStatus.CANDIDATE,
                citation="travel-policy.md#meals:L10-L18",
            ),
        ),
    )

    assert result.status == ValidationStatus.PASSED


def test_citation_validator_fails_when_strict_answer_has_no_supported_refs() -> None:
    result = validate_citations_supported_by_evidence(
        "Travel meals require receipts.",
        (
            EvidenceChunk(
                source="Travel Policy",
                content="Travel meals require receipts.",
                admission_score=0.8,
                status=EvidenceStatus.CANDIDATE,
                citation="travel-policy.md#meals:L10-L18",
            ),
        ),
        observation_records=(
            {
                "source_refs": ["Travel Policy"],
                "citation_refs": ["travel-policy.md#meals:L10-L18"],
            },
        ),
        require_supported_citation=True,
    )

    assert result.status == ValidationStatus.FAILED
    assert result.metadata["missing_supported_citation"] is True


def test_citation_validator_accepts_local_index_citation_ref() -> None:
    citation = (
        "knowledge://source/ks_myks/document/doc_1c78ce23/"
        "revision/rev_1c78ce23#node=82ac0f38"
    )
    result = validate_citations_supported_by_evidence(
        f"平安 2025 年营收 10,505 亿元。Citation: {citation}",
        (
            EvidenceChunk(
                source="knowledge://source/ks_myks/document/doc_1c78ce23",
                content="2025 年营收 10,505 亿元。",
                admission_score=1.0,
                status=EvidenceStatus.CANDIDATE,
                citation=citation,
            ),
        ),
        observation_records=(
            {
                "source_refs": ["knowledge://source/ks_myks/document/doc_1c78ce23"],
                "citation_refs": [citation],
            },
        ),
        require_supported_citation=True,
    )

    assert result.status == ValidationStatus.PASSED
    assert result.metadata["cited_sources"] == (citation,)


def test_citation_validator_rejects_unsupported_local_index_ref() -> None:
    unsupported = (
        "knowledge://source/ks_other/document/doc_other/"
        "revision/rev_other#node=unknown"
    )
    result = validate_citations_supported_by_evidence(
        f"平安 2025 年营收 10,505 亿元。Citation: {unsupported}",
        (
            EvidenceChunk(
                source="knowledge://source/ks_myks/document/doc_1c78ce23",
                content="2025 年营收 10,505 亿元。",
                admission_score=1.0,
                status=EvidenceStatus.CANDIDATE,
                citation=(
                    "knowledge://source/ks_myks/document/doc_1c78ce23/"
                    "revision/rev_1c78ce23#node=82ac0f38"
                ),
            ),
        ),
        require_supported_citation=True,
    )

    assert result.status == ValidationStatus.FAILED
    assert result.metadata["unsupported_sources"] == (unsupported,)
