"""Optional-dependency-safe bounded document routing for Local Index snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
from typing import Any

from proof_agent.capabilities.knowledge.contracts import KnowledgeDocumentRoutingSelection
from proof_agent.capabilities.knowledge.local_index_snapshot import LocalIndexRuntimeDocument
from proof_agent.capabilities.models.normalization import (
    ModelOutputNormalizationError,
    parse_model_contract,
)
from proof_agent.capabilities.models.protocol import ModelProvider
from proof_agent.contracts import ModelCallRole, ModelMessage, ModelRequest, ModelRole
from proof_agent.errors import ProofAgentError

MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES = 100
MAX_ROUTING_METADATA_SCALARS = 20
MAX_ROUTING_METADATA_SCALAR_CHARS = 300
DOCUMENT_ROUTING_MODEL_TIMEOUT_SECONDS = 30.0
ROUTING_METADATA_KEYS = (
    "title",
    "description",
    "tags",
    "document_type",
    "business_category",
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class LocalIndexDocumentRoutingResult:
    """Selected immutable document revisions plus their trace-safe routing summary."""

    selected_documents: tuple[LocalIndexRuntimeDocument, ...]
    summary: Mapping[str, Any]


class LocalIndexDocumentRoutingFailure(ProofAgentError):
    """Bounded routing failure with a trace-safe pre-failure projection."""

    def __init__(self, message: str, *, summary: Mapping[str, Any] | None = None) -> None:
        super().__init__(
            "PA_KNOWLEDGE_002",
            message,
            "Retry retrieval after checking the Source-owned Local Index routing model.",
        )
        self.summary = summary


@dataclass(frozen=True)
class _ProjectedDocument:
    document: LocalIndexRuntimeDocument
    filename: str
    routing_metadata: Mapping[str, list[str]]
    metadata_matched: bool


def route_snapshot_documents(
    query: str,
    *,
    documents: tuple[LocalIndexRuntimeDocument, ...],
    routing_model: ModelProvider,
    selection_budget: int,
    snapshot_id: str,
) -> LocalIndexDocumentRoutingResult:
    """Select a bounded set of immutable snapshot documents through one routing model call."""

    if (
        isinstance(selection_budget, bool)
        or not isinstance(selection_budget, int)
        or not 1 <= selection_budget <= 20
    ):
        raise _routing_failure("Local Index document selection budget is invalid.")

    projected = tuple(_project_document(query, document) for document in documents)
    matched = tuple(candidate for candidate in projected if candidate.metadata_matched)
    eligible = matched or projected
    routed_candidates = tuple(
        sorted(eligible, key=lambda candidate: candidate.document.document_id)[
            :MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES
        ]
    )
    candidate_truncated = len(eligible) > MAX_ROUTING_MODEL_DOCUMENT_CANDIDATES

    if not routed_candidates:
        return LocalIndexDocumentRoutingResult(
            selected_documents=(),
            summary=_routing_summary(
                snapshot_id=snapshot_id,
                candidate_count=len(documents),
                routed_candidates=(),
                selected_documents=(),
                selection_budget=selection_budget,
                candidate_truncated=candidate_truncated,
            ),
        )

    if matched and len(routed_candidates) <= selection_budget:
        selected_documents = tuple(candidate.document for candidate in routed_candidates)
        return LocalIndexDocumentRoutingResult(
            selected_documents=selected_documents,
            summary=_routing_summary(
                snapshot_id=snapshot_id,
                candidate_count=len(documents),
                routed_candidates=routed_candidates,
                selected_documents=selected_documents,
                selection_budget=selection_budget,
                candidate_truncated=candidate_truncated,
                selection_reason="metadata_match_selected",
                selected_document_reason="metadata_match_selected",
            ),
        )

    prompt_payload = {
        "query": query,
        "selection_budget": selection_budget,
        "document_candidates": [
            {
                "document_id": candidate.document.document_id,
                "filename": candidate.filename,
                "routing_metadata": dict(candidate.routing_metadata),
            }
            for candidate in routed_candidates
        ],
    }
    request = ModelRequest(
        messages=(
            ModelMessage(
                role=ModelRole.SYSTEM,
                content=(
                    "You are a document routing classifier. Return only one JSON object, "
                    "with exactly these keys: selected_document_ids and reason. "
                    "selected_document_ids must be an array of document_id strings from the "
                    "provided document_candidates, with at most selection_budget entries. "
                    "Do not echo the input JSON. Do not add document_candidates, query, or "
                    "selection_budget to the response."
                ),
            ),
            ModelMessage(
                role=ModelRole.USER,
                content=json.dumps(prompt_payload, ensure_ascii=True, sort_keys=True),
            ),
        ),
        provider=routing_model.provider_name,
        model=routing_model.model_name,
        timeout_seconds=DOCUMENT_ROUTING_MODEL_TIMEOUT_SECONDS,
        response_format="json",
        metadata={"role": ModelCallRole.ROUTING.value},
    )
    try:
        response = routing_model.generate(request)
    except Exception as exc:
        summary = _routing_summary(
            snapshot_id=snapshot_id,
            candidate_count=len(documents),
            routed_candidates=routed_candidates,
            selected_documents=(),
            selection_budget=selection_budget,
            candidate_truncated=candidate_truncated,
            selection_reason="routing_model_failed",
            error_code=_error_code(exc),
        )
        if _is_policy_error(exc):
            setattr(exc, "summary", summary)
            raise
        raise _routing_failure(
            "Local Index document routing model call failed.",
            summary=summary,
        ) from exc
    try:
        selection = parse_model_contract(
            response.content,
            KnowledgeDocumentRoutingSelection,
            ModelCallRole.ROUTING.value,
        )
    except ModelOutputNormalizationError as exc:
        raise _routing_failure(
            "Local Index document routing model output is invalid.",
            summary=_routing_summary(
                snapshot_id=snapshot_id,
                candidate_count=len(documents),
                routed_candidates=routed_candidates,
                selected_documents=(),
                selection_budget=selection_budget,
                candidate_truncated=candidate_truncated,
                selection_reason="routing_model_failed",
                error_code=_error_code(exc),
            ),
        ) from exc

    try:
        selected_documents = _selected_documents(
            selection,
            routed_candidates=routed_candidates,
            selection_budget=selection_budget,
        )
    except ProofAgentError as exc:
        raise _routing_failure(
            exc.message,
            summary=_routing_summary(
                snapshot_id=snapshot_id,
                candidate_count=len(documents),
                routed_candidates=routed_candidates,
                selected_documents=(),
                selection_budget=selection_budget,
                candidate_truncated=candidate_truncated,
                selection_reason="routing_model_failed",
                error_code=_error_code(exc),
            ),
        ) from exc
    return LocalIndexDocumentRoutingResult(
        selected_documents=selected_documents,
        summary=_routing_summary(
            snapshot_id=snapshot_id,
            candidate_count=len(documents),
            routed_candidates=routed_candidates,
            selected_documents=selected_documents,
            selection_budget=selection_budget,
            candidate_truncated=candidate_truncated,
        ),
    )


def _project_document(query: str, document: LocalIndexRuntimeDocument) -> _ProjectedDocument:
    filename = _safe_basename(document.filename)
    routing_metadata = _project_routing_metadata(document.routing_metadata)
    stem = PurePosixPath(filename).stem
    terms = [filename, stem]
    terms.extend(_TOKEN_RE.findall(stem.casefold()))
    for values in routing_metadata.values():
        terms.extend(values)
    metadata_matched = any(_term_matches_query(query, term) for term in terms)
    return _ProjectedDocument(
        document=document,
        filename=filename,
        routing_metadata=routing_metadata,
        metadata_matched=metadata_matched,
    )


def _project_routing_metadata(metadata: Mapping[str, Any]) -> dict[str, list[str]]:
    projected: dict[str, list[str]] = {}
    remaining = MAX_ROUTING_METADATA_SCALARS
    for key in ROUTING_METADATA_KEYS:
        if remaining == 0:
            break
        if key not in metadata:
            continue
        values = _bounded_scalar_strings(metadata[key], limit=remaining)
        if values:
            projected[key] = values
            remaining -= len(values)
    return projected


def _bounded_scalar_strings(value: Any, *, limit: int) -> list[str]:
    values: list[str] = []
    stack = [value]
    while stack and len(values) < limit:
        item = stack.pop()
        if isinstance(item, Mapping):
            stack.extend(item[key] for key in reversed(sorted(item, key=str)))
        elif isinstance(item, list | tuple):
            stack.extend(reversed(item))
        elif isinstance(item, str | int | float | bool):
            text = str(item).strip()[:MAX_ROUTING_METADATA_SCALAR_CHARS]
            if text:
                values.append(text)
    return values


def _safe_basename(filename: str) -> str:
    return PurePosixPath(filename.replace("\\", "/")).name


def _term_matches_query(query: str, term: str) -> bool:
    normalized_query = _normalized_text(query)
    normalized_term = _normalized_text(term)
    if normalized_term and normalized_term in normalized_query:
        return True
    compact_query = _compact_match_text(query)
    compact_term = _compact_match_text(term)
    return bool(compact_term and compact_term in compact_query)


def _normalized_text(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _compact_match_text(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _selected_documents(
    selection: KnowledgeDocumentRoutingSelection,
    *,
    routed_candidates: tuple[_ProjectedDocument, ...],
    selection_budget: int,
) -> tuple[LocalIndexRuntimeDocument, ...]:
    selected_ids = selection.selected_document_ids
    if len(selected_ids) > selection_budget:
        raise _routing_failure("Local Index document routing selection exceeds its budget.")
    if len(set(selected_ids)) != len(selected_ids):
        raise _routing_failure("Local Index document routing selection contains duplicate ids.")
    candidates_by_id = {
        candidate.document.document_id: candidate.document for candidate in routed_candidates
    }
    if any(document_id not in candidates_by_id for document_id in selected_ids):
        raise _routing_failure("Local Index document routing selection contains an unknown id.")
    return tuple(candidates_by_id[document_id] for document_id in selected_ids)


def _routing_summary(
    *,
    snapshot_id: str,
    candidate_count: int,
    routed_candidates: tuple[_ProjectedDocument, ...],
    selected_documents: tuple[LocalIndexRuntimeDocument, ...],
    selection_budget: int,
    candidate_truncated: bool,
    selection_reason: str | None = None,
    selected_document_reason: str = "routing_model_selected",
    error_code: str | None = None,
) -> dict[str, Any]:
    actual_selection_reason = selection_reason or (
        "routing_model_selected" if selected_documents else "routing_empty"
    )
    document_routing = {
        "snapshot_id": snapshot_id,
        "candidate_count": candidate_count,
        "routed_candidate_count": len(routed_candidates),
        "selected_count": len(selected_documents),
        "candidate_truncated": candidate_truncated,
        "selection_budget": selection_budget,
        "selection_reason": actual_selection_reason,
    }
    if error_code is not None:
        document_routing["error_code"] = error_code
    return {
        "document_candidates": [
            {
                "document_id": candidate.document.document_id,
                "revision_id": candidate.document.revision_id,
                "filename": candidate.filename,
                "routing_metadata_keys": sorted(candidate.routing_metadata),
                "metadata_matched": candidate.metadata_matched,
                "selection_reason": (
                    "metadata_match" if candidate.metadata_matched else "metadata_fallback"
                ),
            }
            for candidate in routed_candidates
        ],
        "selected_documents": [
            {
                "document_id": document.document_id,
                "revision_id": document.revision_id,
                "selection_reason": selected_document_reason,
            }
            for document in selected_documents
        ],
        "document_routing": document_routing,
    }


def _routing_failure(
    message: str,
    *,
    summary: Mapping[str, Any] | None = None,
) -> LocalIndexDocumentRoutingFailure:
    return LocalIndexDocumentRoutingFailure(message, summary=summary)


def _error_code(exc: Exception) -> str:
    return getattr(exc, "code", "PA_KNOWLEDGE_002")


def _is_policy_error(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "PA_POLICY_001"
