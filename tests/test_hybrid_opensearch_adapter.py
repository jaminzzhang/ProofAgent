from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Any
from urllib.parse import quote

import pytest

from proof_agent.capabilities.knowledge.hybrid import opensearch as opensearch_module
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    build_hybrid_query,
    HttpxOpenSearchTransport,
    OpenSearchHybridIndex,
    OpenSearchProjectionError,
    OpenSearchSecretMaterial,
    OpenSearchTransportResponse,
    physical_index_name,
    project_rule_unit_document,
    rrf_pipeline_body,
    rrf_pipeline_name,
    rule_unit_analysis_settings,
    rule_unit_analyzer_sha256,
    rule_unit_index_mapping,
    rule_unit_mapping_sha256,
)
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchRequest,
    ProjectionBulkRequest,
    ProjectionDocument,
    SearchIndexIdentity,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
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


def manifest_entry_core_sha256(entry: RuleUnitManifestEntry) -> str:
    payload = entry.model_dump(mode="json")
    payload.pop("publication_seq_to", None)
    return stable_digest(payload)


def index_identity(*, index_uuid: str = "uuid-1") -> SearchIndexIdentity:
    return SearchIndexIdentity(
        generation=KnowledgeIndexGeneration(
            generation_id="generation-1",
            source_id="source-1",
            canonical_schema_version="structured-knowledge.v1",
            search_projection_version="rule-unit-search.v1",
            mapping_sha256=rule_unit_mapping_sha256(dimension=2),
            analyzer_sha256=rule_unit_analyzer_sha256(),
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
        rrf_pipeline=rrf_pipeline_name(rank_constant=60),
        rrf_rank_constant=60,
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


def projection_document(
    *,
    publication_seq_to: int | None = None,
    metadata: ApprovedInsuranceRuleMetadataRevision | None = None,
) -> ProjectionDocument:
    metadata = metadata or approved_metadata()
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
        content_sha256=hashlib.sha256("住院治疗符合合同条件时给付保险金。".encode()).hexdigest(),
        authority_sha256=stable_digest(
            {
                "approved_metadata": metadata.model_dump(mode="json"),
                "approved_visibility": visibility.model_dump(mode="json"),
            }
        ),
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
        approved_metadata=metadata,
        projection_revision="rule-unit-search.v1",
        embedding=(0.1, 0.2),
    )


def test_unicode_citation_binding_is_shared_by_projection_and_hit_validation() -> None:
    base = projection_document()
    source_id = "来源一"
    document_id = "文档一"
    revision_id = "修订一"
    citation = (
        f"knowledge://source/{quote(source_id, safe='')}/document/"
        f"{quote(document_id, safe='')}/revision/"
        f"{quote(revision_id, safe='')}#page=1"
    )
    rule = base.rule_unit.model_copy(
        update={
            "document_id": document_id,
            "revision_id": revision_id,
            "citation_uri": citation,
            "lineage": base.rule_unit.lineage.model_copy(update={"source_id": source_id}),
        }
    )
    entry = base.manifest_entry.model_copy(
        update={
            "document_id": document_id,
            "revision_id": revision_id,
            "citation_uri": citation,
        }
    )
    document = ProjectionDocument(
        projection_id=base.projection_id,
        rule_unit=rule,
        manifest_entry=entry,
        approved_metadata=base.approved_metadata,
        projection_revision=base.projection_revision,
        embedding=base.embedding,
    )
    base_identity = index_identity()
    identity = SearchIndexIdentity(
        generation=base_identity.generation.model_copy(update={"source_id": source_id}),
        index_uuid=base_identity.index_uuid,
    )

    projected = project_rule_unit_document(
        document,
        identity=identity,
        publication_attempt_id="attempt-1",
    )
    opensearch_module._validate_citation_binding(
        projected["citation_uri"],
        source_id=source_id,
        document_id=document_id,
        revision_id=revision_id,
    )

    with pytest.raises(OpenSearchProjectionError, match="citation"):
        opensearch_module._validate_citation_binding(
            citation,
            source_id=source_id,
            document_id="其他文档",
            revision_id=revision_id,
        )


def test_projection_locator_defaults_compatibly_and_rejects_forged_redirect() -> None:
    identity = index_identity()
    assert opensearch_module._identity_index_name(identity) == physical_index_name(
        identity.generation.source_id,
        identity.generation.generation_id,
    )
    forged = identity.model_copy(update={"projection_locator": "foreign-index"})
    with pytest.raises(OpenSearchProjectionError, match="locator"):
        opensearch_module._identity_index_name(forged)


class RecordingTransport:
    def __init__(
        self,
        *,
        search_hits: list[dict[str, object]] | None = None,
        pipelines_exist: bool = True,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self.search_hits = search_hits or []
        self.pipelines: set[str] = (
            {rrf_pipeline_name(rank_constant=60)} if pipelines_exist else set()
        )

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
        pipeline = rrf_pipeline_name(rank_constant=60)
        if method == "GET" and path == f"/_search/pipeline/{pipeline}":
            if pipeline not in self.pipelines:
                return OpenSearchTransportResponse(status_code=404, body={})
            return OpenSearchTransportResponse(
                status_code=200,
                body={pipeline: rrf_pipeline_body(rank_constant=60)},
            )
        if method == "PUT" and path == f"/_search/pipeline/{pipeline}":
            self.pipelines.add(pipeline)
            return OpenSearchTransportResponse(status_code=200, body={"acknowledged": True})
        if method == "PUT" and path == f"/{index_name}":
            return OpenSearchTransportResponse(status_code=200, body={"acknowledged": True})
        if method == "GET" and path == f"/{index_name}":
            mappings = rule_unit_index_mapping(dimension=2)
            mappings["_meta"] = {
                "source_id": "source-1",
                "generation_id": "generation-1",
                "embedding_dimension": 2,
                "mapping_sha256": rule_unit_mapping_sha256(dimension=2),
                "analyzer_sha256": rule_unit_analyzer_sha256(),
                "mapping_normalization_policy": ("opensearch-3.1-knn-empty-parameters.v1"),
            }
            return OpenSearchTransportResponse(
                status_code=200,
                body={
                    index_name: {
                        "settings": {
                            "index": {
                                "uuid": "uuid-1",
                                "number_of_replicas": "1",
                                "analysis": rule_unit_analysis_settings(),
                            }
                        },
                        "mappings": mappings,
                    }
                },
            )
        if method == "POST" and path == f"/{index_name}/_bulk":
            return OpenSearchTransportResponse(
                status_code=200,
                body={
                    "errors": False,
                    "items": [
                        {
                            "update": {
                                "status": 200,
                                "_id": "projection-1",
                                "_index": index_name,
                                "result": "updated",
                                "_seq_no": 7,
                                "_primary_term": 2,
                                "_version": 3,
                                "_shards": {
                                    "total": 1,
                                    "successful": 1,
                                    "failed": 0,
                                },
                            }
                        }
                    ],
                },
            )
        if method == "POST" and path == f"/{index_name}/_refresh":
            return OpenSearchTransportResponse(
                status_code=200,
                body={"_shards": {"total": 1, "successful": 1, "failed": 0}},
            )
        if method == "POST" and path == f"/{index_name}/_search":
            return OpenSearchTransportResponse(
                status_code=200,
                body={
                    "timed_out": False,
                    "_shards": {"total": 1, "successful": 1, "failed": 0},
                    "hits": {
                        "hits": [
                            {key: value for key, value in hit.items() if key != "_content_source"}
                            for hit in self.search_hits
                        ]
                    },
                },
            )
        if method == "POST" and path == f"/{index_name}/_mget":
            assert json_body is not None
            requested_docs = json_body["docs"]
            assert isinstance(requested_docs, list)
            assert all(
                set(requested_doc) == {"_id", "_source"}
                and requested_doc["_source"]
                == sorted(
                    {
                        "projection_id",
                        "content",
                        "content_sha256",
                        "immutable_projection_sha256",
                        "response_integrity_sha256",
                    }
                )
                for requested_doc in requested_docs
            )
            by_id = {hit["_id"]: hit for hit in self.search_hits}
            return OpenSearchTransportResponse(
                status_code=200,
                body={
                    "docs": [
                        {
                            "_index": index_name,
                            "_id": requested_doc["_id"],
                            "found": True,
                            "_source": by_id[requested_doc["_id"]]["_content_source"],
                        }
                        for requested_doc in requested_docs
                    ]
                },
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

    assert transport._max_response_bytes == 32 * 1024 * 1024  # type: ignore[attr-defined]
    transport.close()


def test_http_transport_requires_private_dns_pinning_for_production() -> None:
    with pytest.raises(ValueError, match="private DNS/CIDR"):
        HttpxOpenSearchTransport(
            endpoint="https://opensearch.internal:9200",
            allowed_hosts=("opensearch.internal",),
        )


def test_http_transport_resolves_auth_only_through_a_secret_handle() -> None:
    class RecordingSecretProvider:
        def __init__(self) -> None:
            self.handles: list[str] = []

        def resolve(self, secret_handle: str) -> OpenSearchSecretMaterial:
            self.handles.append(secret_handle)
            return OpenSearchSecretMaterial(headers={"X-OpenSearch-Auth": "opaque-test-value"})

    provider = RecordingSecretProvider()
    transport = HttpxOpenSearchTransport(
        endpoint="http://127.0.0.1:9200",
        allowed_hosts=("127.0.0.1",),
        allow_insecure_loopback=True,
        secret_handle="vault://opensearch/service-account",
        secret_provider=provider,
    )

    assert provider.handles == ["vault://opensearch/service-account"]
    transport.close()


def test_create_index_pins_generation_metadata_and_source_local_rrf_pipeline() -> None:
    transport = RecordingTransport(pipelines_exist=False)
    adapter = OpenSearchHybridIndex(transport=transport)

    created = adapter.create_index(
        index_identity().generation,
        rrf_pipeline=rrf_pipeline_name(rank_constant=60),
        rrf_rank_constant=60,
    )

    assert created == index_identity()
    pipeline_call = next(
        call
        for call in transport.calls
        if call["method"] == "PUT"
        and call["path"] == f"/_search/pipeline/{rrf_pipeline_name(rank_constant=60)}"
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
        call
        for call in transport.calls
        if call["path"] == f"/{physical_index_name('source-1', 'generation-1')}"
    )
    assert index_call["json_body"]["mappings"]["_meta"] == {
        "source_id": "source-1",
        "generation_id": "generation-1",
        "embedding_dimension": 2,
        "mapping_sha256": rule_unit_mapping_sha256(dimension=2),
        "analyzer_sha256": rule_unit_analyzer_sha256(),
        "mapping_normalization_policy": "opensearch-3.1-knn-empty-parameters.v1",
    }
    assert index_call["json_body"]["settings"]["index"]["analysis"] == rule_unit_analysis_settings()
    assert index_call["json_body"]["settings"]["index"]["number_of_replicas"] == 1
    assert (
        index_call["json_body"]["mappings"]["properties"]["lexical_text"]["analyzer"]
        == "proof_agent_cjk_v1"
    )


def test_mapping_uses_typed_authority_acl_applicability_and_one_vector() -> None:
    mapping = rule_unit_index_mapping(dimension=1024)
    properties = mapping["properties"]

    assert properties["rule_unit_revision_id"]["type"] == "keyword"
    assert properties["manifest_entry_core_sha256"]["type"] == "keyword"
    assert properties["allowed_institutions"]["type"] == "keyword"
    assert properties["publication_seq_from"]["type"] == "long"
    assert properties["effective_from"]["type"] == "date"
    assert properties["applicability_predicates"]["type"] == "nested"
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
    assert "manifest_root_sha256" not in json.dumps(lexical_filter)
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
    assert body["search_pipeline"] == rrf_pipeline_name(rank_constant=60)
    assert "dense_vector" not in body["_source"]
    assert "lexical_text" not in body["_source"]
    assert "content" not in body["_source"]
    assert "approved_metadata" not in body["_source"]
    assert "approved_visibility" not in body["_source"]
    serialized_filters = json.dumps(lexical_filter, sort_keys=True)
    assert all(operator in serialized_filters for operator in ("EQ", "IN", "NOT_EQ", "NOT_IN"))


def test_search_budget_contract_keeps_lexical_candidates_at_least_dense_candidates() -> None:
    with pytest.raises(ValueError, match="lexical_budget"):
        HybridSearchRequest.model_validate(
            {
                **search_request().model_dump(mode="python"),
                "lexical_budget": 99,
                "dense_budget": 100,
            }
        )


def test_projection_contains_only_approved_query_safe_fields() -> None:
    projected = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        publication_attempt_id="attempt-1",
    )

    assert projected["source_id"] == "source-1"
    assert projected["index_generation_id"] == "generation-1"
    assert projected["manifest_entry_core_sha256"] == manifest_entry_core_sha256(
        projection_document().manifest_entry
    )
    assert projected["metadata_revision_digest"]
    assert projected["visibility_revision_digest"]
    assert projected["publication_seq_from"] == 1
    assert "publication_seq_to" not in projected
    assert projected["visibility"] == "RESTRICTED"
    assert projected["institution_mode"] == "ALLOWLIST"
    assert projected["allowed_institutions"] == ["INST-1"]
    assert projected["effective_from"] == "2026-01-01"
    assert any(
        predicate["key"] == "insured_age" and predicate["integer_values"] == [35]
        for predicate in projected["applicability_predicates"]
    )
    assert "住院保险金" in projected["lexical_text"]
    assert projected["dense_vector"] == [0.1, 0.2]
    assert "approved_metadata" not in projected
    assert "approved_visibility" not in projected
    assert "vendor_payload" not in projected
    assert "metadata_draft" not in projected


def test_keyword_projection_validator_covers_every_mapped_keyword_field() -> None:
    mapping = rule_unit_index_mapping(dimension=2)
    properties = mapping["properties"]
    mapped_top_level_keywords = {
        field_name
        for field_name, field_mapping in properties.items()
        if field_mapping["type"] == "keyword"
    }
    mapped_predicate_keywords = {
        field_name
        for field_name, field_mapping in properties["applicability_predicates"][
            "properties"
        ].items()
        if field_mapping["type"] == "keyword"
    }

    assert set(opensearch_module._PROJECTED_KEYWORD_FIELDS) == mapped_top_level_keywords
    assert set(opensearch_module._APPLICABILITY_KEYWORD_FIELDS) == (mapped_predicate_keywords)

    projected = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        publication_attempt_id="attempt-1",
    )
    overlong = "x" * 513
    for field_name in mapped_top_level_keywords:
        mutated = dict(projected)
        original = mutated.get(field_name)
        mutated[field_name] = [overlong] if isinstance(original, list) else overlong
        with pytest.raises(ValueError, match=field_name):
            opensearch_module._validate_projected_keyword_fields(mutated)

    for field_name in mapped_predicate_keywords:
        mutated = dict(projected)
        predicates = [dict(item) for item in projected["applicability_predicates"]]
        original = predicates[0].get(field_name)
        predicates[0][field_name] = [overlong] if isinstance(original, list) else overlong
        mutated["applicability_predicates"] = predicates
        with pytest.raises(ValueError, match=field_name):
            opensearch_module._validate_projected_keyword_fields(mutated)


def test_keyword_projection_enforces_character_and_utf8_byte_boundaries() -> None:
    projected = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        publication_attempt_id="attempt-1",
    )

    for accepted in ("x" * 512, "保" * 170, "😀" * 128):
        assert len(accepted.encode("utf-8")) <= 512
        mutated = {**projected, "projection_id": accepted}
        opensearch_module._validate_projected_keyword_fields(mutated)

    for rejected in ("x" * 513, "保" * 171, "😀" * 129):
        mutated = {**projected, "projection_id": rejected}
        with pytest.raises(ValueError, match="projection_id"):
            opensearch_module._validate_projected_keyword_fields(mutated)


