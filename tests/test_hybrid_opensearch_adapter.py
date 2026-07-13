from __future__ import annotations

from datetime import date
import json
from typing import Any

import pytest

from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    build_hybrid_query,
    HttpxOpenSearchTransport,
    OpenSearchHybridIndex,
    OpenSearchProjectionError,
    OpenSearchTransportResponse,
    physical_index_name,
    project_rule_unit_document,
    rule_unit_index_mapping,
)
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchRequest,
    ProjectionBulkRequest,
    ProjectionDocument,
    SearchIndexIdentity,
)
from proof_agent.contracts import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InstitutionAuthorizationContext,
    InsuranceRuleApplicability,
    InsuranceRulePageBoundingBox,
    InsuranceRulePrecedence,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
    KnowledgeIndexGeneration,
    RuleUnitManifestEntry,
    ScopeDimension,
)
from proof_agent.contracts.hybrid_documents import BoundingBox
from proof_agent.contracts.insurance_rules import TaxonomyCondition


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def index_identity(*, index_uuid: str = "uuid-1") -> SearchIndexIdentity:
    return SearchIndexIdentity(
        generation=KnowledgeIndexGeneration(
            generation_id="generation-1",
            source_id="source-1",
            canonical_schema_version="structured-knowledge.v1",
            search_projection_version="rule-unit-search.v1",
            mapping_sha256=SHA_A,
            analyzer_sha256=SHA_B,
            embedding_model_revision="embedding@sha256:model",
            embedding_instruction_sha256=SHA_C,
            embedding_dimension=2,
            normalized=True,
        ),
        index_uuid=index_uuid,
    )


def search_request() -> HybridSearchRequest:
    return HybridSearchRequest(
        identity=index_identity(),
        manifest_root_sha256=SHA_A,
        query_text="住院给付条件",
        query_embedding=(0.1, 0.2),
        source_publication_seq=7,
        authorization=InstitutionAuthorizationContext(
            institutions=("INST-1",),
            regions=("CN-31",),
            channels=("AGENCY",),
            roles=("SPECIALIST",),
            business_lines=("HEALTH",),
        ),
        applicability_filters=(
            TaxonomyCondition(key="product_code", operator="EQ", values=("P-1",)),
            TaxonomyCondition(key="insured_age", operator="EQ", values=(35,)),
        ),
        as_of_date=date(2026, 7, 14),
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        rrf_pipeline="pa-source-local-rrf-v1",
        limit=10,
    )


def approved_metadata() -> ApprovedInsuranceRuleMetadataRevision:
    return ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id="metadata-1",
        applicability=InsuranceRuleApplicability(
            taxonomy_id="insurance-applicability",
            taxonomy_revision_id="taxonomy-v1",
            conditions=(
                TaxonomyCondition(key="product_code", operator="EQ", values=("P-1",)),
                TaxonomyCondition(key="insured_age", operator="EQ", values=(35,)),
            ),
        ),
        effective_from=date(2026, 1, 1),
        effective_to=date(2026, 12, 31),
        authority="insurance-operations",
        precedence=InsuranceRulePrecedence(
            policy_revision_id="precedence-v1",
            authority_tier="product-rule",
            order=10,
        ),
    )


def projection_document(*, publication_seq_to: int | None = None) -> ProjectionDocument:
    visibility = ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="RESTRICTED",
        revision_id="visibility-1",
        institutions=ScopeDimension(mode="ALLOWLIST", values=("INST-1",)),
        regions=ScopeDimension(mode="ALL"),
        channels=ScopeDimension(mode="ALLOWLIST", values=("AGENCY",)),
        roles=ScopeDimension(mode="ALLOWLIST", values=("SPECIALIST",)),
        business_lines=ScopeDimension(mode="ALLOWLIST", values=("HEALTH",)),
    )
    citation = "knowledge://source/source-1/document/document-1/revision/revision-1#page=1"
    rule = InsuranceRuleUnitRevision(
        rule_unit_revision_id="rule-unit-1",
        logical_rule_key="hospital-benefit",
        unit_kind="clause",
        document_id="document-1",
        revision_id="revision-1",
        structured_build_id="build-1",
        content="住院治疗符合合同条件时给付保险金。",
        citation_uri=citation,
        metadata_revision_id="metadata-1",
        visibility_scope=visibility,
        content_sha256=SHA_B,
        authority_sha256=SHA_C,
        lineage=InsuranceRuleUnitLineage(
            source_id="source-1",
            original_sha256="d" * 64,
            heading_path=("保险责任", "住院保险金"),
            definitions=("住院：入住医院正式病房接受治疗。",),
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                ),
            ),
            block_ids=("block-1",),
        ),
    )
    entry = RuleUnitManifestEntry(
        rule_unit_revision_id=rule.rule_unit_revision_id,
        document_id=rule.document_id,
        revision_id=rule.revision_id,
        structured_build_id=rule.structured_build_id,
        metadata_revision_id=rule.metadata_revision_id,
        visibility_revision_id=visibility.revision_id,
        content_sha256=rule.content_sha256,
        authority_sha256=rule.authority_sha256,
        citation_uri=citation,
        publication_seq_from=1,
        publication_seq_to=publication_seq_to,
    )
    return ProjectionDocument(
        projection_id="projection-1",
        rule_unit=rule,
        manifest_entry=entry,
        approved_metadata=approved_metadata(),
        projection_revision="rule-unit-search.v1",
        embedding=(0.1, 0.2),
    )


