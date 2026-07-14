import pytest
from threading import Lock
import time

from proof_agent.evaluation.knowledge_capacity import (
    CapacityIngestionSample,
    CapacityRunSample,
    KnowledgeCapacityExperimentPlan,
    KnowledgeCapacityMeasurements,
    KnowledgeCapacitySuite,
    KnowledgeCapacityThresholds,
    execute_capacity_suite,
    run_capacity_experiment,
    seal_capacity_report,
)


def measurements(*, active_runs: int = 5, ingestion_samples: int = 1):
    return KnowledgeCapacityMeasurements(
        corpus_digest="a" * 64,
        suite_digest="b" * 64,
        changed_documents=20,
        changed_pages=400,
        docling_pages=350,
        paddle_pages=50,
        table_density=0.3,
        model_revision="model-v1",
        retrieval_profile_revision="profile-v1",
        hardware_label="test-gpu",
        active_run_ids=tuple(f"run-{index}" for index in range(active_runs)),
        reviewer_count=2,
        target_agent_count=3,
        warmup_count=10,
        sample_count=100,
        retrieval_p50_ms=1000,
        retrieval_p95_ms=4000,
        retrieval_p99_ms=4800,
        scheduler_queue_p95_ms=500,
        full_run_p95_ms=30000,
        ingestion_documents_per_hour=40,
        idle_retrieval_p95_ms=3500,
        active_ingestion_retrieval_p95_ms=4200,
        approved_to_active_seconds=7200,
        idle_raw_measurement_refs=("s3://test/idle.json",),
        active_ingestion_raw_measurement_refs=tuple(
            f"s3://test/active-{index}.json" for index in range(ingestion_samples)
        ),
    )


def test_capacity_report_requires_five_active_runs_and_ingestion_sample() -> None:
    with pytest.raises(ValueError, match="five active runs"):
        seal_capacity_report(measurements=measurements(active_runs=4))
    with pytest.raises(ValueError, match="active ingestion sample"):
        seal_capacity_report(measurements=measurements(ingestion_samples=0))


def test_capacity_digest_and_interference_are_stable() -> None:
    first = seal_capacity_report(measurements=measurements())
    second = seal_capacity_report(measurements=measurements())

    assert first == second
    assert first.interference_percent == pytest.approx(20.0)
    assert first.passed is False
    assert "ingestion interference" in first.blocking_reasons[0]


def test_capacity_experiment_runs_five_authorized_workers_with_ingestion_overlap() -> None:
    lock = Lock()
    active = 0
    maximum_active = 0
    phases: list[str] = []

    def run_worker(run_id: str, phase: str, sample_index: int, warmup: bool):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            phases.append(phase)
        time.sleep(0.005)
        with lock:
            active -= 1
        return CapacityRunSample(
            queue_ms=100,
            service_ms=900 if phase == "idle" else 1100,
            raw_measurement_ref=f"fixture://{phase}/{run_id}/{sample_index}/{warmup}",
        )

    result = run_capacity_experiment(
        plan=KnowledgeCapacityExperimentPlan(
            corpus_digest="a" * 64,
            suite_digest="b" * 64,
            changed_documents=20,
            changed_pages=400,
            docling_pages=350,
            paddle_pages=50,
            table_density=0.3,
            model_revision="model-v1",
            retrieval_profile_revision="profile-v1",
            hardware_label="test-gpu",
            active_run_ids=tuple(f"run-{index}" for index in range(5)),
            reviewer_count=2,
            target_agent_count=3,
            warmup_count=1,
            sample_count=2,
        ),
        run_worker=run_worker,
        ingestion_worker=lambda: CapacityIngestionSample(
            changed_documents=20,
            duration_seconds=1800,
            approved_to_active_seconds=7200,
            raw_measurement_ref="fixture://ingestion/run",
        ),
    )

    assert maximum_active == 5
    assert {"idle", "active_ingestion"} <= set(phases)
    assert result.active_run_ids == tuple(f"run-{index}" for index in range(5))
    assert result.ingestion_documents_per_hour == pytest.approx(40.0)
    assert result.active_ingestion_retrieval_p95_ms > result.idle_retrieval_p95_ms


def test_capacity_suite_executes_workers_instead_of_accepting_precomputed_measurements() -> None:
    calls: list[str] = []
    suite = KnowledgeCapacitySuite(
        schema_version="insurance-knowledge-capacity.v1",
        plan=KnowledgeCapacityExperimentPlan(
            corpus_digest="a" * 64,
            suite_digest="b" * 64,
            changed_documents=1,
            changed_pages=1,
            docling_pages=1,
            paddle_pages=0,
            table_density=0,
            model_revision="model-v1",
            retrieval_profile_revision="profile-v1",
            hardware_label="approved-hardware",
            active_run_ids=tuple(f"run-{index}" for index in range(5)),
            reviewer_count=1,
            target_agent_count=1,
            warmup_count=1,
            sample_count=1,
        ),
        thresholds=KnowledgeCapacityThresholds(
            retrieval_p95_limit_ms=5_000,
            approved_to_active_limit_seconds=14_400,
            ingestion_interference_limit_percent=10,
        ),
    )

    class Driver:
        def run_sample(self, run_id, phase, sample_index, warmup):
            calls.append(f"{phase}:{run_id}:{sample_index}:{warmup}")
            return CapacityRunSample(
                queue_ms=1,
                service_ms=2,
                raw_measurement_ref=f"driver://{phase}/{run_id}/{sample_index}/{warmup}",
            )

        def run_ingestion(self):
            calls.append("ingestion")
            return CapacityIngestionSample(
                changed_documents=1,
                duration_seconds=1,
                approved_to_active_seconds=2,
                raw_measurement_ref="driver://ingestion",
            )

    envelope = execute_capacity_suite(suite=suite, driver=Driver())

    assert envelope.passed is True
    assert "ingestion" in calls
    assert len([call for call in calls if call.startswith("active_ingestion:")]) == 10