def test_projection_rejects_oversized_taxonomy_keyword_before_bulk() -> None:
    condition = TaxonomyCondition(key="product_code", operator="EQ", values=("P-1",)).model_copy(
        update={"key": "保" * 171}
    )
    document = projection_document(metadata=metadata_with_condition(condition))

    with pytest.raises(ValueError, match="applicability_predicates.key"):
        project_rule_unit_document(
            document,
            identity=index_identity(),
            publication_attempt_id="attempt-1",
        )


@pytest.mark.parametrize(
    ("field", "mutated"),
    (
        ("title", "forged title"),
        ("heading_path", ["forged heading"]),
        ("definitions", ["forged definition"]),
        ("table_context", "forged table context"),
        ("page_numbers", [2]),
        ("lineage_sha256", SHA_B),
        ("block_ids", ["forged-block"]),
        ("cell_coordinates", ["p1:r0:c0:rs1:cs1"]),
        ("table_id", "forged-table"),
        ("dense_vector", [0.2, 0.1]),
        ("embedding_sha256", SHA_B),
        ("lexical_text", "forged ranking text"),
        (
            "citation_uri",
            "knowledge://source/source-1/document/document-1/revision/revision-1#page=2",
        ),
    ),
)
def test_full_write_fence_digest_binds_every_omitted_projection_class(
    field: str,
    mutated: object,
) -> None:
    projected = project_rule_unit_document(
        projection_document(),
        identity=index_identity(),
        publication_attempt_id="attempt-1",
    )
    baseline = projected["immutable_projection_sha256"]
    projected[field] = mutated

    assert opensearch_module._immutable_projection_sha256(projected) != baseline


