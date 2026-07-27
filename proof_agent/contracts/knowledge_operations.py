"""Trace-safe Knowledge operations health and durable workflow records."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import ConfigDict, Field, model_validator

from proof_agent.contracts._base import FrozenModel, StrictFrozenModel


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
    index_lag_seconds: float = Field(default=0.0, ge=0)
    orphan_count: int = Field(default=0, ge=0)
    publication_age_seconds: float | None = Field(default=None, ge=0.0)
    rebuild_state: Literal["idle", "queued", "running", "failed", "unavailable"] = (
        "unavailable"
    )
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


class KnowledgeIngestionAttempt(StrictFrozenModel):
    """One identity-preserving execution history entry for an ingestion job."""

    attempt_id: str = Field(min_length=1, max_length=255)
    job_id: str = Field(min_length=1, max_length=255)
    attempt_number: int = Field(ge=1)
    initiation: Literal["automatic", "manual"]
    state: Literal["running", "succeeded", "failed", "cancelled"]
    fencing_token: int = Field(ge=1)
    worker_id: str | None = Field(default=None, min_length=1, max_length=512)
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    failure_classification: Literal[
        "recoverable",
        "recoverable_exhausted",
        "review_required",
        "non_recoverable",
    ] | None = None
    outcome_detail: str | None = Field(default=None, min_length=1, max_length=1_000)
    started_at: str
    updated_at: str
    completed_at: str | None = None

    @model_validator(mode="after")
    def require_lifecycle_shape(self) -> Self:
        terminal = self.state in {"succeeded", "failed", "cancelled"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal ingestion attempts require completed_at")
        if self.state == "failed":
            if self.failure_code is None or self.failure_classification is None:
                raise ValueError("failed ingestion attempts require bounded failure facts")
        elif self.failure_code is not None or self.failure_classification is not None:
            raise ValueError("only failed ingestion attempts accept failure facts")
        return self


class PreparedHybridKnowledgePublication(StrictFrozenModel):
    """One-use result of asynchronous Hybrid publication preparation."""

    validation_id: str = Field(min_length=1, max_length=255)
    operation_id: str = Field(min_length=1, max_length=255)
    attempt_id: str = Field(min_length=1, max_length=255)
    fencing_token: int = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=255)
    source_draft_version_id: str = Field(min_length=1, max_length=255)
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_id: str = Field(min_length=1, max_length=255)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staged_projection_id: str = Field(min_length=1, max_length=255)
    attestation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    smoke_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: Literal["prepared", "consumed", "invalidated"]
    prepared_at: str
    consumed_at: str | None = None

    @model_validator(mode="after")
    def require_consumption_shape(self) -> Self:
        if (self.state == "consumed") != (self.consumed_at is not None):
            raise ValueError("only consumed publications require consumed_at")
        return self


__all__ = [
    "KnowledgeIngestionAttempt",
    "KnowledgeOperationsHealthSources",
    "KnowledgeStageLatency",
    "PreparedHybridKnowledgePublication",
]
