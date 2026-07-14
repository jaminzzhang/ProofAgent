from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import proof_agent.capabilities.knowledge.http_json as http_json_module
from proof_agent.bootstrap.knowledge_resolution import (
    ConfigurationStoreKnowledgeBindingResolver,
    PackageKnowledgeBindingResolver,
)
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.configuration.hybrid_knowledge_repository import (
    HybridKnowledgeBindingAuthoritySnapshot,
    InMemoryHybridKnowledgeBindingAuthority,
)
from proof_agent.contracts import (
    ExactArtifactRef,
    FrozenDict,
    HybridKnowledgePublicationRecord,
    KnowledgeProjectionAttestation,
    KnowledgeRetrievalProfileRevision,
    KnowledgeSourceSnapshotManifest,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


def test_resolved_knowledge_binding_set_round_trips_mixed_binding_types() -> None:
    bindings = ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeBinding(
                binding_id="kb_legacy",
                source_scope="shared",
                source_id="ks_legacy",
                source_version_id="snapshot_legacy",
                provider="local_index",
            ),
            ResolvedHybridKnowledgeBinding(
                binding_id="kb_hybrid",
                source_id="ks_hybrid",
                source_publication_id="publication_001",
                source_snapshot_id="snapshot_001",
                index_generation_id="generation_001",
                source_publication_seq=1,
                retrieval_profile_revision_id="profile_001",
                manifest_ref=ExactArtifactRef(
                    artifact_uri="s3://knowledge/manifests/root.json",
                    version_id="manifest_001",
                    sha256="1" * 64,
                    size_bytes=42,
                    media_type="application/json",
                ),
                publication_attestation_id="attestation_001",
            ),
        )
    )

    restored = ResolvedKnowledgeBindingSet.model_validate_json(bindings.model_dump_json())

    assert [binding.binding_id for binding in restored.bindings] == [
        "kb_legacy",
        "kb_hybrid",
    ]
    assert isinstance(restored.bindings[0], ResolvedKnowledgeBinding)
    assert isinstance(restored.bindings[1], ResolvedHybridKnowledgeBinding)


def test_resolved_knowledge_binding_set_loads_legacy_payload_without_discriminator() -> None:
    legacy_payload = {
        "bindings": [
            {
                "binding_id": "kb_legacy",
                "source_scope": "shared",
                "source_id": "ks_legacy",
                "source_version_id": "snapshot_legacy",
                "provider": "local_index",
                "provider_params": {},
            }
        ]
    }

    restored = ResolvedKnowledgeBindingSet.model_validate(legacy_payload)

    assert isinstance(restored.bindings[0], ResolvedKnowledgeBinding)
    assert restored.model_dump(mode="json")["bindings"][0]["binding_kind"] == "legacy"


@pytest.mark.parametrize("binding_kind", [None, "legacy"])
def test_resolved_knowledge_binding_set_rejects_legacy_payload_with_hybrid_reserved_keys(
    binding_kind: str | None,
) -> None:
    binding = _legacy_binding_payload(source_publication_id="publication_001")
    if binding_kind is not None:
        binding["binding_kind"] = binding_kind

    with pytest.raises(ValidationError):
        ResolvedKnowledgeBindingSet.model_validate({"bindings": [binding]})


def test_resolved_legacy_binding_direct_construction_rejects_hybrid_reserved_keys() -> None:
    with pytest.raises(ValidationError):
        ResolvedKnowledgeBinding.model_validate(
            _legacy_binding_payload(source_snapshot_id="snapshot_001")
        )


def test_resolved_knowledge_binding_set_rejects_omitted_kind_for_hybrid_provider() -> None:
    binding = _legacy_binding_payload(provider="hybrid_index")

    with pytest.raises(ValidationError):
        ResolvedKnowledgeBindingSet.model_validate({"bindings": [binding]})