def test_bulk_upsert_is_attempt_scoped_and_allows_only_idempotence_or_interval_close() -> None:
    transport = RecordingTransport()
    adapter = OpenSearchHybridIndex(transport=transport)
    request = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_B,
        documents=(
            projection_document(
                publication_seq_to=8,
            ),
        ),
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
    assert "manifest entry core conflict" in update["script"]["source"]
    assert "publication_seq_to" in update["script"]["source"]
    assert update["script"]["params"]["doc"]["publication_attempt_id"] == "attempt-1"
    assert "authority_manifest_digests" not in update["script"]["params"]["doc"]
    assert update["script"]["params"]["doc"]["manifest_entry_core_sha256"]
    assert result.accepted_count == 1
    assert result.request is request
    assert result.refresh_checkpoint.startswith("refresh-sha256:")
    assert (
        sum(
            call["method"] == "GET"
            and call["path"] == f"/{physical_index_name('source-1', 'generation-1')}"
            for call in transport.calls
        )
        == 2
    )


def test_bulk_upsert_rejects_backend_item_identity_mismatch() -> None:
    class WrongBulkIdentityTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].endswith("/_bulk"):
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={
                        "errors": False,
                        "items": [
                            {
                                "update": {
                                    "status": 200,
                                    "_id": "wrong-projection",
                                    "_index": physical_index_name("source-1", "generation-1"),
                                }
                            }
                        ],
                    },
                )
            return response

    request = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_A,
        documents=(projection_document(),),
    )
    with pytest.raises(OpenSearchProjectionError, match="bulk item identity"):
        OpenSearchHybridIndex(transport=WrongBulkIdentityTransport()).bulk_upsert(request)


