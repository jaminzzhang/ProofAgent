from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from proof_agent.contracts import EvidenceChunk, ValidationResult, ValidationStatus


MARKDOWN_SOURCE_RE = re.compile(r"\b([A-Za-z0-9_.-]+\.md)(?:#[^\s\]\),;]*)?")
URI_REF_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*://[^\s\]\),;]+)")
TRAILING_REF_PUNCTUATION = ".,;:!?)]}。！？；，、"


def validate_citations_supported_by_evidence(
    text: str,
    evidence: Iterable[EvidenceChunk],
    *,
    observation_records: Iterable[Mapping[str, object]] = (),
    require_supported_citation: bool = False,
) -> ValidationResult:
    cited_sources = _cited_refs(text)
    return _validate_cited_refs(
        cited_sources,
        evidence,
        observation_records=observation_records,
        require_supported_citation=require_supported_citation,
    )


def validate_citation_refs_supported_by_evidence(
    citation_refs: Iterable[str],
    evidence: Iterable[EvidenceChunk],
    *,
    observation_records: Iterable[Mapping[str, object]] = (),
    require_supported_citation: bool = False,
) -> ValidationResult:
    """Validate structured citation refs without extracting refs from prose."""

    cited_sources = _structured_cited_refs(citation_refs)
    return _validate_cited_refs(
        cited_sources,
        evidence,
        observation_records=observation_records,
        require_supported_citation=require_supported_citation,
    )


def _validate_cited_refs(
    cited_sources: tuple[str, ...],
    evidence: Iterable[EvidenceChunk],
    *,
    observation_records: Iterable[Mapping[str, object]],
    require_supported_citation: bool,
) -> ValidationResult:
    supported_sources = _supported_refs(evidence, observation_records)
    unsupported = tuple(
        source for source in cited_sources if source not in supported_sources
    )
    has_supported_citation = any(source in supported_sources for source in cited_sources)
    missing_supported_citation = (
        require_supported_citation and bool(supported_sources) and not has_supported_citation
    )
    passed = (
        not unsupported
        and not missing_supported_citation
        and (not cited_sources or has_supported_citation)
    )
    return ValidationResult(
        validator_name="citations",
        status=ValidationStatus.PASSED if passed else ValidationStatus.FAILED,
        reason="Citations are supported by accepted evidence."
        if passed
        else "Citations include unsupported sources."
        if unsupported
        else "Missing supported citation references.",
        metadata={
            "cited_sources": cited_sources,
            "supported_sources": tuple(sorted(supported_sources)),
            "unsupported_sources": unsupported,
            "missing_supported_citation": missing_supported_citation,
        },
    )


def _supported_refs(
    evidence: Iterable[EvidenceChunk],
    observation_records: Iterable[Mapping[str, object]],
) -> set[str]:
    supported_sources = set[str]()
    for chunk in evidence:
        if chunk.status == "rejected":
            continue
        _add_supported_ref(supported_sources, chunk.source)
        _add_supported_ref(supported_sources, chunk.citation)
    for observation in observation_records:
        for source in _string_refs(observation.get("source_refs")):
            _add_supported_ref(supported_sources, source)
        for citation in _string_refs(observation.get("citation_refs")):
            _add_supported_ref(supported_sources, citation)
    return supported_sources


def _add_supported_ref(supported_sources: set[str], value: object) -> None:
    if not isinstance(value, str):
        return
    ref = _clean_ref(value)
    if not ref:
        return
    supported_sources.add(ref)
    supported_sources.update(_markdown_source_refs(ref))


def _cited_refs(text: str) -> tuple[str, ...]:
    refs: list[str] = []
    for match in URI_REF_RE.finditer(text):
        _append_unique(refs, _clean_ref(match.group(1)))
    for match in MARKDOWN_SOURCE_RE.finditer(text):
        _append_unique(refs, _clean_ref(match.group(1)))
    return tuple(refs)


def _structured_cited_refs(citation_refs: Iterable[str]) -> tuple[str, ...]:
    refs: list[str] = []
    for ref in citation_refs:
        if isinstance(ref, str):
            _append_unique(refs, ref.strip())
    return tuple(refs)


def _markdown_source_refs(ref: str) -> tuple[str, ...]:
    return tuple(
        _clean_ref(match.group(1))
        for match in MARKDOWN_SOURCE_RE.finditer(ref)
        if _clean_ref(match.group(1))
    )


def _clean_ref(ref: str) -> str:
    return ref.strip().rstrip(TRAILING_REF_PUNCTUATION)


def _append_unique(refs: list[str], ref: str) -> None:
    if ref and ref not in refs:
        refs.append(ref)


def _string_refs(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, Mapping):
        return ()
    if not isinstance(value, Iterable):
        return ()
    return tuple(str(item) for item in value if isinstance(item, str) and item.strip())