def test_resolved_knowledge_binding_set_preserves_unknown_legacy_extension_compatibility() -> None:
    binding = _legacy_binding_payload(future_legacy_extension={"revision": "future_001"})

    restored = ResolvedKnowledgeBindingSet.model_validate({"bindings": [binding]})

    assert isinstance(restored.bindings[0], ResolvedKnowledgeBinding)
    assert restored.bindings[0].binding_kind == "legacy"


def test_legacy_discriminator_migration_does_not_mutate_caller_dict_list_or_tuple() -> None:
    for bindings in (
        [_legacy_binding_payload()],
        (_legacy_binding_payload(),),
    ):
        original_binding = dict(bindings[0])
        payload = {"bindings": bindings}

        restored = ResolvedKnowledgeBindingSet.model_validate(payload)

        assert isinstance(restored.bindings[0], ResolvedKnowledgeBinding)
        assert payload["bindings"] is bindings
        assert bindings[0] == original_binding
        assert "binding_kind" not in bindings[0]


def test_legacy_discriminator_migration_accepts_frozen_mapping_and_tuple_input() -> None:
    frozen_binding = FrozenDict(_legacy_binding_payload())
    frozen_bindings = (frozen_binding,)
    frozen_payload = FrozenDict({"bindings": frozen_bindings})

    restored = ResolvedKnowledgeBindingSet.model_validate(frozen_payload)

    assert isinstance(restored.bindings[0], ResolvedKnowledgeBinding)
    assert restored.bindings[0].binding_kind == "legacy"
    assert frozen_payload["bindings"] is frozen_bindings
    assert "binding_kind" not in frozen_binding


def test_resolved_knowledge_binding_set_schema_declares_binding_kind_discriminator() -> None:
    schema = ResolvedKnowledgeBindingSet.model_json_schema()
    discriminator = schema["properties"]["bindings"]["items"]["discriminator"]

    assert discriminator["propertyName"] == "binding_kind"
    assert set(discriminator["mapping"]) == {"legacy", "hybrid"}


@pytest.mark.parametrize(
    "binding_kind,provider",
    [
        ("unknown", "hybrid_index"),
        ("hybrid", "local_index"),
        ("legacy", "hybrid_index"),
    ],
)
def test_resolved_knowledge_binding_set_rejects_unknown_or_mismatched_discriminator(
    binding_kind: str,
    provider: str,
) -> None:
    payload = _hybrid_binding_payload()
    payload.update(binding_kind=binding_kind, provider=provider)
    if binding_kind == "legacy":
        payload["source_version_id"] = "snapshot_001"

    with pytest.raises(ValidationError):
        ResolvedKnowledgeBindingSet.model_validate({"bindings": [payload]})


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("binding_id", "   "),
        ("source_id", ""),
        ("source_publication_id", "\t"),
        ("source_snapshot_id", ""),
        ("index_generation_id", " "),
        ("retrieval_profile_revision_id", ""),
        ("publication_attestation_id", "  "),
        ("source_publication_seq", 0),
        ("source_publication_seq", True),
        ("fusion_weight", 0.0),
        ("fusion_weight", float("inf")),
        ("failure_mode", "fallback"),
    ],
)
def test_resolved_hybrid_knowledge_binding_rejects_invalid_governance_facts(
    field_name: str,
    invalid_value: object,
) -> None:
    payload = _hybrid_binding_payload()
    payload[field_name] = invalid_value

    with pytest.raises(ValidationError):
        ResolvedHybridKnowledgeBinding.model_validate(payload)


def _hybrid_binding_payload() -> dict[str, object]:
    return {
        "binding_kind": "hybrid",
        "binding_id": "kb_hybrid",
        "source_scope": "shared",
        "source_id": "ks_hybrid",
        "provider": "hybrid_index",
        "source_publication_id": "publication_001",
        "source_snapshot_id": "snapshot_001",
        "index_generation_id": "generation_001",
        "source_publication_seq": 1,
        "retrieval_profile_revision_id": "profile_001",
        "manifest_ref": {
            "artifact_uri": "s3://knowledge/manifests/root.json",
            "version_id": "manifest_001",
            "sha256": "1" * 64,
            "size_bytes": 42,
            "media_type": "application/json",
        },
        "publication_attestation_id": "attestation_001",
        "failure_mode": "required",
        "fusion_weight": 1.0,
    }