def test_refresh_checkpoint_binds_exact_projection_state_and_is_idempotent() -> None:
    base = projection_document()
    citation = "knowledge://source/source-1/document/document-2/revision/revision-2#page=1"
    second_rule = base.rule_unit.model_copy(
        update={
            "rule_unit_revision_id": "rule-unit-2",
            "logical_rule_key": "hospital-benefit-2",
            "document_id": "document-2",
            "revision_id": "revision-2",
            "structured_build_id": "build-2",
            "citation_uri": citation,
        }
    )
    second_entry = base.manifest_entry.model_copy(
        update={
            "rule_unit_revision_id": "rule-unit-2",
            "document_id": "document-2",
            "revision_id": "revision-2",
            "structured_build_id": "build-2",
            "citation_uri": citation,
        }
    )
    second = ProjectionDocument(
        projection_id="projection-2",
        rule_unit=second_rule,
        manifest_entry=second_entry,
        approved_metadata=base.approved_metadata,
        projection_revision=base.projection_revision,
        embedding=base.embedding,
    )

    class StatefulBulkTransport(RecordingTransport):
        def __init__(self) -> None:
            super().__init__()
            self.states: dict[str, tuple[str, int, int, int]] = {}

        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            if kwargs["path"].endswith("/_bulk"):
                lines = kwargs["content"].decode().splitlines()
                items: list[dict[str, object]] = []
                index = physical_index_name("source-1", "generation-1")
                for offset in range(0, len(lines), 2):
                    projection_id = json.loads(lines[offset])["update"]["_id"]
                    document = json.loads(lines[offset + 1])["script"]["params"]["doc"]
                    projection_sha256 = document["projection_sha256"]
                    previous = self.states.get(projection_id)
                    if previous is None:
                        sequence = 7 if projection_id == "projection-1" else 8
                        state = (projection_sha256, sequence, 2, 1)
                        result, status, shards = "created", 201, (1, 1)
                    elif previous[0] == projection_sha256:
                        state = previous
                        result, status, shards = "noop", 200, (0, 0)
                    else:
                        state = (
                            projection_sha256,
                            previous[1] + 1,
                            previous[2],
                            previous[3] + 1,
                        )
                        result, status, shards = "updated", 200, (1, 1)
                    self.states[projection_id] = state
                    items.append(
                        {
                            "update": {
                                "status": status,
                                "_id": projection_id,
                                "_index": index,
                                "result": result,
                                "_seq_no": state[1],
                                "_primary_term": state[2],
                                "_version": state[3],
                                "_shards": {
                                    "total": shards[0],
                                    "successful": shards[1],
                                    "failed": 0,
                                },
                            }
                        }
                    )
                self.calls.append(kwargs)
                return OpenSearchTransportResponse(
                    status_code=200, body={"errors": False, "items": items}
                )
            return super().request(**kwargs)

    transport = StatefulBulkTransport()
    adapter = OpenSearchHybridIndex(transport=transport)
    baseline = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_A,
        documents=(base, second),
    )
    identical_retry_reordered = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-2",
        manifest_root_sha256=SHA_A,
        documents=(second, base),
    )
    closed = baseline.model_copy(
        update={
            "publication_attempt_id": "attempt-3",
            "documents": (projection_document(publication_seq_to=7), second),
        }
    )

    first = adapter.bulk_upsert(baseline)
    retry = adapter.bulk_upsert(identical_retry_reordered)
    changed = adapter.bulk_upsert(closed)

    assert first.refresh_checkpoint == retry.refresh_checkpoint
    assert first.refresh_checkpoint != changed.refresh_checkpoint


