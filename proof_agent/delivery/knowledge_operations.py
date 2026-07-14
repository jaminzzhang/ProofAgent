"""Trace-safe read model for Hybrid Knowledge operations."""

from __future__ import annotations

from pydantic import Field

from proof_agent.contracts import KnowledgeOperationsHealthSources, KnowledgeStageLatency


class KnowledgeOperationsProjection(KnowledgeOperationsHealthSources):
    """Dashboard projection; excludes document, Rule Unit, and candidate identities."""

    retrieval_p95_ms: float = Field(ge=0.0)
    release_blocker_count: int = Field(ge=0)


def build_operations_projection(
    sources: KnowledgeOperationsHealthSources,
) -> KnowledgeOperationsProjection:
    """Aggregate queue and service time while preserving zero-tolerance counters."""

    security_failures = (
        sources.unauthorized_candidate_exposure
        + sources.wrong_version_or_precedence
        + max(sources.unresolvable_formal_citation, sources.citation_failure_count)
        + sources.advice_under_authority_uncertainty
        + sources.high_severity_unsupported_claim
    )
    return KnowledgeOperationsProjection(
        **sources.model_dump(),
        retrieval_p95_ms=(sources.scheduler_queue_p95_ms + sources.retrieval_service_p95_ms),
        release_blocker_count=security_failures + int(not sources.telemetry_complete),
    )


__all__ = [
    "KnowledgeOperationsHealthSources",
    "KnowledgeOperationsProjection",
    "KnowledgeStageLatency",
    "build_operations_projection",
]
