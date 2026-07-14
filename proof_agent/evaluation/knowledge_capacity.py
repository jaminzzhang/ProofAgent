"""Frozen workload envelope for Hybrid Knowledge capacity acceptance."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from math import ceil
from pathlib import Path
from threading import Barrier
from time import monotonic
from typing import Protocol, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator
import yaml  # type: ignore[import-untyped]

from proof_agent.contracts._base import FrozenModel
from proof_agent.evaluation.errors import EvaluationInputError


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


class KnowledgeCapacityExperimentPlan(_CapacityModel):
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

    @model_validator(mode="after")
    def validate_workload_shape(self) -> Self:
        if len(self.active_run_ids) != 5 or len(set(self.active_run_ids)) != 5:
            raise ValueError("capacity experiment requires exactly five active runs")
        if self.docling_pages + self.paddle_pages != self.changed_pages:
            raise ValueError("parser page mix must equal changed pages")
        return self


class CapacityRunSample(_CapacityModel):
    queue_ms: float = Field(ge=0.0)
    service_ms: float = Field(ge=0.0)
    raw_measurement_ref: str = Field(min_length=1)


class CapacityIngestionSample(_CapacityModel):
    changed_documents: int = Field(gt=0)
    duration_seconds: float = Field(gt=0.0)
    approved_to_active_seconds: float = Field(ge=0.0)
    raw_measurement_ref: str = Field(min_length=1)


CapacityRunWorker = Callable[[str, str, int, bool], CapacityRunSample]
CapacityIngestionWorker = Callable[[], CapacityIngestionSample]


class KnowledgeCapacityEnvelope(_CapacityModel):
    measurements: KnowledgeCapacityMeasurements
    interference_percent: float = Field(ge=-100.0)
    passed: bool
    blocking_reasons: tuple[str, ...]
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class KnowledgeCapacityThresholds(_CapacityModel):
    retrieval_p95_limit_ms: float = Field(gt=0.0)
    approved_to_active_limit_seconds: float = Field(gt=0.0)
    ingestion_interference_limit_percent: float = Field(gt=0.0)


class KnowledgeCapacitySuite(_CapacityModel):
    schema_version: str = Field(pattern=r"^insurance-knowledge-capacity\.v1$")
    plan: KnowledgeCapacityExperimentPlan
    thresholds: KnowledgeCapacityThresholds


class KnowledgeCapacityDriver(Protocol):
    """Deployment adapter for governed online samples and offline ingestion."""

    def run_sample(
        self,
        run_id: str,
        phase: str,
        sample_index: int,
        warmup: bool,
    ) -> CapacityRunSample: ...

    def run_ingestion(self) -> CapacityIngestionSample: ...


def seal_capacity_report(
    *,
    measurements: KnowledgeCapacityMeasurements,
    retrieval_p95_limit_ms: float = 5000.0,
    approved_to_active_limit_seconds: float = 14400.0,
    ingestion_interference_limit_percent: float = 10.0,
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
    if interference > ingestion_interference_limit_percent:
        reasons.append("ingestion interference exceeded the sealed threshold")
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


def load_capacity_suite(path: Path | str) -> KnowledgeCapacitySuite:
    """Load the approved workload description without inventing thresholds."""

    suite_path = Path(path)
    try:
        raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise EvaluationInputError(
            f"Unable to read Knowledge capacity suite: {suite_path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise EvaluationInputError("Knowledge capacity suite contains invalid YAML") from exc
    if not isinstance(raw, dict):
        raise EvaluationInputError("Knowledge capacity suite must be a mapping")
    try:
        return KnowledgeCapacitySuite.model_validate(raw)
    except ValidationError as exc:
        raise EvaluationInputError(f"Invalid Knowledge capacity suite: {exc}") from exc


def seal_capacity_suite(
    suite: KnowledgeCapacitySuite,
    measurements: KnowledgeCapacityMeasurements,
) -> KnowledgeCapacityEnvelope:
    return seal_capacity_report(
        measurements=measurements,
        retrieval_p95_limit_ms=suite.thresholds.retrieval_p95_limit_ms,
        approved_to_active_limit_seconds=(suite.thresholds.approved_to_active_limit_seconds),
        ingestion_interference_limit_percent=(
            suite.thresholds.ingestion_interference_limit_percent
        ),
    )


def execute_capacity_suite(
    *,
    suite: KnowledgeCapacitySuite,
    driver: KnowledgeCapacityDriver,
) -> KnowledgeCapacityEnvelope:
    """Launch the fixed experiment through a deployment-owned governed driver."""

    measurements = run_capacity_experiment(
        plan=suite.plan,
        run_worker=driver.run_sample,
        ingestion_worker=driver.run_ingestion,
    )
    return seal_capacity_suite(suite, measurements)


def run_capacity_experiment(
    *,
    plan: KnowledgeCapacityExperimentPlan,
    run_worker: CapacityRunWorker,
    ingestion_worker: CapacityIngestionWorker,
) -> KnowledgeCapacityMeasurements:
    """Measure five bounded workers in idle and active-ingestion phases."""

    idle = _run_capacity_phase(plan, "idle", run_worker)
    ingestion_barrier = Barrier(6)
    with ThreadPoolExecutor(max_workers=6, thread_name_prefix="knowledge-capacity") as pool:
        ingestion_future = pool.submit(_run_ingestion, ingestion_barrier, ingestion_worker)
        active_futures = tuple(
            pool.submit(
                _run_capacity_worker,
                ingestion_barrier,
                run_id,
                "active_ingestion",
                plan,
                run_worker,
            )
            for run_id in plan.active_run_ids
        )
        active = tuple(sample for future in active_futures for sample in future.result())
        ingestion = ingestion_future.result()
    if ingestion.changed_documents != plan.changed_documents:
        raise ValueError("ingestion sample changed-document count does not match the plan")
    idle_totals = tuple(item.queue_ms + item.service_ms for item, _ in idle)
    active_totals = tuple(item.queue_ms + item.service_ms for item, _ in active)
    active_full = tuple(full_ms for _, full_ms in active)
    return KnowledgeCapacityMeasurements(
        corpus_digest=plan.corpus_digest,
        suite_digest=plan.suite_digest,
        changed_documents=plan.changed_documents,
        changed_pages=plan.changed_pages,
        docling_pages=plan.docling_pages,
        paddle_pages=plan.paddle_pages,
        table_density=plan.table_density,
        model_revision=plan.model_revision,
        retrieval_profile_revision=plan.retrieval_profile_revision,
        hardware_label=plan.hardware_label,
        active_run_ids=plan.active_run_ids,
        reviewer_count=plan.reviewer_count,
        target_agent_count=plan.target_agent_count,
        warmup_count=plan.warmup_count,
        sample_count=plan.sample_count,
        retrieval_p50_ms=_percentile(active_totals, 0.50),
        retrieval_p95_ms=_percentile(active_totals, 0.95),
        retrieval_p99_ms=_percentile(active_totals, 0.99),
        scheduler_queue_p95_ms=_percentile(tuple(item.queue_ms for item, _ in active), 0.95),
        full_run_p95_ms=_percentile(active_full, 0.95),
        ingestion_documents_per_hour=(
            ingestion.changed_documents / ingestion.duration_seconds * 3600.0
        ),
        idle_retrieval_p95_ms=_percentile(idle_totals, 0.95),
        active_ingestion_retrieval_p95_ms=_percentile(active_totals, 0.95),
        approved_to_active_seconds=ingestion.approved_to_active_seconds,
        idle_raw_measurement_refs=tuple(item.raw_measurement_ref for item, _ in idle),
        active_ingestion_raw_measurement_refs=(
            *(item.raw_measurement_ref for item, _ in active),
            ingestion.raw_measurement_ref,
        ),
    )


def _run_capacity_phase(
    plan: KnowledgeCapacityExperimentPlan,
    phase: str,
    worker: CapacityRunWorker,
) -> tuple[tuple[CapacityRunSample, float], ...]:
    barrier = Barrier(5)
    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="knowledge-capacity") as pool:
        futures = tuple(
            pool.submit(_run_capacity_worker, barrier, run_id, phase, plan, worker)
            for run_id in plan.active_run_ids
        )
        return tuple(sample for future in futures for sample in future.result())


def _run_capacity_worker(
    barrier: Barrier,
    run_id: str,
    phase: str,
    plan: KnowledgeCapacityExperimentPlan,
    worker: CapacityRunWorker,
) -> tuple[tuple[CapacityRunSample, float], ...]:
    barrier.wait()
    for index in range(plan.warmup_count):
        worker(run_id, phase, index, True)
    samples: list[tuple[CapacityRunSample, float]] = []
    for index in range(plan.sample_count):
        started = monotonic()
        sample = worker(run_id, phase, index, False)
        elapsed_ms = (monotonic() - started) * 1000.0
        samples.append((sample, max(elapsed_ms, sample.queue_ms + sample.service_ms)))
    return tuple(samples)


def _run_ingestion(
    barrier: Barrier,
    worker: CapacityIngestionWorker,
) -> CapacityIngestionSample:
    barrier.wait()
    return worker()


def _percentile(values: tuple[float, ...], quantile: float) -> float:
    if not values:
        raise ValueError("capacity percentile requires samples")
    ordered = sorted(values)
    return ordered[max(0, ceil(quantile * len(ordered)) - 1)]


__all__ = [
    "CapacityIngestionSample",
    "CapacityRunSample",
    "KnowledgeCapacityEnvelope",
    "KnowledgeCapacityDriver",
    "KnowledgeCapacityMeasurements",
    "KnowledgeCapacityExperimentPlan",
    "KnowledgeCapacitySuite",
    "KnowledgeCapacityThresholds",
    "execute_capacity_suite",
    "load_capacity_suite",
    "run_capacity_experiment",
    "seal_capacity_report",
    "seal_capacity_suite",
]