def test_bulk_upsert_rejects_item_shard_failure() -> None:
    class FailedBulkShardTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].endswith("/_bulk"):
                index = physical_index_name("source-1", "generation-1")
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={
                        "errors": False,
                        "items": [
                            {
                                "update": {
                                    "status": 200,
                                    "_id": "projection-1",
                                    "_index": index,
                                    "result": "updated",
                                    "_seq_no": 7,
                                    "_primary_term": 2,
                                    "_version": 3,
                                    "_shards": {
                                        "total": 2,
                                        "successful": 1,
                                        "failed": 1,
                                    },
                                }
                            }
                        ],
                    },
                )
            return response

    request = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_A,
        documents=(projection_document(),),
    )
    with pytest.raises(OpenSearchProjectionError, match="bulk item shards"):
        OpenSearchHybridIndex(transport=FailedBulkShardTransport()).bulk_upsert(request)


def projected_search_hit(
    *,
    document: ProjectionDocument | None = None,
    content_updates: dict[str, object] | None = None,
    **updates: object,
) -> dict[str, object]:
    projected = project_rule_unit_document(
        document or projection_document(),
        identity=index_identity(),
        publication_attempt_id="attempt-1",
    )
    returned_fields = set(build_hybrid_query(search_request())["_source"])
    source = {key: value for key, value in projected.items() if key in returned_fields}
    content_source = {
        key: value
        for key, value in projected.items()
        if key
        in {
            "projection_id",
            "content",
            "content_sha256",
            "immutable_projection_sha256",
            "response_integrity_sha256",
        }
    }
    content_source.update(content_updates or {})
    source.update(updates)
    return {
        "_index": physical_index_name("source-1", "generation-1"),
        "_id": source["projection_id"],
        "_score": 1.25,
        "_source": source,
        "_content_source": content_source,
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
    assert hits[0].manifest_entry_core_sha256 == manifest_entry_core_sha256(
        projection_document().manifest_entry
    )
    assert "manifest_root_sha256" not in hits[0].model_dump()
    assert hits[0].citation_uri.endswith("#page=1")
    assert hits[0].content == "住院治疗符合合同条件时给付保险金。"
    search_call = next(call for call in transport.calls if call["path"].endswith("/_search"))
    expected_body = build_hybrid_query(search_request())
    expected_body.pop("search_pipeline")
    assert search_call["json_body"] == expected_body
    assert search_call["query_params"] == {"search_pipeline": rrf_pipeline_name(rank_constant=60)}
    assert (
        sum(
            call["method"] == "GET"
            and call["path"] == f"/{physical_index_name('source-1', 'generation-1')}"
            for call in transport.calls
        )
        == 3
    )
    content_call = next(call for call in transport.calls if call["path"].endswith("/_mget"))
    assert content_call["json_body"] == {
        "docs": [
            {
                "_id": "projection-1",
                "_source": sorted(
                    {
                        "projection_id",
                        "content",
                        "content_sha256",
                        "immutable_projection_sha256",
                        "response_integrity_sha256",
                    }
                ),
            }
        ]
    }


@pytest.mark.parametrize(
    "updates",
    (
        {"source_id": "source-2"},
        {"index_generation_id": "generation-2"},
        {"manifest_entry_core_sha256": SHA_B},
        {"metadata_revision_digest": None},
        {"taxonomy_id": "forged-taxonomy"},
        {"taxonomy_revision_id": "forged-taxonomy-revision"},
        {"precedence_order": 999},
        {"authority": "forged-authority"},
        {"supersedes_rule_unit_revision_ids": ["forged-rule"]},
        {"projection_revision": "forged-projection.v1"},
        {"publication_seq_from": 8},
        {"publication_seq_to": 6},
        {"effective_from": "2027-01-01"},
        {"applicability_predicates": None},
        {"allowed_institutions": ["INST-2"]},
        {"citation_uri": "https://example.invalid/raw"},
        {
            "citation_uri": (
                "knowledge://source/source-2/document/document-1/revision/revision-1#page=1"
            )
        },
        {"projection_sha256": None},
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
        OpenSearchHybridIndex(transport=RecordingTransport(search_hits=[hit])).search(
            search_request()
        )


def test_unauthorized_candidate_never_triggers_content_fetch() -> None:
    transport = RecordingTransport(
        search_hits=[projected_search_hit(allowed_institutions=["INST-2"])]
    )
    with pytest.raises(OpenSearchProjectionError):
        OpenSearchHybridIndex(transport=transport).search(search_request())
    assert not any(call["path"].endswith("/_mget") for call in transport.calls)


def test_search_rejects_any_failed_backend_shard() -> None:
    class FailedShardTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].endswith("/_search"):
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={
                        "timed_out": False,
                        "_shards": {"total": 2, "successful": 1, "failed": 1},
                        "hits": {"hits": []},
                    },
                )
            return response

    with pytest.raises(OpenSearchProjectionError, match="search shards"):
        OpenSearchHybridIndex(transport=FailedShardTransport()).search(search_request())


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


def test_search_reverifies_index_uuid_after_content_stage() -> None:
    class PostContentIdentityDriftTransport(RecordingTransport):
        def __init__(self) -> None:
            super().__init__(search_hits=[projected_search_hit()])
            self.identity_reads = 0

        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["method"] == "GET" and kwargs["path"].startswith("/pa-knowledge-"):
                self.identity_reads += 1
                if self.identity_reads == 3:
                    body = dict(response.body)
                    index = physical_index_name("source-1", "generation-1")
                    body[index]["settings"]["index"]["uuid"] = "drifted-uuid"  # type: ignore[index]
                    return OpenSearchTransportResponse(status_code=200, body=body)
            return response

    with pytest.raises(OpenSearchProjectionError, match="index UUID"):
        OpenSearchHybridIndex(transport=PostContentIdentityDriftTransport()).search(
            search_request()
        )


def test_publication_upper_bound_equal_to_requested_sequence_remains_visible() -> None:
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(
            search_hits=[projected_search_hit(document=projection_document(publication_seq_to=7))]
        )
    )

    assert len(adapter.search(search_request())) == 1


