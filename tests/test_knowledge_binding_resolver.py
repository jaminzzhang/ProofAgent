from __future__ import annotations

from pathlib import Path

import pytest

import proof_agent.capabilities.knowledge.http_json as http_json_module
from proof_agent.bootstrap.knowledge_resolution import (
    ConfigurationStoreKnowledgeBindingResolver,
    PackageKnowledgeBindingResolver,
)
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import KnowledgeSourceSnapshotManifest
from proof_agent.errors import ProofAgentError


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