def _legacy_binding_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "binding_id": "kb_legacy",
        "source_scope": "shared",
        "source_id": "ks_legacy",
        "source_version_id": "snapshot_legacy",
        "provider": "local_index",
        "provider_params": {},
    }
    payload.update(overrides)
    return payload


def _hybrid_publication(
    *,
    source_id: str,
    source_draft_version_id: str,
    publication_id: str = "publication-7",
    source_publication_seq: int = 7,
) -> HybridKnowledgePublicationRecord:
    manifest_ref = ExactArtifactRef(
        artifact_uri="s3://knowledge/manifests/root.json",
        version_id="manifest-version-7",
        sha256="1" * 64,
        size_bytes=42,
        media_type="application/json",
    )
    attestation = KnowledgeProjectionAttestation(
        attestation_id="attestation-7",
        attestation_sha256="2" * 64,
        source_id=source_id,
        generation_id="generation-7",
        publication_attempt_id="attempt-7",
        index_uuid="index-uuid-7",
        refresh_checkpoint="refresh-7",
        manifest_root_sha256=manifest_ref.sha256,
        mapping_sha256="3" * 64,
        covered_publication_sequences=(source_publication_seq,),
        projection_sha256="4" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )
    return HybridKnowledgePublicationRecord(
        publication_id=publication_id,
        source_id=source_id,
        source_draft_version_id=source_draft_version_id,
        source_snapshot_id="snapshot-7",
        source_publication_seq=source_publication_seq,
        candidate_digest="5" * 64,
        generation_id="generation-7",
        manifest_ref=manifest_ref,
        attestation=attestation,
        validation_id="validation-7",
        published_at=datetime(2026, 7, 14, tzinfo=UTC),
        published_by="operator",
    )


def _hybrid_profile(
    profile_revision_id: str = "profile-2",
) -> KnowledgeRetrievalProfileRevision:
    return KnowledgeRetrievalProfileRevision(
        profile_revision_id=profile_revision_id,
        lexical_budget=100,
        dense_budget=100,
        rrf_window=50,
        reranker_revision="reranker-2",
        rerank_budget=50,
        final_budget=16,
    )


def test_package_resolver_resolves_package_source(tmp_path: Path) -> None:
    agent_yaml = _write_agent_manifest(tmp_path, source_ref_scope="package")

    resolved = PackageKnowledgeBindingResolver().resolve(load_agent_manifest(agent_yaml))

    binding = resolved.bindings[0]
    assert binding.binding_id == "kb_local"
    assert binding.source_scope == "package"
    assert binding.source_id == "ks_local"
    assert binding.source_version_id == "package"
    assert binding.provider == "local_markdown"
    assert binding.provider_params["path"] == (tmp_path / "knowledge").resolve()
    assert binding.alias == "policy_docs"
    assert binding.failure_mode == "required"
    assert binding.fusion_weight == 1.25
    assert binding.top_k == 2


def test_package_resolver_rejects_shared_source_ref(tmp_path: Path) -> None:
    agent_yaml = _write_agent_manifest(
        tmp_path,
        source_ref_scope="shared",
        package_sources_yaml="package_knowledge_sources: []",
    )

    with pytest.raises(ProofAgentError) as exc:
        PackageKnowledgeBindingResolver().resolve(load_agent_manifest(agent_yaml))

    assert exc.value.code == "PA_CONFIG_002"
    assert "Configuration Store resolver" in exc.value.fix