def test_new_corpus_root_does_not_change_unchanged_rule_unit_projection() -> None:
    document = projection_document()
    first = ProjectionBulkRequest(
        identity=index_identity(),
        publication_attempt_id="attempt-1",
        manifest_root_sha256=SHA_A,
        documents=(document,),
    )
    second = first.model_copy(
        update={"publication_attempt_id": "attempt-2", "manifest_root_sha256": SHA_B}
    )
    first_transport = RecordingTransport()
    second_transport = RecordingTransport()
    first_result = OpenSearchHybridIndex(transport=first_transport).bulk_upsert(first)
    second_result = OpenSearchHybridIndex(transport=second_transport).bulk_upsert(second)
    first_doc = json.loads(
        next(call for call in first_transport.calls if call["path"].endswith("/_bulk"))["content"]
        .decode()
        .splitlines()[1]
    )["script"]["params"]["doc"]
    second_doc = json.loads(
        next(call for call in second_transport.calls if call["path"].endswith("/_bulk"))["content"]
        .decode()
        .splitlines()[1]
    )["script"]["params"]["doc"]
    assert first_doc["projection_sha256"] == second_doc["projection_sha256"]
    assert first_doc["manifest_entry_core_sha256"] == second_doc["manifest_entry_core_sha256"]
    assert "manifest_root_sha256" not in first_doc | second_doc
    assert first_result.refresh_checkpoint != second_result.refresh_checkpoint


def test_historical_sequence_candidate_is_root_agnostic_for_later_authority_gate() -> None:
    open_document = projection_document()
    document = projection_document(publication_seq_to=7)
    assert manifest_entry_core_sha256(open_document.manifest_entry) == (
        manifest_entry_core_sha256(document.manifest_entry)
    )
    open_projection = project_rule_unit_document(
        open_document,
        identity=index_identity(),
        publication_attempt_id="attempt-open",
    )
    closed_projection = project_rule_unit_document(
        document,
        identity=index_identity(),
        publication_attempt_id="attempt-close",
    )
    assert (
        open_projection["immutable_projection_sha256"]
        == closed_projection["immutable_projection_sha256"]
    )
    assert open_projection["projection_sha256"] != closed_projection["projection_sha256"]
    assert (
        open_projection["response_integrity_sha256"]
        != closed_projection["response_integrity_sha256"]
    )
    hit = projected_search_hit(document=document)
    transport = RecordingTransport(search_hits=[hit])
    adapter = OpenSearchHybridIndex(transport=transport)

    old_root_hits = adapter.search(
        search_request().model_copy(
            update={"source_publication_seq": 1, "manifest_root_sha256": SHA_A}
        )
    )
    assert old_root_hits[0].manifest_entry_core_sha256 == manifest_entry_core_sha256(
        open_document.manifest_entry
    )
    assert adapter.search(
        search_request().model_copy(
            update={"source_publication_seq": 7, "manifest_root_sha256": SHA_B}
        )
    )


