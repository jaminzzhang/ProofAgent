from __future__ import annotations

from datetime import UTC, date, datetime
from time import monotonic, sleep
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationValidationAuthority,
)
from proof_agent.capabilities.knowledge.hybrid.model_clients import (
    ImmediateKnowledgeModelWorkScheduler,
)
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    OpenSearchProjectionError,
    rrf_pipeline_name,
)
from proof_agent.capabilities.knowledge.hybrid.ports import HybridSearchRequest
from proof_agent.contracts.insurance_authorization import InstitutionAuthorizationContext
from proof_agent.evaluation.knowledge_capacity import (
    CapacityIngestionSample,
    CapacityRunSample,
    KnowledgeCapacityExperimentPlan,
    KnowledgeCapacitySuite,
    KnowledgeCapacityThresholds,
    execute_capacity_suite,
)
from test_hybrid_postgres_s3 import _cleanup, _environment, _request


pytestmark = pytest.mark.hybrid_integration


def test_real_hybrid_capacity_envelope_has_five_runs_and_ingestion_interference() -> None:
    env: dict[str, Any] = _environment()
    try:
        scheduler = ImmediateKnowledgeModelWorkScheduler()
        publication = env["service"].publish(env["request"])
        search = HybridSearchRequest(
            identity=env["identity"],
            manifest_root_sha256=publication.manifest_ref.sha256,
            query_text="Exact integration insurance rule",
            query_embedding=(1.0, 0.0),
            source_publication_seq=1,
            authorization=InstitutionAuthorizationContext(),
            as_of_date=date(2026, 7, 14),
            lexical_budget=10,
            dense_budget=10,
            rrf_window=10,
            rrf_pipeline=rrf_pipeline_name(rank_constant=60),
            rrf_rank_constant=60,
            limit=10,
        )

        class Driver:
            def run_sample(self, run_id, phase, sample_index, warmup):
                started = monotonic()
                while True:
                    try:
                        scheduled = scheduler.submit_and_wait(
                            kind="embedding",
                            priority="online",
                            timeout_seconds=30,
                            operation=lambda _timeout, _cancellation: env["index"].search(
                                search
                            ),
                        )
                        break
                    except OpenSearchProjectionError as exc:
                        if (
                            "content projection state does not match candidate" not in str(exc)
                            or monotonic() - started >= 30
                        ):
                            raise
                        sleep(0.01)
                assert scheduled.value
                elapsed_ms = (monotonic() - started) * 1000.0
                return CapacityRunSample(
                    queue_ms=scheduled.queue_time_ms,
                    service_ms=max(
                        scheduled.service_time_ms,
                        elapsed_ms - scheduled.queue_time_ms,
                    ),
                    raw_measurement_ref=(
                        f"integration://{phase}/{run_id}/{sample_index}/{int(warmup)}"
                    ),
                )

            def run_ingestion(self):
                started = monotonic()

                def publish(_timeout, _cancellation):
                    second = _request(
                        env["source_id"],
                        env["generation"],
                        env["identity"],
                        rule_suffix="capacity-two",
                        publication_seq_from=2,
                    )
                    env["repository"].advance_source_candidate(
                        source_id=env["source_id"],
                        expected_source_draft_version_id=(env["request"].source_draft_version_id),
                        expected_candidate_digest=env["request"].candidate_digest,
                        source_draft_version_id=second.source_draft_version_id,
                        candidate_digest=second.candidate_digest,
                    )
                    env["repository"].register_validation(
                        HybridPublicationValidationAuthority(
                            validation_id=second.validation_id,
                            source_id=second.source_id,
                            source_draft_version_id=second.source_draft_version_id,
                            candidate_digest=second.candidate_digest,
                            generation_id=second.generation.generation_id,
                            validated_at=datetime.now(UTC),
                            validated_by="capacity-integration",
                        )
                    )
                    return env["service"].publish(second)

                scheduled = scheduler.submit_and_wait(
                    kind="docling",
                    priority="offline",
                    timeout_seconds=300,
                    operation=publish,
                )
                duration = monotonic() - started
                return CapacityIngestionSample(
                    changed_documents=1,
                    duration_seconds=duration,
                    approved_to_active_seconds=duration,
                    raw_measurement_ref=(
                        f"integration://ingestion/{scheduled.service_time_ms:.6f}"
                    ),
                )

        envelope = execute_capacity_suite(
            suite=KnowledgeCapacitySuite(
                schema_version="insurance-knowledge-capacity.v1",
                plan=KnowledgeCapacityExperimentPlan(
                    corpus_digest="a" * 64,
                    suite_digest="b" * 64,
                    changed_documents=1,
                    changed_pages=1,
                    docling_pages=1,
                    paddle_pages=0,
                    table_density=0.0,
                    model_revision="integration-model",
                    retrieval_profile_revision="integration-profile",
                    hardware_label="docker-compose-hybrid-test",
                    active_run_ids=tuple(f"authorized-run-{index}" for index in range(5)),
                    reviewer_count=1,
                    target_agent_count=1,
                    warmup_count=1,
                    sample_count=2,
                ),
                thresholds=KnowledgeCapacityThresholds(
                    retrieval_p95_limit_ms=30_000,
                    approved_to_active_limit_seconds=300,
                    # This integration test proves orchestration and evidence shape;
                    # production uses the approved ten-percent gate.
                    ingestion_interference_limit_percent=1_000_000,
                ),
            ),
            driver=Driver(),
        )
        assert envelope.passed
        assert len(envelope.measurements.active_run_ids) == 5
        assert envelope.measurements.active_ingestion_raw_measurement_refs
    finally:
        _cleanup(env)