class RecordingTransport:
    def __init__(self, *, search_hits: list[dict[str, object]] | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self.search_hits = search_hits or []

    def request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, object] | None = None,
        content: bytes | None = None,
        content_type: str = "application/json",
        query_params: dict[str, str] | None = None,
    ) -> OpenSearchTransportResponse:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json_body": json_body,
                "content": content,
                "content_type": content_type,
                "query_params": query_params,
            }
        )
        index_name = physical_index_name("source-1", "generation-1")
        if method == "GET" and path == f"/{index_name}":
            return OpenSearchTransportResponse(
                status_code=200,
                body={
                    index_name: {
                        "settings": {"index": {"uuid": "uuid-1"}},
                        "mappings": {
                            "_meta": {
                                "source_id": "source-1",
                                "generation_id": "generation-1",
                                "embedding_dimension": 2,
                                "mapping_sha256": SHA_A,
                                "analyzer_sha256": SHA_B,
                            }
                        },
                    }
                },
            )
        if method == "POST" and path == f"/{index_name}/_bulk":
            return OpenSearchTransportResponse(
                status_code=200,
                body={"errors": False, "items": [{"update": {"status": 200}}]},
            )
        if method == "POST" and path == f"/{index_name}/_refresh":
            return OpenSearchTransportResponse(
                status_code=200,
                body={"_shards": {"total": 1, "successful": 1, "failed": 0}},
            )
        if method == "POST" and path == f"/{index_name}/_search":
            return OpenSearchTransportResponse(
                status_code=200,
                body={"hits": {"hits": self.search_hits}},
            )
        raise AssertionError(f"unexpected transport call: {method} {path}")


def test_physical_index_name_is_safe_deterministic_and_collision_resistant() -> None:
    first = physical_index_name("Source / 华东", "Generation:V1")

    assert first == physical_index_name("Source / 华东", "Generation:V1")
    assert first.startswith("pa-knowledge-source-generation-v1-")
    assert first != physical_index_name("source---华东", "Generation:V1")
    assert first.isascii()
    assert first == first.lower()
    assert len(first.encode("utf-8")) <= 255


@pytest.mark.parametrize(
    "endpoint",
    (
        "http://opensearch.internal:9200",
        "https://user:secret@opensearch.internal:9200",
        "https://opensearch.internal:9200/prefix",
        "https://opensearch.internal:9200?token=secret",
    ),
)
def test_http_transport_rejects_unguarded_or_credential_bearing_endpoints(
    endpoint: str,
) -> None:
    with pytest.raises(ValueError):
        HttpxOpenSearchTransport(
            endpoint=endpoint,
            allowed_hosts=("opensearch.internal",),
        )


def test_http_transport_allows_only_explicit_insecure_loopback_for_integration() -> None:
    transport = HttpxOpenSearchTransport(
        endpoint="http://127.0.0.1:9200",
        allowed_hosts=("127.0.0.1",),
        allow_insecure_loopback=True,
    )

    transport.close()