def test_invalid_hit_beyond_return_limit_rejects_the_entire_candidate_window() -> None:
    bad = projected_search_hit(source_id="source-2")
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(search_hits=[projected_search_hit(), bad])
    )

    with pytest.raises(OpenSearchProjectionError, match="Source generation"):
        adapter.search(search_request().model_copy(update={"limit": 1}))


def test_invalid_score_beyond_return_limit_rejects_the_entire_candidate_window() -> None:
    bad = projected_search_hit()
    bad["_score"] = float("nan")
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(search_hits=[projected_search_hit(), bad])
    )

    with pytest.raises(OpenSearchProjectionError, match="fused score"):
        adapter.search(search_request().model_copy(update={"limit": 1}))


def test_search_rejects_timed_out_response_even_with_hits() -> None:
    class TimedOutTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].endswith("/_search"):
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={
                        **response.body,
                        "timed_out": True,
                    },
                )
            return response

    with pytest.raises(OpenSearchProjectionError, match="timed out"):
        OpenSearchHybridIndex(transport=TimedOutTransport()).search(search_request())


def test_search_rejects_per_hit_and_aggregate_source_envelope_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = projected_search_hit()
    oversized["_source"]["authority"] = "x" * (  # type: ignore[index]
        opensearch_module.MAX_CANDIDATE_SOURCE_BYTES + 1
    )
    with pytest.raises(OpenSearchProjectionError, match="bounded envelope"):
        OpenSearchHybridIndex(transport=RecordingTransport(search_hits=[oversized])).search(
            search_request()
        )

    monkeypatch.setattr(opensearch_module, "MAX_CANDIDATE_SOURCES_BYTES", 1)
    with pytest.raises(OpenSearchProjectionError, match="bounded envelope"):
        OpenSearchHybridIndex(
            transport=RecordingTransport(search_hits=[projected_search_hit()])
        ).search(search_request())


def test_content_fetch_rejects_oversize_and_digest_or_state_mismatch() -> None:
    for updates in (
        {"content": "x" * 50_001},
        {"content": "forged content"},
        {"immutable_projection_sha256": SHA_B},
        {"response_integrity_sha256": SHA_B},
    ):
        with pytest.raises(OpenSearchProjectionError):
            OpenSearchHybridIndex(
                transport=RecordingTransport(
                    search_hits=[projected_search_hit(content_updates=updates)]
                )
            ).search(search_request())


@pytest.mark.parametrize("failure", ("count", "id", "index", "found", "source"))
def test_content_fetch_rejects_incomplete_or_misbound_documents(failure: str) -> None:
    class InvalidMgetTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if not kwargs["path"].endswith("/_mget"):
                return response
            body = {"docs": [dict(item) for item in response.body["docs"]]}  # type: ignore[index]
            if failure == "count":
                body["docs"] = []
            elif failure == "id":
                body["docs"][0]["_id"] = "wrong-projection"
            elif failure == "index":
                body["docs"][0]["_index"] = "wrong-index"
            elif failure == "found":
                body["docs"][0]["found"] = False
            else:
                body["docs"][0]["_source"] = {"content": "incomplete"}
            return OpenSearchTransportResponse(status_code=200, body=body)

    with pytest.raises(OpenSearchProjectionError, match="content fetch"):
        OpenSearchHybridIndex(
            transport=InvalidMgetTransport(search_hits=[projected_search_hit()])
        ).search(search_request())


def metadata_with_condition(
    condition: TaxonomyCondition | None,
) -> ApprovedInsuranceRuleMetadataRevision:
    baseline = approved_metadata()
    return baseline.model_copy(
        update={
            "applicability": baseline.applicability.model_copy(
                update={"conditions": (() if condition is None else (condition,))}
            )
        }
    )


@pytest.mark.parametrize(
    ("condition", "allowed"),
    (
        (TaxonomyCondition(key="product_code", operator="IN", values=("P-1", "P-2")), True),
        (TaxonomyCondition(key="product_code", operator="IN", values=("P-2",)), False),
        (TaxonomyCondition(key="product_code", operator="NOT_EQ", values=("P-2",)), True),
        (TaxonomyCondition(key="product_code", operator="NOT_EQ", values=("P-1",)), False),
        (TaxonomyCondition(key="product_code", operator="NOT_IN", values=("P-2",)), True),
        (TaxonomyCondition(key="product_code", operator="NOT_IN", values=("P-1",)), False),
        (None, True),
    ),
)
def test_applicability_facts_are_evaluated_against_rule_predicates(
    condition: TaxonomyCondition | None,
    allowed: bool,
) -> None:
    document = projection_document(metadata=metadata_with_condition(condition))
    adapter = OpenSearchHybridIndex(
        transport=RecordingTransport(search_hits=[projected_search_hit(document=document)])
    )
    request = search_request().model_copy(
        update={
            "applicability_filters": (
                TaxonomyCondition(key="product_code", operator="EQ", values=("P-1",)),
            )
        }
    )

    if allowed:
        assert adapter.search(request)
    else:
        with pytest.raises(OpenSearchProjectionError, match="applicability"):
            adapter.search(request)