def test_package_resolver_rejects_hybrid_profile_selection(tmp_path: Path) -> None:
    agent_yaml = _write_agent_manifest(tmp_path, source_ref_scope="package")
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace(
            "    alias: policy_docs\n",
            "    retrieval_profile_revision_id: profile_001\n    alias: policy_docs\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        PackageKnowledgeBindingResolver().resolve(load_agent_manifest(agent_yaml))

    assert exc.value.code == "PA_CONFIG_002"
    assert "Hybrid" in exc.value.message


def test_configuration_store_resolver_rejects_unpublished_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="ks_local",
        name="Policy Knowledge",
        provider="local_index",
        params={"ingestion_model": {"provider": "deterministic", "name": "routing"}},
        actor="operator",
    )
    manifest = load_agent_manifest(
        _write_agent_manifest(
            tmp_path,
            source_ref_scope="shared",
            package_sources_yaml="package_knowledge_sources: []",
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)

    assert exc.value.code == "PA_CONFIG_002"
    assert "published" in exc.value.message


def test_configuration_store_resolver_pins_hybrid_publication_and_profile(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_local",
        name="Hybrid Policy Knowledge",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    publication = _hybrid_publication(
        source_id=source.source_id,
        source_draft_version_id=source.source_draft_version_id or "draft-7",
    )
    profile = _hybrid_profile()

    class Authority:
        def resolve_binding_authority(
            self,
            *,
            source_id: str,
            profile_revision_id: str | None,
        ) -> HybridKnowledgeBindingAuthoritySnapshot | None:
            assert source_id == source.source_id
            assert profile_revision_id == profile.profile_revision_id
            return HybridKnowledgeBindingAuthoritySnapshot(
                publication=publication,
                retrieval_profile=profile,
            )

    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": publication.publication_id})
    )
    agent_yaml = _write_agent_manifest(
        tmp_path,
        source_ref_scope="shared",
        package_sources_yaml="package_knowledge_sources: []",
    )
    agent_yaml.write_text(
        agent_yaml.read_text(encoding="utf-8").replace(
            "    source_ref:\n      scope: shared\n      source_id: ks_local\n",
            "    source_ref:\n      scope: shared\n      source_id: ks_local\n"
            "    retrieval_profile_revision_id: profile-2\n",
        ),
        encoding="utf-8",
    )

    resolved = ConfigurationStoreKnowledgeBindingResolver(
        store,
        hybrid_authority=Authority(),
    ).resolve(load_agent_manifest(agent_yaml))

    binding = resolved.bindings[0]
    assert isinstance(binding, ResolvedHybridKnowledgeBinding)
    assert binding.source_publication_id == publication.publication_id
    assert binding.source_snapshot_id == publication.source_snapshot_id
    assert binding.index_generation_id == publication.generation_id
    assert binding.source_publication_seq == 7
    assert binding.retrieval_profile_revision_id == profile.profile_revision_id
    assert binding.manifest_ref == publication.manifest_ref
    assert binding.publication_attestation_id == publication.attestation.attestation_id


def test_configuration_store_resolver_inherits_hybrid_source_default_profile(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_local",
        name="Hybrid Policy Knowledge",
        provider="hybrid_index",
        params={},
        actor="operator",
    )
    publication = _hybrid_publication(
        source_id=source.source_id,
        source_draft_version_id=source.source_draft_version_id or "draft-7",
    )
    profile = _hybrid_profile("profile-default")
    authority = InMemoryHybridKnowledgeBindingAuthority()
    authority.publish(publication)
    authority.publish_retrieval_profile(
        source_id=source.source_id,
        profile=profile,
        make_default=True,
    )
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": publication.publication_id})
    )
    manifest = load_agent_manifest(
        _write_agent_manifest(
            tmp_path,
            source_ref_scope="shared",
            package_sources_yaml="package_knowledge_sources: []",
        )
    )

    resolved = ConfigurationStoreKnowledgeBindingResolver(
        store,
        hybrid_authority=authority,
    ).resolve(manifest)

    binding = resolved.bindings[0]
    assert isinstance(binding, ResolvedHybridKnowledgeBinding)
    assert binding.retrieval_profile_revision_id == "profile-default"