def test_create_index_pins_generation_metadata_and_source_local_rrf_pipeline() -> None:
    class CreationTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            method = kwargs["method"]
            if method == "PUT":
                self.calls.append(kwargs)
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={"acknowledged": True},
                )
            return super().request(**kwargs)

    transport = CreationTransport()
    adapter = OpenSearchHybridIndex(transport=transport)

    created = adapter.create_index(
        index_identity().generation,
        rrf_pipeline="pa-source-local-rrf-v1",
        rrf_rank_constant=60,
    )

    assert created == index_identity()
    pipeline_call = next(
        call for call in transport.calls if call["path"] == "/_search/pipeline/pa-source-local-rrf-v1"
    )
    assert pipeline_call["json_body"]["phase_results_processors"] == [
        {
            "score-ranker-processor": {
                "combination": {
                    "technique": "rrf",
                    "rank_constant": 60,
                }
            }
        }
    ]
    index_call = next(
        call for call in transport.calls if call["path"] == f"/{physical_index_name('source-1', 'generation-1')}"
    )
    assert index_call["json_body"]["mappings"]["_meta"] == {
        "source_id": "source-1",
        "generation_id": "generation-1",
        "embedding_dimension": 2,
        "mapping_sha256": SHA_A,
        "analyzer_sha256": SHA_B,
    }


def test_mapping_uses_typed_authority_acl_applicability_and_one_vector() -> None:
    mapping = rule_unit_index_mapping(dimension=1024)
    properties = mapping["properties"]

    assert properties["rule_unit_revision_id"]["type"] == "keyword"
    assert properties["authority_manifest_digest"]["type"] == "keyword"
    assert properties["allowed_institutions"]["type"] == "keyword"
    assert properties["publication_seq_from"]["type"] == "long"
    assert properties["effective_from"]["type"] == "date"
    assert properties["applicability_numbers"]["type"] == "nested"
    assert properties["lexical_text"]["type"] == "text"
    assert properties["dense_vector"]["type"] == "knn_vector"
    assert properties["dense_vector"]["dimension"] == 1024
    assert [field for field in properties.values() if field["type"] == "knn_vector"] == [
        properties["dense_vector"]
    ]


def test_hybrid_query_applies_identical_filters_inside_both_lanes() -> None:
    body = build_hybrid_query(search_request())
    lanes = body["query"]["hybrid"]["queries"]
    lexical_filter = lanes[0]["bool"]["filter"]
    vector_filter = lanes[1]["knn"]["dense_vector"]["filter"]["bool"]["filter"]

    assert lexical_filter == vector_filter
    assert body["query"]["hybrid"]["pagination_depth"] == 100
    assert {"term": {"source_id": "source-1"}} in lexical_filter
    assert {"term": {"index_generation_id": "generation-1"}} in lexical_filter
    assert {"term": {"authority_manifest_digest": SHA_A}} in lexical_filter
    assert {"range": {"publication_seq_from": {"lte": 7}}} in lexical_filter
    assert {
        "bool": {
            "should": [
                {"range": {"publication_seq_to": {"gte": 7}}},
                {"bool": {"must_not": [{"exists": {"field": "publication_seq_to"}}]}},
            ],
            "minimum_should_match": 1,
        }
    } in lexical_filter
    assert {
        "bool": {
            "should": [
                {"range": {"effective_from": {"lte": "2026-07-14"}}},
                {"bool": {"must_not": [{"exists": {"field": "effective_from"}}]}},
            ],
            "minimum_should_match": 1,
        }
    } in lexical_filter
    assert {
        "bool": {
            "should": [
                {"range": {"effective_to": {"gte": "2026-07-14"}}},
                {"bool": {"must_not": [{"exists": {"field": "effective_to"}}]}},
            ],
            "minimum_should_match": 1,
        }
    } in lexical_filter
    assert "post_filter" not in body
    assert body["search_pipeline"] == "pa-source-local-rrf-v1"


def test_projection_contains_only_approved_query_safe_fields() -> None:
    projected = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        manifest_root_sha256=SHA_A,
        publication_attempt_id="attempt-1",
    )

    assert projected["source_id"] == "source-1"
    assert projected["index_generation_id"] == "generation-1"
    assert projected["authority_manifest_digest"] == SHA_A
    assert projected["metadata_revision_digest"]
    assert projected["visibility_revision_digest"]
    assert projected["publication_seq_from"] == 1
    assert "publication_seq_to" not in projected
    assert projected["visibility"] == "RESTRICTED"
    assert projected["institution_mode"] == "ALLOWLIST"
    assert projected["allowed_institutions"] == ["INST-1"]
    assert projected["effective_from"] == "2026-01-01"
    assert projected["applicability_numbers"] == [
        {"key": "insured_age", "operator": "EQ", "value": 35}
    ]
    assert "住院保险金" in projected["lexical_text"]
    assert projected["dense_vector"] == [0.1, 0.2]
    assert "vendor_payload" not in projected
    assert "metadata_draft" not in projected


