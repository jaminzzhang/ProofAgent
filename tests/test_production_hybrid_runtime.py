from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

from proof_agent.bootstrap.production_hybrid_runtime import (
    EnvironmentOpenSearchSecretProvider,
    LoadedHybridBindingRuntime,
    ProductionHybridDeploymentSettings,
    ProductionHybridKnowledgeRuntime,
    compose_production_hybrid_runtime_from_env,
)
from proof_agent.capabilities.knowledge.hybrid.provider import HybridRetrievalAuthority
from proof_agent.capabilities.knowledge.hybrid.versioning import (
    projection_attestation_fingerprint,
)
from proof_agent.contracts import (
    ExactArtifactRef,
    KnowledgeIndexGeneration,
    KnowledgeProjectionAttestation,
    KnowledgeRetrievalProfileRevision,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.control.knowledge.hybrid_request import ApprovedInsuranceConditionTaxonomy


INSTRUCTION = "Represent the insurance rule query for retrieval."


def _binding() -> ResolvedHybridKnowledgeBinding:
    return ResolvedHybridKnowledgeBinding(
        binding_id="binding-1",
        source_id="source-1",
        source_publication_id="publication-1",
        source_snapshot_id="snapshot-1",
        index_generation_id="generation-1",
        source_publication_seq=1,
        retrieval_profile_revision_id="profile-1",
        manifest_ref=ExactArtifactRef(
            artifact_uri="s3://knowledge/root.json",
            version_id=f"sha256:{'a' * 64}",
            sha256="a" * 64,
            size_bytes=1,
            media_type="application/json",
        ),
        publication_attestation_id="attestation-1",
    )


def _authority() -> HybridRetrievalAuthority:
    generation = KnowledgeIndexGeneration(
        generation_id="generation-1",
        source_id="source-1",
        canonical_schema_version="structured-knowledge.v1",
        search_projection_version="rule-unit-search.v1",
        mapping_sha256="b" * 64,
        analyzer_sha256="c" * 64,
        embedding_model_revision="embedding@sha256:model-1",
        embedding_instruction_sha256=sha256(INSTRUCTION.encode()).hexdigest(),
        embedding_dimension=2,
        normalized=True,
    )
    digest = projection_attestation_fingerprint(
        source_id="source-1",
        generation_id="generation-1",
        publication_attempt_id="attempt-1",
        index_uuid="index-1",
        refresh_checkpoint="refresh-1",
        manifest_root_sha256="a" * 64,
        mapping_sha256="b" * 64,
        covered_publication_sequences=(1,),
        parent_attestation_sha256=None,
        projection_sha256="d" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )
    attestation = KnowledgeProjectionAttestation(
        attestation_id=f"attestation-{digest}",
        attestation_sha256=digest,
        source_id="source-1",
        generation_id="generation-1",
        publication_attempt_id="attempt-1",
        index_uuid="index-1",
        refresh_checkpoint="refresh-1",
        manifest_root_sha256="a" * 64,
        mapping_sha256="b" * 64,
        covered_publication_sequences=(1,),
        projection_sha256="d" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )
    return HybridRetrievalAuthority(
        generation=generation,
        attestation=attestation,
        embedding_instruction=INSTRUCTION,
        manifest_entry_core_sha256_by_rule_unit_revision_id={"rule-1": "e" * 64},
    )


def test_runtime_binds_frozen_agent_binding_to_online_provider_and_request_factory() -> None:
    binding = _binding().model_copy(
        update={"publication_attestation_id": _authority().attestation.attestation_id}
    )
    profile = KnowledgeRetrievalProfileRevision(
        profile_revision_id="profile-1",
        lexical_budget=10,
        dense_budget=10,
        rrf_window=10,
        reranker_revision="reranker@sha256:model-1",
        rerank_budget=5,
        final_budget=2,
    )
    loaded = LoadedHybridBindingRuntime(
        binding=binding,
        retrieval_profile=profile,
        retrieval_authority=_authority(),
    )
    calls: list[ResolvedHybridKnowledgeBinding] = []

    class Loader:
        def load(self, exact_binding: ResolvedHybridKnowledgeBinding) -> Any:
            calls.append(exact_binding)
            return loaded

    provider = object()

    class Graph:
        def compose_retrieval_provider(self, *, authority: Any, index: Any) -> object:
            assert authority == loaded.retrieval_authority
            assert index == "search-index"
            return provider

    runtime = ProductionHybridKnowledgeRuntime(
        model_graph=Graph(),
        authority_loader=Loader(),
        search_index="search-index",
        taxonomy=ApprovedInsuranceConditionTaxonomy(
            taxonomy_id="insurance",
            taxonomy_revision_id="insurance-v1",
            allowed_values={"region": ("SHANGHAI",)},
        ),
        clock=lambda: datetime(2026, 7, 15, tzinfo=UTC),
        owned_resources=(),
    )

    result = runtime.bind_for_run(ResolvedKnowledgeBindingSet(bindings=(binding,)))

    assert calls == [binding]
    assert result.hybrid_providers == {"binding-1": provider}
    assert result.governed_request_factory is not None
    assert result.governed_request_factory.binding == binding
    assert result.governed_request_factory.retrieval_profile == profile


def test_runtime_closes_owned_resources_once_in_reverse_order() -> None:
    events: list[str] = []
    resources = tuple(
        SimpleNamespace(close=lambda name=name: events.append(name))
        for name in ("repository", "artifact-store", "model-graph")
    )
    runtime = ProductionHybridKnowledgeRuntime(
        model_graph=SimpleNamespace(),
        authority_loader=SimpleNamespace(),
        search_index=object(),
        taxonomy=ApprovedInsuranceConditionTaxonomy(
            taxonomy_id="insurance",
            taxonomy_revision_id="insurance-v1",
            allowed_values={"region": ("SHANGHAI",)},
        ),
        clock=lambda: datetime(2026, 7, 15, tzinfo=UTC),
        owned_resources=resources,
    )

    runtime.close()
    runtime.close()

    assert events == ["model-graph", "artifact-store", "repository"]


def test_deployment_settings_build_candidate_bound_generation_and_profile() -> None:
    settings = ProductionHybridDeploymentSettings.from_environment(
        {
            "HYBRID_EMBEDDING_INSTRUCTION": INSTRUCTION,
            "HYBRID_EMBEDDING_MODEL_REVISION": "embedding@sha256:model-1",
            "HYBRID_EMBEDDING_DIMENSION": "2",
            "HYBRID_RERANKER_REVISION": "reranker@sha256:model-1",
            "HYBRID_RETRIEVAL_PROFILE_REVISION": "profile-1",
            "HYBRID_CONDITION_TAXONOMY_JSON": (
                '{"taxonomy_id":"insurance","taxonomy_revision_id":"insurance-v1",'
                '"allowed_values":{"region":["SHANGHAI"]}}'
            ),
            "HYBRID_APPROVED_VISIBILITY_JSON": (
                '{"visibility":"PUBLIC","revision_id":"visibility-public-v1"}'
            ),
        }
    )

    generation = settings.generation_for("source-1")
    profile = settings.retrieval_profile()

    assert generation.source_id == "source-1"
    assert generation.generation_id.startswith("generation-")
    assert generation.embedding_instruction_sha256 == sha256(INSTRUCTION.encode()).hexdigest()
    assert profile.profile_revision_id == "profile-1"
    assert profile.reranker_revision == "reranker@sha256:model-1"
    assert settings.approved_visibility.revision_id == "visibility-public-v1"


def test_production_runtime_requires_explicit_activation() -> None:
    assert compose_production_hybrid_runtime_from_env({}) is None


def test_opensearch_secret_provider_uses_indirect_environment_names() -> None:
    provider = EnvironmentOpenSearchSecretProvider(
        {
            "HYBRID_OPENSEARCH_AUTHORIZATION_ENV": "OPENSEARCH_AUTHORIZATION",
            "OPENSEARCH_AUTHORIZATION": "Bearer opaque-token",
            "HYBRID_OPENSEARCH_CA_BUNDLE_PATH_ENV": "OPENSEARCH_CA_PATH",
            "OPENSEARCH_CA_PATH": "/run/secrets/opensearch-ca.pem",
        }
    )

    material = provider.resolve("environment://hybrid-opensearch")

    assert material.headers == {"Authorization": "Bearer opaque-token"}
    assert material.ca_bundle_path == "/run/secrets/opensearch-ca.pem"
