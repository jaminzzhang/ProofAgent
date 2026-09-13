"""One accepted-evidence projection for initial and repair model requests."""

from typing import Any
import json

from pydantic import ValidationError

from proof_agent.contracts import EvidenceChunk, EvidenceStatus
from proof_agent.errors import ProofAgentError


def unique_answer_evidence(evidence: tuple[EvidenceChunk, ...]) -> tuple[EvidenceChunk, ...]:
    """Deduplicate retrieval repeats, retaining applicability/conflict/authority changes."""
    unique: dict[str, EvidenceChunk] = {}
    for chunk in evidence:
        if chunk.status is not EvidenceStatus.ACCEPTED:
            continue
        try:
            # model_copy is intentionally unchecked; validate again at the answer boundary.
            checked = EvidenceChunk.model_validate(chunk.model_dump(mode="python", warnings=False))
        except (ValueError, ValidationError, RecursionError):
            raise ProofAgentError(
                "PA_KNOWLEDGE_002",
                "Accepted evidence integrity check failed.",
                "Retrieve and admit valid source evidence again.",
            ) from None
        identity = checked.model_dump(mode="json")
        for key in ("provider_native_score", "fusion_rank", "admission_score"):
            identity.pop(key, None)
        identity["metadata"] = {key: value for key, value in identity["metadata"].items() if key != "observed_at"}
        unique.setdefault(json.dumps(identity, sort_keys=True, ensure_ascii=False), checked)
    return tuple(unique.values())


def answer_evidence_records(evidence: tuple[EvidenceChunk, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for checked in unique_answer_evidence(evidence):
        record: dict[str, Any] = {
            "source": checked.source,
            "citation": checked.citation,
            "content": checked.content,
        }
        if checked.structured_data is not None:
            record.update(
                {
                    "evidence_id": checked.evidence_id,
                    "binding_id": checked.binding_id,
                    "source_id": checked.source_id,
                    "source_version_id": checked.source_version_id,
                    "document_id": checked.document_id,
                    "chunk_id": checked.chunk_id,
                    "structured_data": checked.structured_data.model_dump(mode="json"),
                }
            )
        records.append(record)
    return records