def test_configuration_store_resolver_rejects_archived_source_before_publication_lookup(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_local",
        name="Policy Knowledge",
        provider="local_index",
        params={"ingestion_model": {"provider": "deterministic", "name": "routing"}},
        actor="operator",
    )
    store.archive_knowledge_source(
        source_id=source.source_id,
        actor="operator",
        reason="No longer maintained.",
    )
    manifest = load_agent_manifest(
        _write_agent_manifest(
            tmp_path,
            source_ref_scope="shared",
            package_sources_yaml="package_knowledge_sources: []",
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)

    assert exc.value.code == "PA_CONFIG_002"
    assert "archived" in exc.value.message


def test_configuration_store_resolver_maps_published_local_index_snapshot(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_local",
        name="Policy Knowledge",
        provider="local_index",
        params={
            "ingestion_model": {"provider": "deterministic", "name": "routing"},
            "document_selection_budget": 6,
        },
        actor="operator",
    )
    assert source.source_draft_version_id is not None
    snapshot = KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id="kssnapshot_001",
        source_id=source.source_id,
        state="READY",
        validation_level="foundation",
        source_draft_version_id=source.source_draft_version_id,
        candidate_digest="digest",
        foundation_validation_id="ksvalidation_001",
        documents=(),
        created_at="2026-06-04T00:00:00Z",
        created_by="operator",
    )
    store._write_knowledge_source_snapshot(snapshot)
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": snapshot.snapshot_id})
    )
    manifest = load_agent_manifest(
        _write_agent_manifest(
            tmp_path,
            source_ref_scope="shared",
            package_sources_yaml="package_knowledge_sources: []",
        )
    )

    resolved = ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)

    binding = resolved.bindings[0]
    assert binding.source_scope == "shared"
    assert binding.source_id == "ks_local"
    assert binding.source_version_id == snapshot.snapshot_id
    assert binding.provider == "local_index"
    assert binding.provider_params["snapshot_path"] == (
        store.root_dir / "knowledge_sources" / "ks_local" / "snapshots" / snapshot.snapshot_id
    )
    assert binding.provider_params["artifact_root"] == store.root_dir
    assert binding.provider_params["routing_model"] == {
        "provider": "deterministic",
        "name": "routing",
    }
    assert binding.provider_params["document_selection_budget"] == 6


def test_configuration_store_resolver_maps_mixed_package_and_shared_sources(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_shared",
        name="Shared Knowledge",
        provider="local_index",
        params={"ingestion_model": {"provider": "deterministic", "name": "routing"}},
        actor="operator",
    )
    assert source.source_draft_version_id is not None
    snapshot = KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id="kssnapshot_001",
        source_id=source.source_id,
        state="READY",
        validation_level="foundation",
        source_draft_version_id=source.source_draft_version_id,
        candidate_digest="digest",
        foundation_validation_id="ksvalidation_001",
        documents=(),
        created_at="2026-06-04T00:00:00Z",
        created_by="operator",
    )
    store._write_knowledge_source_snapshot(snapshot)
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": snapshot.snapshot_id})
    )
    agent_yaml = _write_agent_manifest(tmp_path, source_ref_scope="package")
    raw = agent_yaml.read_text(encoding="utf-8")
    raw = raw.replace(
        """  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
    alias: policy_docs
    failure_mode: required
    fusion_weight: 1.25
    top_k: 2
""",
        """  - binding_id: kb_local
    source_ref:
      scope: package
      source_id: ks_local
    alias: policy_docs
    failure_mode: required
    fusion_weight: 1.25
    top_k: 2
  - binding_id: kb_shared
    source_ref:
      scope: shared
      source_id: ks_shared
    alias: supplemental
    failure_mode: advisory
    fusion_weight: 0.75
    top_k: 3
""",
    )
    agent_yaml.write_text(raw, encoding="utf-8")

    resolved = ConfigurationStoreKnowledgeBindingResolver(store).resolve(
        load_agent_manifest(agent_yaml)
    )

    by_id = {binding.binding_id: binding for binding in resolved.bindings}
    assert by_id["kb_local"].source_scope == "package"
    assert by_id["kb_local"].provider == "local_markdown"
    assert by_id["kb_shared"].source_scope == "shared"
    assert by_id["kb_shared"].provider == "local_index"
    assert by_id["kb_shared"].source_version_id == snapshot.snapshot_id


