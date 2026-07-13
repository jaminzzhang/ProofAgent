"""Provider-neutral exact citation binding for Hybrid Knowledge Rule Units."""

from __future__ import annotations

from urllib.parse import quote, urlsplit


def validate_hybrid_citation_binding(
    citation_uri: str,
    *,
    source_id: str,
    document_id: str,
    revision_id: str,
) -> None:
    """Require one canonical Knowledge citation to bind its exact lineage IDs."""

    parsed = urlsplit(citation_uri)
    if parsed.scheme != "knowledge":
        raise ValueError("Hybrid citations must use the knowledge scheme")
    expected_path = (
        f"/{quote(source_id, safe='')}/document/"
        f"{quote(document_id, safe='')}/revision/"
        f"{quote(revision_id, safe='')}"
    )
    if parsed.netloc != "source" or parsed.path != expected_path:
        raise ValueError("Hybrid citation does not bind its exact lineage")


__all__ = ["validate_hybrid_citation_binding"]