def test_bulk_upsert_is_attempt_scoped_and_allows_only_idempotence_or_interval_close() -> None:
    transport = RecordingTransport()
    adapter = OpenSearchHybridIndex(transport=transport)
    request = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_A,
        documents=(projection_document(publication_seq_to=8),),
    )

    result = adapter.bulk_upsert(request)

    bulk_call = next(call for call in transport.calls if call["path"].endswith("/_bulk"))
    lines = bulk_call["content"].decode().splitlines()
    action = json.loads(lines[0])
    update = json.loads(lines[1])
    assert action == {"update": {"_id": "projection-1"}}
    assert update["scripted_upsert"] is True
    assert update["upsert"] == {}
    assert "immutable_projection_sha256" in update["script"]["source"]
    assert "publication_seq_to" in update["script"]["source"]
    assert update["script"]["params"]["doc"]["publication_attempt_id"] == "attempt-1"
    assert result.accepted_count == 1
    assert result.request is request
    assert result.refresh_checkpoint.startswith("refresh-sha256:")


def projected_search_hit(**updates: object) -> dict[str, object]:
    source = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        manifest_root_sha256=SHA_A,
        publication_attempt_id="attempt-1",
    )
    source.update(updates)
    return {
        "_index": physical_index_name("source-1", "generation-1"),
        "_id": source["projection_id"],
        "_score": 1.25,
        "_source": source,
    }


def test_search_normalizes_only_bounded_authorized_manifest_matching_hits() -> None:
    transport = RecordingTransport(search_hits=[projected_search_hit()])
    adapter = OpenSearchHybridIndex(transport=transport)

    hits = adapter.search(search_request())

    assert len(hits) == 1
    assert hits[0].rank == 1
    assert hits[0].source_id == "source-1"
    assert hits[0].index_generation_id == "generation-1"
    assert hits[0].index_uuid == "uuid-1"
    assert hits[0].rule_unit_revision_id == "rule-unit-1"
    assert hits[0].citation_uri.endswith("#page=1")
    assert hits[0].content == "住院治疗符合合同条件时给付保险金。"
    search_call = next(call for call in transport.calls if call["path"].endswith("/_search"))
    expected_body = build_hybrid_query(search_request())
    expected_body.pop("search_pipeline")
    assert search_call["json_body"] == expected_body
    assert search_call["query_params"] == {
        "search_pipeline": "pa-source-local-rrf-v1"
    }


@pytest.mark.parametrize(
    "updates",
    (
        {"source_id": "source-2"},
        {"index_generation_id": "generation-2"},
        {"authority_manifest_digest": SHA_B},
        {"metadata_revision_digest": None},
        {"publication_seq_from": 8},
        {"publication_seq_to": 6},
        {"effective_from": "2027-01-01"},
        {"applicability_tokens": []},
        {"allowed_institutions": ["INST-2"]},
        {"citation_uri": "https://example.invalid/raw"},
        {
            "citation_uri": (
                "knowledge://source/source-2/document/document-1/"
                "revision/revision-1#page=1"
            )
        },
        {"projection_sha256": None},
        {"content": "x" * 50_001},
    ),
)
def test_search_rejects_backend_hits_that_bypass_governed_filters(
    updates: dict[str, Any],
) -> None:
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(search_hits=[projected_search_hit(**updates)])
    )

    with pytest.raises(OpenSearchProjectionError):
        adapter.search(search_request())


def test_search_rejects_hit_from_another_physical_index() -> None:
    hit = projected_search_hit()
    hit["_index"] = "pa-knowledge-other-generation"

    with pytest.raises(OpenSearchProjectionError, match="physical index"):
        OpenSearchHybridIndex(
            transport=RecordingTransport(search_hits=[hit])
        ).search(search_request())


def test_search_rejects_wrong_exact_index_uuid_before_content_query() -> None:
    class WrongIdentityTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["method"] == "GET":
                body = dict(response.body)
                index = physical_index_name("source-1", "generation-1")
                body[index]["settings"]["index"]["uuid"] = "wrong-uuid"  # type: ignore[index]
                return OpenSearchTransportResponse(status_code=200, body=body)
            return response

    transport = WrongIdentityTransport(search_hits=[projected_search_hit()])

    with pytest.raises(OpenSearchProjectionError, match="index UUID"):
        OpenSearchHybridIndex(transport=transport).search(search_request())
    assert not any(call["path"].endswith("/_search") for call in transport.calls)


def test_publication_upper_bound_equal_to_requested_sequence_remains_visible() -> None:
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(
            search_hits=[projected_search_hit(publication_seq_to=7)]
        )
    )

    assert len(adapter.search(search_request())) == 1
