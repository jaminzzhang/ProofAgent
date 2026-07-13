from __future__ import annotations

import hashlib
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from proof_agent.capabilities.knowledge.hybrid.manifest import ManifestRuleUnitMembership
from proof_agent.capabilities.knowledge.hybrid.model_clients import EmbeddingResult
from proof_agent.capabilities.knowledge.hybrid.opensearch import (
    HttpxOpenSearchTransport,
    OpenSearchHybridIndex,
    physical_index_name,
    rrf_pipeline_name,
    rule_unit_analyzer_sha256,
    rule_unit_mapping_sha256,
)
from proof_agent.capabilities.knowledge.hybrid.publication import (
    HybridPublicationRequest,
    HybridPublicationService,
    HybridPublicationValidationAuthority,
    ProjectionSeed,
    hybrid_candidate_material_fingerprint,
)
from proof_agent.capabilities.knowledge.hybrid.recovery import (
    HybridRecoveryService,
    OpenSearchRecoveryIndex,
)
from proof_agent.capabilities.knowledge.hybrid.s3_artifacts import S3ExactArtifactStore
from proof_agent.capabilities.knowledge.hybrid.versioning import stable_digest
from proof_agent.capabilities.knowledge.hybrid.ports import SearchIndexIdentity
from proof_agent.configuration.postgres_hybrid_knowledge_repository import (
    PostgresHybridKnowledgeRepository,
)
from proof_agent.contracts.hybrid_documents import BoundingBox
from proof_agent.contracts.insurance_rules import (
    ApprovedInsuranceKnowledgeVisibilityScope,
    ApprovedInsuranceRuleMetadataRevision,
    InsuranceRuleApplicability,
    InsuranceRulePageBoundingBox,
    InsuranceRulePrecedence,
    InsuranceRuleUnitLineage,
    InsuranceRuleUnitRevision,
)
from proof_agent.contracts.knowledge_index import KnowledgeIndexGeneration, RuleUnitManifestEntry


pytestmark = pytest.mark.hybrid_integration
INSTRUCTION = "Represent the exact insurance rule for retrieval."


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"set {name} for disposable Hybrid integration")
    return value


class _Embedding:
    def embed(self, **kwargs: Any) -> EmbeddingResult:
        return EmbeddingResult(
            model_revision=kwargs["model_revision"],
            vectors=tuple((1.0, 0.0) for _ in kwargs["texts"]),
            queue_time_ms=1.0,
            service_time_ms=1.0,
        )


def _request(
    source_id: str,
    generation: KnowledgeIndexGeneration,
    identity: SearchIndexIdentity,
    *,
    rule_suffix: str = "one",
    publication_seq_from: int = 1,
):
    metadata = ApprovedInsuranceRuleMetadataRevision(
        metadata_revision_id=f"metadata-{source_id}",
        applicability=InsuranceRuleApplicability(
            taxonomy_id="integration", taxonomy_revision_id="v1"
        ),
        effective_from=date(2026, 1, 1),
        authority="integration",
        precedence=InsuranceRulePrecedence(
            policy_revision_id="v1", authority_tier="product", order=1
        ),
    )
    visibility = ApprovedInsuranceKnowledgeVisibilityScope(
        visibility="PUBLIC", revision_id=f"visibility-{source_id}"
    )
    content = f"Exact integration insurance rule {rule_suffix}."
    document_id = f"document-{source_id}-{rule_suffix}"
    revision_id = f"revision-{source_id}-{rule_suffix}"
    citation = (
        f"knowledge://source/{source_id}/document/{document_id}/revision/{revision_id}#page=1"
    )
    rule = InsuranceRuleUnitRevision(
        rule_unit_revision_id=f"rule-{source_id}-{rule_suffix}",
        logical_rule_key=f"logical-{source_id}-{rule_suffix}",
        unit_kind="clause",
        document_id=document_id,
        revision_id=revision_id,
        structured_build_id=f"build-{source_id}",
        content=content,
        citation_uri=citation,
        metadata_revision_id=metadata.metadata_revision_id,
        visibility_scope=visibility,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        authority_sha256=stable_digest(
            {
                "approved_metadata": metadata.model_dump(mode="json"),
                "approved_visibility": visibility.model_dump(mode="json"),
            }
        ),
        lineage=InsuranceRuleUnitLineage(
            source_id=source_id,
            original_sha256="e" * 64,
            page_numbers=(1,),
            page_bboxes=(
                InsuranceRulePageBoundingBox(
                    page_number=1,
                    bbox=BoundingBox(x0=0, y0=0, x1=10, y1=10),
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
        citation_uri=rule.citation_uri,
        publication_seq_from=publication_seq_from,
    )
    request = HybridPublicationRequest(
        source_id=source_id,
        source_draft_version_id=f"draft-{publication_seq_from}",
        candidate_digest="0" * 64,
        source_snapshot_id=f"snapshot-{publication_seq_from}",
        generation=generation,
        validation_id=f"validation-{source_id}-{publication_seq_from}",
        published_by="integration",
        memberships=(
            ManifestRuleUnitMembership(
                rule_unit=rule,
                publication_seq_from=publication_seq_from,
            ),
        ),
        projection_seeds=(
            ProjectionSeed(
                projection_id=f"projection-{source_id}-{rule_suffix}",
                rule_unit=rule,
                manifest_entry=entry,
                approved_metadata=metadata,
                projection_revision="rule-unit-search.v1",
            ),
        ),
        identity=identity,
        embedding_instruction=INSTRUCTION,
        embedding_timeout_seconds=30.0,
    )
    return request.model_copy(
        update={"candidate_digest": hybrid_candidate_material_fingerprint(request)}
    )


def _delete_prefix_versions(client: Any, bucket: str, prefix: str) -> None:
    paginator = client.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        objects = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for field in ("Versions", "DeleteMarkers")
            for item in page.get(field, [])
        ]
        if objects:
            client.delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})


