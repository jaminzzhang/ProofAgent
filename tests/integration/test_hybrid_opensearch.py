from __future__ import annotations

from datetime import date
import hashlib
import os
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    HttpxOpenSearchTransport,
    OpenSearchHybridIndex,
    OpenSearchProjectionError,
    physical_index_name,
    rrf_pipeline_name,
    rule_unit_analyzer_sha256,
    rule_unit_mapping_sha256,
)
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.capabilities.knowledge.hybrid.ports import (
    HybridSearchRequest,
    ProjectionBulkRequest,
    ProjectionDocument,
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
)
from proof_agent.contracts.hybrid_documents import BoundingBox


pytestmark = pytest.mark.hybrid_integration
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _endpoint() -> str:
    endpoint = os.environ.get("HYBRID_TEST_OPENSEARCH_URL")
    if endpoint is None:
        pytest.skip("set HYBRID_TEST_OPENSEARCH_URL for disposable OpenSearch integration")
    return endpoint


def _generation(source_id: str) -> KnowledgeIndexGeneration:
    return KnowledgeIndexGeneration(
        generation_id="generation-1",
        source_id=source_id,
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256=rule_unit_mapping_sha256(dimension=2),
        analyzer_sha256=rule_unit_analyzer_sha256(),
        embedding_model_revision="embedding@test",
        embedding_instruction_sha256=SHA_C,
        embedding_dimension=2,
        normalized=True,
    )


def _document(
    *,
    source_id: str,
    identifier: str,
    content: str,
    embedding: tuple[float, float],
    publication_seq_to: int | None = None,
) -> ProjectionDocument:
    visibility = ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="PUBLIC",
        revision_id=f"visibility-{identifier}",
    )
    citation = (
        f"knowledge://source/{source_id}/document/document-{identifier}/"
        f"revision/revision-{identifier}#page=1"
    )
    rule = InsuranceRuleUnitRevision(
        rule_unit_revision_id=f"rule-{identifier}",
        logical_rule_key=f"logical-{identifier}",
        unit_kind="clause",
        document_id=f"document-{identifier}",
        revision_id=f"revision-{identifier}",
        structured_build_id=f"build-{identifier}",
        content=content,
        citation_uri=citation,
        metadata_revision_id=f"metadata-{identifier}",
        visibility_scope=visibility,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        authority_sha256=stable_digest(
            {
                "approved_metadata": ApprovedInsuranceRuleMetadataRevision(
                    metadata_revision_id=f"metadata-{identifier}",
                    applicability=InsuranceRuleApplicability(
                        taxonomy_id="integration-taxonomy",
                        taxonomy_revision_id="v1",
                    ),
                    effective_from=date(2026, 1, 1),
                    authority="integration",
                    precedence=InsuranceRulePrecedence(
                        policy_revision_id="v1",
                        authority_tier="product",
                        order=1,
                    ),
                ).model_dump(mode="json"),
                "approved_visibility": visibility.model_dump(mode="json"),
            }
        ),
        lineage=InsuranceRuleUnitLineage(
            source_id=source_id,
            original_sha256="d" * 64,
            heading_path=("保险责任",),
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=100, y1=100),
                ),
            ),
            block_ids=(f"block-{identifier}",),
        ),
    )
    return ProjectionDocument(
        projection_id=f"projection-{identifier}",
        rule_unit=rule,
        manifest_entry=RuleUnitManifestEntry(
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
        ),
        approved_metadata=ApprovedInsuranceRuleMetadataRevision(
            metadata_revision_id=rule.metadata_revision_id,
            applicability=InsuranceRuleApplicability(
                taxonomy_id="integration-taxonomy",
                taxonomy_revision_id="v1",
            ),
            effective_from=date(2026, 1, 1),
            authority="integration",
            precedence=InsuranceRulePrecedence(
                policy_revision_id="v1",
                authority_tier="product",
                order=1,
            ),
        ),
        projection_revision="rule-unit-search.v1",
        embedding=embedding,
    )


def test_disposable_opensearch_supports_exact_filtered_hybrid_rrf_and_interval_close() -> None:
    endpoint = _endpoint()
    source_id = f"integration-{uuid4().hex}"
    generation = _generation(source_id)
    index_name = physical_index_name(source_id, generation.generation_id)
    transport = HttpxOpenSearchTransport(
        endpoint=endpoint,
        allowed_hosts=("127.0.0.1", "localhost"),
        allow_insecure_loopback=True,
        timeout_seconds=30,
    )
    adapter = OpenSearchHybridIndex(transport=transport, number_of_replicas=0)
    try:
        identity = adapter.create_index(
            generation,
            rrf_pipeline=rrf_pipeline_name(rank_constant=60),
            rrf_rank_constant=60,
        )
        first = _document(
            source_id=source_id,
            identifier="first",
            content="住院保险金符合合同条件时给付。",
            embedding=(1.0, 0.0),
        )
        second = _document(
            source_id=source_id,
            identifier="second",
            content="门诊责任另行约定。",
            embedding=(0.0, 1.0),
        )
        bulk = ProjectionBulkRequest(
            identity=identity,
            publication_attempt_id="attempt-1",
            manifest_root_sha256=SHA_A,
            documents=(first, second),
        )
        assert adapter.bulk_upsert(bulk).accepted_count == 2
        request = HybridSearchRequest(
            identity=identity,
            manifest_root_sha256=SHA_A,
            query_text="住院保险金",
            query_embedding=(1.0, 0.0),
            source_publication_seq=1,
            authorization=InstitutionAuthorizationContext(),
            as_of_date=date(2026, 7, 14),
            lexical_budget=10,
            dense_budget=10,
            rrf_window=10,
            rrf_pipeline=rrf_pipeline_name(rank_constant=60),
            rrf_rank_constant=60,
            limit=2,
        )
        hits = adapter.search(request)
        assert hits
        assert hits[0].rule_unit_revision_id == "rule-first"
        assert all(hit.source_id == source_id for hit in hits)

        closed = _document(
            source_id=source_id,
            identifier="first",
            content="住院保险金符合合同条件时给付。",
            embedding=(1.0, 0.0),
            publication_seq_to=1,
        )
        second_with_new_manifest = _document(
            source_id=source_id,
            identifier="second",
            content="门诊责任另行约定。",
            embedding=(0.0, 1.0),
        )
        adapter.bulk_upsert(
            ProjectionBulkRequest(
                identity=identity,
                publication_attempt_id="attempt-2",
                manifest_root_sha256=SHA_B,
                documents=(closed, second_with_new_manifest),
            )
        )
        assert any(hit.rule_unit_revision_id == "rule-first" for hit in adapter.search(request))
        later_hits = adapter.search(
            request.model_copy(
                update={"source_publication_seq": 2, "manifest_root_sha256": SHA_B}
            )
        )
        assert all(hit.rule_unit_revision_id != "rule-first" for hit in later_hits)
        assert any(hit.rule_unit_revision_id == "rule-second" for hit in later_hits)
        with pytest.raises(OpenSearchProjectionError, match="UUID"):
            adapter.verify_identity(identity.model_copy(update={"index_uuid": "wrong"}))
    finally:
        transport.request(method="DELETE", path=f"/{index_name}")
        transport.close()
