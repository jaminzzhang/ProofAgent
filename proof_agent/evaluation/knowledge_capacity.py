"""Frozen workload envelope for Hybrid Knowledge capacity acceptance."""

from __future__ import annotations

import hashlib
import json
from typing import Self

from pydantic import ConfigDict, Field, model_validator

from proof_agent.contracts._base import FrozenModel


class _CapacityModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KnowledgeCapacityMeasurements(_CapacityModel):
    corpus_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    changed_documents: int = Field(ge=0)
    changed_pages: int = Field(ge=0)
    docling_pages: int = Field(ge=0)
    paddle_pages: int = Field(ge=0)
    table_density: float = Field(ge=0.0, le=1.0)
    model_revision: str = Field(min_length=1)
    retrieval_profile_revision: str = Field(min_length=1)
    hardware_label: str = Field(min_length=1)
    active_run_ids: tuple[str, ...]
    reviewer_count: int = Field(ge=0)
    target_agent_count: int = Field(gt=0)
    warmup_count: int = Field(gt=0)
    sample_count: int = Field(gt=0)
    retrieval_p50_ms: float = Field(ge=0.0)
    retrieval_p95_ms: float = Field(ge=0.0)
    retrieval_p99_ms: float = Field(ge=0.0)
    scheduler_queue_p95_ms: float = Field(ge=0.0)
    full_run_p95_ms: float = Field(ge=0.0)
    ingestion_documents_per_hour: float = Field(ge=0.0)
    idle_retrieval_p95_ms: float = Field(gt=0.0)
    active_ingestion_retrieval_p95_ms: float = Field(gt=0.0)
    approved_to_active_seconds: float = Field(ge=0.0)
    idle_raw_measurement_refs: tuple[str, ...]
    active_ingestion_raw_measurement_refs: tuple[str, ...]

    @model_validator(mode="after")
    def validate_percentiles(self) -> Self:
        if not self.retrieval_p50_ms <= self.retrieval_p95_ms <= self.retrieval_p99_ms:
            raise ValueError("retrieval percentiles must be monotonic")
        return self


class KnowledgeCapacityEnvelope(_CapacityModel):
    measurements: KnowledgeCapacityMeasurements
    interference_percent: float = Field(ge=-100.0)
    passed: bool
    blocking_reasons: tuple[str, ...]
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def seal_capacity_report(
    *,
    measurements: KnowledgeCapacityMeasurements,
    retrieval_p95_limit_ms: float = 5000.0,
    approved_to_active_limit_seconds: float = 14400.0,
) -> KnowledgeCapacityEnvelope:
    """Validate the fixed five-run experiment and seal its canonical digest."""

    if len(measurements.active_run_ids) != 5 or len(set(measurements.active_run_ids)) != 5:
        raise ValueError("capacity report requires exactly five active runs")
    if not measurements.idle_raw_measurement_refs:
        raise ValueError("capacity report requires idle raw measurement references")
    if not measurements.active_ingestion_raw_measurement_refs:
        raise ValueError("capacity report requires an active ingestion sample")
    interference = (
        (measurements.active_ingestion_retrieval_p95_ms - measurements.idle_retrieval_p95_ms)
        / measurements.idle_retrieval_p95_ms
        * 100.0
    )
    reasons: list[str] = []
    if measurements.retrieval_p95_ms > retrieval_p95_limit_ms:
        reasons.append("hybrid retrieval P95 exceeded the sealed threshold")
    if measurements.approved_to_active_seconds > approved_to_active_limit_seconds:
        reasons.append("approved-file-to-active duration exceeded four hours")
    payload = {
        "measurements": measurements.model_dump(mode="json"),
        "interference_percent": interference,
        "passed": not reasons,
        "blocking_reasons": reasons,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeCapacityEnvelope(
        measurements=measurements,
        interference_percent=interference,
        passed=not reasons,
        blocking_reasons=tuple(reasons),
        envelope_sha256=digest,
    )


__all__ = [
    "KnowledgeCapacityEnvelope",
    "KnowledgeCapacityMeasurements",
    "seal_capacity_report",
]