def _environment():
    import boto3
    import psycopg

    dsn = _required("HYBRID_TEST_POSTGRES_DSN")
    endpoint = _required("HYBRID_TEST_S3_ENDPOINT")
    bucket = _required("HYBRID_TEST_S3_BUCKET")
    opensearch_url = _required("HYBRID_TEST_OPENSEARCH_URL")
    run_id = uuid4().hex
    prefix = f"test-runs/{run_id}/"
    migration = Path("proof_agent/configuration/migrations/0001_hybrid_knowledge.sql").read_text(
        encoding="utf-8"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(migration, prepare=False)
    s3_client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_required("HYBRID_TEST_S3_ACCESS_KEY"),
        aws_secret_access_key=_required("HYBRID_TEST_S3_SECRET_KEY"),
        region_name="us-east-1",
    )
    store = S3ExactArtifactStore(client=s3_client, bucket=bucket, key_prefix=prefix)
    source_id = f"integration-{run_id}"
    generation = KnowledgeIndexGeneration(
        generation_id=f"generation-{run_id}",
        source_id=source_id,
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256=rule_unit_mapping_sha256(dimension=2),
        analyzer_sha256=rule_unit_analyzer_sha256(),
        embedding_model_revision="embedding@sha256:integration",
        embedding_instruction_sha256=hashlib.sha256(INSTRUCTION.encode()).hexdigest(),
        embedding_dimension=2,
        normalized=True,
    )
    transport = HttpxOpenSearchTransport(
        endpoint=opensearch_url,
        allowed_hosts=("127.0.0.1", "localhost"),
        allow_insecure_loopback=True,
        timeout_seconds=30,
    )
    index = OpenSearchHybridIndex(transport=transport, number_of_replicas=0)
    identity = index.create_index(
        generation,
        rrf_pipeline=rrf_pipeline_name(rank_constant=60),
        rrf_rank_constant=60,
    )
    repository = PostgresHybridKnowledgeRepository.from_dsn(dsn)
    request = _request(source_id, generation, identity)
    repository.register_source(
        source_id=source_id,
        source_draft_version_id="draft-1",
        candidate_digest=request.candidate_digest,
        generation=generation,
    )
    repository.register_validation(
        HybridPublicationValidationAuthority(
            validation_id=request.validation_id,
            source_id=request.source_id,
            source_draft_version_id=request.source_draft_version_id,
            candidate_digest=request.candidate_digest,
            generation_id=request.generation.generation_id,
            validated_at=datetime.now(UTC),
            validated_by="integration-validator",
        )
    )
    service = HybridPublicationService(
        repository=repository,
        artifact_store=store,
        index=index,
        embedding=cast(Any, _Embedding()),
    )
    return {
        "bucket": bucket,
        "prefix": prefix,
        "s3": s3_client,
        "transport": transport,
        "index": index,
        "repository": repository,
        "store": store,
        "request": request,
        "service": service,
        "identity": identity,
        "source_id": source_id,
        "generation": generation,
    }


def _cleanup(env: dict[str, Any]) -> None:
    identities = env.get("cleanup_identities", [env["identity"]])
    for identity in identities:
        locator = identity.projection_locator or physical_index_name(
            identity.generation.source_id, identity.generation.generation_id
        )
        env["transport"].request(method="DELETE", path=f"/{locator}")
    env["transport"].close()
    env["repository"].close()
    _delete_prefix_versions(env["s3"], env["bucket"], env["prefix"])


def test_disposable_postgres_s3_fenced_publication_and_shared_orphan_repair() -> None:
    env = _environment()
    try:
        publication = env["service"].publish(env["request"])
        assert publication.source_publication_seq == 1
        assert env["store"].get_exact(publication.manifest_ref)

        class FailAfterRefresh:
            def materialize_authority(self, *args: Any, **kwargs: Any) -> Any:
                return env["index"].materialize_authority(*args, **kwargs)

            def bulk_upsert(self, request: Any) -> Any:
                env["index"].bulk_upsert(request)
                raise RuntimeError("integration failure after refresh")

            def close_projection_memberships(self, request: Any) -> Any:
                return env["index"].close_projection_memberships(request)

            def validate_exact_projection(self, request: Any) -> Any:
                return env["index"].validate_exact_projection(request)

        env["service"].index = FailAfterRefresh()
        second = _request(
            env["source_id"],
            env["generation"],
            env["identity"],
            rule_suffix="orphan",
            publication_seq_from=2,
        )
        env["repository"].advance_source_candidate(
            source_id=env["source_id"],
            expected_source_draft_version_id=env["request"].source_draft_version_id,
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
                validated_by="integration-validator",
            )
        )
        with pytest.raises(RuntimeError, match="after refresh"):
            env["service"].publish(second)
        assert env["repository"].load_active_publication(env["source_id"]) == publication
        recovery = HybridRecoveryService(
            repository=env["repository"],
            artifact_store=env["store"],
            index=OpenSearchRecoveryIndex(
                index=env["index"],
                embedding=cast(Any, _Embedding()),
                embedding_instruction=INSTRUCTION,
            ),
        )
        dry_run = recovery.reconcile_orphans(source_id=env["source_id"])
        assert dry_run.candidates
        applied = recovery.reconcile_orphans(source_id=env["source_id"], apply=True)
        assert applied.deleted_attempt_ids == dry_run.candidates
        assert env["index"].verify_identity(env["identity"]) == env["identity"]
    finally:
        _cleanup(env)
