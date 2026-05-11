from __future__ import annotations

import re
from collections.abc import Iterable

from proof_agent.contracts import EvidenceChunk, ValidationResult, ValidationStatus


CITATION_RE = re.compile(r"\b([A-Za-z0-9_.-]+\.md)#")


def validate_citations_supported_by_evidence(
    text: str, evidence: Iterable[EvidenceChunk]
) -> ValidationResult:
    supported_sources = {
        chunk.source
        for chunk in evidence
        if chunk.status == "accepted"
    }
    cited_sources = tuple(CITATION_RE.findall(text))
    unsupported = tuple(
        source for source in cited_sources if source not in supported_sources
    )
    passed = not unsupported and (not cited_sources or bool(supported_sources))
    return ValidationResult(
        validator_name="citations",
        status=ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        reason="Citations are supported by accepted evidence."
        if passed
        else "Citations include unsupported sources.",
        metadata={
            "cited_sources": cited_sources,
            "supported_sources": tuple(sorted(supported_sources)),
            "unsupported_sources": unsupported,
        },
    )