def test_configuration_store_resolver_maps_published_http_json_remote_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="ks_local",
        name="Remote Knowledge",
        provider="http_json",
        params={"endpoint": "https://knowledge.example/retrieve", "top_k": 2},
        actor="operator",
    )
    monkeypatch.setattr(
        http_json_module,
        "_send_http_json_request",
        lambda request: {
            "protocol_version": "proof-agent.remote-retrieval.v1",
            "results": [
                {
                    "content": "Remote policy evidence.",
                    "score": 0.9,
                    "citation": "https://knowledge.example/policies#remote",
                }
            ],
        },
    )
    validation = store.validate_http_json_source_publication(
        source_id="ks_local",
        smoke_query="What does the remote policy say?",
        actor="validator",
    )
    publication = store.publish_knowledge_source(
        source_id="ks_local",
        validation_id=validation.validation_id,
        change_note="Publish remote API.",
        actor="operator",
    )
    manifest = load_agent_manifest(
        _write_agent_manifest(
            tmp_path,
            source_ref_scope="shared",
            package_sources_yaml="package_knowledge_sources: []",
        )
    )

    resolved = ConfigurationStoreKnowledgeBindingResolver(store).resolve(manifest)

    binding = resolved.bindings[0]
    assert binding.source_scope == "shared"
    assert binding.source_id == "ks_local"
    assert binding.source_version_id == publication.resource_id
    assert binding.provider == "http_json"
    assert binding.provider_params == {
        "endpoint": "https://knowledge.example/retrieve",
        "top_k": 2,
    }


def _write_agent_manifest(
    tmp_path: Path,
    *,
    source_ref_scope: str,
    package_sources_yaml: str | None = None,
) -> Path:
    agent_yaml = tmp_path / "agent.yaml"
    (tmp_path / "knowledge").mkdir()
    (tmp_path / "policy.yaml").write_text("rules: []\n", encoding="utf-8")
    (tmp_path / "tools.yaml").write_text("tools: []\n", encoding="utf-8")
    if package_sources_yaml is None:
        package_sources_yaml = """
package_knowledge_sources:
  - source_id: ks_local
    name: Local Knowledge
    provider: local_markdown
    params:
      path: ./knowledge
"""
    agent_yaml.write_text(
        f"""
name: resolver_test
purpose: "Resolve Knowledge bindings."
workflow:
  template: react_enterprise_qa_v3
  template_descriptor_version: react_enterprise_qa.v3
{package_sources_yaml}
knowledge_bindings:
  - binding_id: kb_local
    source_ref:
      scope: {source_ref_scope}
      source_id: ks_local
    alias: policy_docs
    failure_mode: required
    fusion_weight: 1.25
    top_k: 2
retrieval:
  strategy: single_step
react:
  planner:
    provider: deterministic
    name: demo
model:
  provider: deterministic
  name: demo
policy:
  file: ./policy.yaml
capabilities:
  tools:
    enabled: false
  memory:
    enabled: true
    provider: session
audit:
  trace_path: ./runs/trace.jsonl
  receipt_path: ./runs/governance_receipt.md
""",
        encoding="utf-8",
    )
    return agent_yaml
