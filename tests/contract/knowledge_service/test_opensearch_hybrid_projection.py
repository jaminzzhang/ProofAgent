from __future__ import annotations

import pytest

from knowledge_source_service.adapters.opensearch.hybrid_projection import (
    OpenSearchHybridProjection,
)
from knowledge_source_service.ports.search_projection import ProjectionEvidenceUnit


pytestmark = pytest.mark.search_integration


def test_opensearch_projection_keeps_lexical_sparse_and_dense_lanes_distinct(
    kss_search_endpoint: str,
) -> None:
    projection = OpenSearchHybridProjection(endpoint=kss_search_endpoint)
    index_identity = "kss-test-generation-a1b2c3d4"
    documents = (
        ProjectionEvidenceUnit(
            evidence_unit_id="unit-flight-delay",
            knowledge_source_id="source-policy",
            knowledge_source_version_id="source-version-1",
            text="flight delay benefit is 300 CNY after four hours",
            content_hash=f"sha256:{'a' * 64}",
            dense_vector=(1.0, 0.0, 0.0, 0.0),
            sparse_vector={"flight": 1.0, "delay": 0.8, "benefit": 0.5},
        ),
        ProjectionEvidenceUnit(
            evidence_unit_id="unit-medical-waiting",
            knowledge_source_id="source-policy",
            knowledge_source_version_id="source-version-1",
            text="medical waiting period is thirty days",
            content_hash=f"sha256:{'b' * 64}",
            dense_vector=(0.0, 1.0, 0.0, 0.0),
            sparse_vector={"medical": 1.0, "waiting": 0.8, "period": 0.5},
        ),
    )
    try:
        attestation = projection.rebuild(
            index_identity=index_identity,
            dense_dimension=4,
            documents=documents,
        )
        projection.verify_generation(attestation)
        result = projection.query(
            index_identity=index_identity,
            lexical_query="flight delay benefit",
            dense_vector=(1.0, 0.0, 0.0, 0.0),
            sparse_vector={"flight": 1.0, "delay": 0.8},
            top_k=2,
        )
    finally:
        projection.delete_generation(index_identity)
        projection.close()

    assert attestation.document_count == 2
    assert attestation.index_identity == index_identity
    assert attestation.mapping_digest.startswith("sha256:")
    assert [hit.lane for hit in result.lexical] == ["lexical"]
    assert [hit.lane for hit in result.sparse] == ["sparse"]
    assert [hit.lane for hit in result.dense] == ["dense", "dense"]
    assert result.lexical[0].evidence_unit_id == "unit-flight-delay"
    assert result.sparse[0].evidence_unit_id == "unit-flight-delay"
    assert result.dense[0].evidence_unit_id == "unit-flight-delay"
    assert result.lexical[0].native_score != result.dense[0].native_score
