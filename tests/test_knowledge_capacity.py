import pytest

from proof_agent.evaluation.knowledge_capacity import (
    KnowledgeCapacityMeasurements,
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
    assert first.passed is True
