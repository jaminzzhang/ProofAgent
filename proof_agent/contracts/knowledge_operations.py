"""Trace-safe health facts supplied by Hybrid Knowledge telemetry adapters."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from proof_agent.contracts._base import FrozenModel


class _OperationsModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeStageLatency(_OperationsModel):
    stage: str = Field(min_length=1, pattern=r"^[a-z0-9_.-]+$")
    p95_ms: float = Field(ge=0.0)


class KnowledgeOperationsHealthSources(_OperationsModel):
    """Safe counters and timings supplied by governed telemetry adapters."""

    source_id: str = Field(min_length=1)
    telemetry_complete: bool = False
    queue_age_seconds: float = Field(default=0.0, ge=0.0)
    retry_backlog: int = Field(default=0, ge=0)
    review_backlog: int = Field(default=0, ge=0)
    parser_escalation_count: int = Field(default=0, ge=0)
    ingestion_throughput_documents_per_hour: float = Field(default=0.0, ge=0.0)
    gpu_queue_depth: int = Field(default=0, ge=0)
    gpu_utilization_percent: float = Field(default=0.0, ge=0.0, le=100.0)
    embedding_backlog: int = Field(default=0, ge=0)
    index_lag_seconds: float = Field(default=0.0, ge=0.0)
    orphan_count: int = Field(default=0, ge=0)
    publication_age_seconds: float | None = Field(default=None, ge=0.0)
    rebuild_state: Literal["idle", "queued", "running", "failed", "unavailable"] = "unavailable"
    scheduler_queue_p95_ms: float = Field(default=0.0, ge=0.0)
    retrieval_service_p95_ms: float = Field(default=0.0, ge=0.0)
    stage_latencies: tuple[KnowledgeStageLatency, ...] = ()
    no_evidence_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    clarification_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    conflict_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    refusal_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    degradation_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    citation_failure_count: int = Field(default=0, ge=0)
    complete_evidence_slot_coverage_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    unauthorized_candidate_exposure: int = Field(default=0, ge=0)
    wrong_version_or_precedence: int = Field(default=0, ge=0)
    unresolvable_formal_citation: int = Field(default=0, ge=0)
    advice_under_authority_uncertainty: int = Field(default=0, ge=0)
    high_severity_unsupported_claim: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def require_unique_stage_latencies(self) -> Self:
        stages = tuple(item.stage for item in self.stage_latencies)
        if len(stages) != len(set(stages)):
            raise ValueError("stage latency identities must be unique")
        return self


__all__ = ["KnowledgeOperationsHealthSources", "KnowledgeStageLatency"]
