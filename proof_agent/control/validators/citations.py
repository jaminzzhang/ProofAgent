from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from proof_agent.contracts import EvidenceChunk, ValidationResult, ValidationStatus


CITATION_RE = re.compile(r"\b([A-Za-z0-9_.-]+\.md)#")


def validate_citations_supported_by_evidence(
    text: str,
    evidence: Iterable[EvidenceChunk],
    *,
    observation_records: Iterable[Mapping[str, object]] = (),
    require_supported_citation: bool = False,
) -> ValidationResult:
    supported_sources = set[str]()
    for chunk in evidence:
        if chunk.status == "rejected":
            continue
        supported_sources.add(chunk.source)
        if chunk.citation:
            supported_sources.update(CITATION_RE.findall(chunk.citation))
    for observation in observation_records:
        supported_sources.update(_string_refs(observation.get("source_refs")))
        for citation in _string_refs(observation.get("citation_refs")):
            supported_sources.update(CITATION_RE.findall(citation))
    cited_sources = tuple(CITATION_RE.findall(text))
    unsupported = tuple(
        source for source in cited_sources if source not in supported_sources
    )
    missing_supported_citation = (
        require_supported_citation and bool(supported_sources) and not cited_sources
    )
    passed = (
        not unsupported
        and not missing_supported_citation
        and (not cited_sources or bool(supported_sources))
    )
    return ValidationResult(
        validator_name="citations",
        status=ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        reason="Citations are supported by accepted evidence."
        if passed
        else "Missing supported citation references."
        if missing_supported_citation
        else "Citations include unsupported sources.",
        metadata={
            "cited_sources": cited_sources,
            "supported_sources": tuple(sorted(supported_sources)),
            "unsupported_sources": unsupported,
            "missing_supported_citation": missing_supported_citation,
        },
    )


def _string_refs(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Mapping):
        return ()
    if not isinstance(value, Iterable):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item.strip())
