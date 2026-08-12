from __future__ import annotations

from dataclasses import asdict
import json

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.memory.knowledge_catalog import (
    InMemoryKnowledgeCatalog,
)
from knowledge_source_service.application.hybrid_retrieval import (
    HybridKnowledgeRetrievalEngine,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.application.object_manifest_intake import (
    ObjectManifestIntakeApplication,
    ObjectManifestIntakeCommand,
)
from knowledge_source_service.contracts.knowledge_query import (
    CreateKnowledgeQueryRequest,
)
from knowledge_source_service.ports.authorization import KnowledgeQueryAdmission
from knowledge_source_service.ports.retrieval import AdmittedKnowledgeQuery


def test_object_manifest_materializes_only_exact_declared_members() -> None:
    artifacts = InMemoryImmutableArtifactStore()
    document = artifacts.put_immutable(
        object_key="imports/run-7/policy.md",
        content=b"# Delay\nFlight delay benefit is 300 CNY.\n",
        media_type="text/markdown",
    )
    dataset = artifacts.put_immutable(
        object_key="imports/run-7/claims.json",
        content=b'{"records":[{"claim_year":2026,"active":true}]}',
        media_type="application/json",
    )
    artifacts.put_immutable(
        object_key="imports/run-7/undeclared-secret.txt",
        content=b"this object must never be discovered",
        media_type="text/plain",
    )
    manifest = json.dumps(
        {
            "schema_version": "knowledge-object-manifest.v1",
            "knowledge_space_id": "space-manifest",
            "members": [
                {
                    "knowledge_source_id": "source-policy",
                    "display_filename": "policy.md",
                    "media_type": "text/markdown",
                    "artifact": asdict(document),
                },
                {
                    "knowledge_source_id": "source-claims",
                    "display_filename": "claims.json",
                    "media_type": "application/json",
                    "artifact": asdict(dataset),
                    "dataset_mapping": {
                        "record_path": ["records"],
                        "field_types": {
                            "claim_year": "integer",
                            "active": "boolean",
                        },
                    },
                },
            ],
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    catalog = InMemoryKnowledgeCatalog()

    published = ObjectManifestIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        document_pipeline_revision="document-pipeline-v1",
        dataset_pipeline_revision="dataset-pipeline-v1",
        allowed_object_prefix="imports/",
        max_manifest_bytes=64 * 1024,
        max_members=10,
        max_member_bytes=1024 * 1024,
        max_dataset_records=100,
    ).materialize(ObjectManifestIntakeCommand(content=manifest))

    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-manifest",
            knowledge_base_id="base-manifest",
            knowledge_source_version_ids=tuple(
                item.knowledge_source_version_id for item in published.source_versions
            ),
        )
    ).release
    result = HybridKnowledgeRetrievalEngine(catalog=catalog).retrieve(
        AdmittedKnowledgeQuery(
            request=CreateKnowledgeQueryRequest.model_validate(
                {
                    "knowledge_base_release_id": release.knowledge_base_release_id,
                    "question": "delay benefit",
                    "query_constraints": {
                        "filters": [
                            {"field": "claim_year", "operator": "eq", "value": 2026}
                        ]
                    },
                    "execution_budget": {
                        "max_rounds": 1,
                        "max_model_calls": 1,
                        "max_candidates": 10,
                        "max_model_tokens": 100,
                        "max_duration_ms": 1000,
                    },
                    "deadline_at": "2026-08-12T04:00:00Z",
                }
            ),
            admission=KnowledgeQueryAdmission(
                knowledge_space_id="space-manifest",
                client_grant_id="grant-manifest",
                effective_access_scope_digest=f"sha256:{'c' * 64}",
            ),
        )
    )

    assert len(published.source_versions) == 2
    assert published.manifest_artifact.sha256.startswith("sha256:")
    assert [group.group_type for group in result.evidence_groups] == [
        "relevance_ranked",
        "structured",
    ]
    returned_text = " ".join(
        candidate.content.text
        for group in result.evidence_groups
        for candidate in group.candidate_evidence
    )
    assert "300 CNY" in returned_text
    assert "undeclared-secret" not in returned_text