def test_runtime_applicability_rejects_rule_predicates_as_user_facts() -> None:
    with pytest.raises(ValueError, match="one-value EQ facts"):
        HybridSearchRequest.model_validate(
            {
                **search_request().model_dump(mode="python"),
                "applicability_filters": (
                    TaxonomyCondition(key="product_code", operator="IN", values=("P-1", "P-2")),
                ),
            }
        )


def test_projection_revision_must_match_generation() -> None:
    document = projection_document().model_copy(update={"projection_revision": "other"})
    with pytest.raises(ValueError, match="projection revision"):
        project_rule_unit_document(
            document,
            identity=index_identity(),
            publication_attempt_id="attempt-1",
        )


def test_generation_rejects_digest_that_does_not_match_local_mapping() -> None:
    identity = index_identity()
    wrong = identity.model_copy(
        update={"generation": identity.generation.model_copy(update={"mapping_sha256": SHA_A})}
    )
    with pytest.raises(OpenSearchProjectionError, match="actual mapping"):
        OpenSearchHybridIndex(transport=RecordingTransport()).verify_identity(wrong)


def test_index_identity_rejects_self_asserted_meta_over_mutated_actual_mapping() -> None:
    class MutatedMappingTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["method"] == "GET" and kwargs["path"].startswith("/pa-knowledge-"):
                body = dict(response.body)
                index = physical_index_name("source-1", "generation-1")
                details = body[index]
                mappings = details["mappings"]  # type: ignore[index]
                mappings["properties"]["content"]["index"] = True  # type: ignore[index]
                return OpenSearchTransportResponse(status_code=200, body=body)
            return response

    with pytest.raises(OpenSearchProjectionError, match="actual mapping digest"):
        OpenSearchHybridIndex(transport=MutatedMappingTransport()).verify_identity(index_identity())


def test_index_identity_rejects_name_only_analyzer_settings_drift() -> None:
    class MutatedAnalysisTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["method"] == "GET" and kwargs["path"].startswith("/pa-knowledge-"):
                body = dict(response.body)
                index = physical_index_name("source-1", "generation-1")
                analysis = body[index]["settings"]["index"]["analysis"]  # type: ignore[index]
                analysis["analyzer"]["proof_agent_cjk_v1"]["filter"] = [  # type: ignore[index]
                    "lowercase"
                ]
                return OpenSearchTransportResponse(status_code=200, body=body)
            return response

    with pytest.raises(OpenSearchProjectionError, match="actual analyzer settings"):
        OpenSearchHybridIndex(transport=MutatedAnalysisTransport()).verify_identity(
            index_identity()
        )


def test_index_identity_rejects_replica_setting_drift() -> None:
    class MutatedReplicaTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["method"] == "GET" and kwargs["path"].startswith("/pa-knowledge-"):
                body = dict(response.body)
                index = physical_index_name("source-1", "generation-1")
                body[index]["settings"]["index"]["number_of_replicas"] = "0"  # type: ignore[index]
                return OpenSearchTransportResponse(status_code=200, body=body)
            return response

    with pytest.raises(OpenSearchProjectionError, match="replica setting"):
        OpenSearchHybridIndex(transport=MutatedReplicaTransport()).verify_identity(index_identity())


def test_search_rejects_mutated_content_addressed_rrf_pipeline() -> None:
    class MutatedPipelineTransport(RecordingTransport):
        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].startswith("/_search/pipeline/") and response.status_code == 200:
                pipeline = rrf_pipeline_name(rank_constant=60)
                return OpenSearchTransportResponse(
                    status_code=200,
                    body={pipeline: rrf_pipeline_body(rank_constant=61)},
                )
            return response

    with pytest.raises(OpenSearchProjectionError, match="pipeline content"):
        OpenSearchHybridIndex(
            transport=MutatedPipelineTransport(search_hits=[projected_search_hit()])
        ).search(search_request())


def test_search_rejects_rrf_pipeline_mutated_between_pre_and_post_checks() -> None:
    class AbaPipelineTransport(RecordingTransport):
        def __init__(self) -> None:
            super().__init__(search_hits=[projected_search_hit()])
            self.pipeline_reads = 0

        def request(self, **kwargs: Any) -> OpenSearchTransportResponse:
            response = super().request(**kwargs)
            if kwargs["path"].startswith("/_search/pipeline/"):
                self.pipeline_reads += 1
                if self.pipeline_reads == 2:
                    pipeline = rrf_pipeline_name(rank_constant=60)
                    return OpenSearchTransportResponse(
                        status_code=200,
                        body={pipeline: rrf_pipeline_body(rank_constant=61)},
                    )
            return response

    with pytest.raises(OpenSearchProjectionError, match="pipeline content"):
        OpenSearchHybridIndex(transport=AbaPipelineTransport()).search(search_request())
