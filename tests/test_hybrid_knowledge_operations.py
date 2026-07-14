from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.delivery.knowledge_operations import (
    KnowledgeOperationsHealthSources,
    KnowledgeStageLatency,
    build_operations_projection,
)
from proof_agent.observability.api.app import create_app


def fake_health_sources() -> KnowledgeOperationsHealthSources:
    return KnowledgeOperationsHealthSources(
        source_id="ks_hybrid_index",
        telemetry_complete=True,
        queue_age_seconds=15.0,
        retry_backlog=3,
        review_backlog=12,
        parser_escalation_count=2,
        ingestion_throughput_documents_per_hour=44.0,
        gpu_queue_depth=4,
        gpu_utilization_percent=73.0,
        embedding_backlog=9,
        index_lag_seconds=21.0,
        orphan_count=0,
        publication_age_seconds=3600.0,
        rebuild_state="idle",
        scheduler_queue_p95_ms=120.0,
        retrieval_service_p95_ms=380.0,
        stage_latencies=(KnowledgeStageLatency(stage="rerank", p95_ms=210.0),),
        no_evidence_rate=0.03,
        clarification_rate=0.08,
        conflict_rate=0.01,
        refusal_rate=0.02,
        degradation_rate=0.0,
        citation_failure_count=0,
        complete_evidence_slot_coverage_rate=0.94,
        unauthorized_candidate_exposure=0,
        wrong_version_or_precedence=0,
        unresolvable_formal_citation=0,
        advice_under_authority_uncertainty=0,
        high_severity_unsupported_claim=0,
    )


def test_operations_projection_is_trace_safe_and_includes_queue_time() -> None:
    projection = build_operations_projection(fake_health_sources())

    assert projection.retrieval_p95_ms == 500.0
    assert projection.retrieval_p95_ms >= projection.scheduler_queue_p95_ms
    assert projection.unauthorized_candidate_exposure == 0
    assert projection.release_blocker_count == 0
    assert not hasattr(projection, "raw_rule_content")


def test_incomplete_telemetry_is_a_release_blocker() -> None:
    projection = build_operations_projection(
        fake_health_sources().model_copy(update={"telemetry_complete": False})
    )

    assert projection.release_blocker_count == 1
    assert projection.telemetry_complete is False


def test_hybrid_operations_endpoint_returns_safe_projection(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
        knowledge_operations_provider=lambda source_id: fake_health_sources(),
    )
    client = TestClient(app)
    created = client.post(
        "/api/config/knowledge-sources",
        json={
            "source_id": "ks_hybrid_index",
            "name": "Hybrid Index Policies",
            "provider": "hybrid_index",
            "params": {},
        },
    )
    assert created.status_code == 200
    response = client.get("/api/config/knowledge-sources/ks_hybrid_index/operations")

    assert response.status_code == 200
    assert response.json()["review_backlog"] == 12
    assert response.json()["scheduler_queue_p95_ms"] == 120.0
    assert "raw_rule_content" not in response.json()
