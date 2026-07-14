"""Tests for resolving Published Agent Versions into governed execution."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import yaml  # type: ignore[import-untyped]

from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.configuration.hybrid_knowledge_repository import (
    InMemoryHybridKnowledgeBindingAuthority,
)
from proof_agent.contracts import (
    ContractBundle,
    ExactArtifactRef,
    HybridKnowledgePublicationRecord,
    KnowledgeProjectionAttestation,
    KnowledgeRetrievalProfileRevision,
    KnowledgeSourcePublicationRecord,
    KnowledgeSourceSnapshotManifest,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.delivery.published_agents import PublishedAgentRegistry
from proof_agent.errors import ProofAgentError
from proof_agent.observability.api.app import create_app


def _resolved_hybrid_binding(
    *, source_publication_id: str = "publication_001"
) -> ResolvedHybridKnowledgeBinding:
    return ResolvedHybridKnowledgeBinding(
        binding_id="kb_hybrid",
        source_id="ks_hybrid",
        source_publication_id=source_publication_id,
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
    )


def _seed_hybrid_binding_authority(
    authority: InMemoryHybridKnowledgeBindingAuthority,
    *,
    source_draft_version_id: str,
    publication_id: str = "publication_001",
) -> None:
    binding = _resolved_hybrid_binding(source_publication_id=publication_id)
    attestation = KnowledgeProjectionAttestation(
        attestation_id=binding.publication_attestation_id,
        attestation_sha256="2" * 64,
        source_id=binding.source_id,
        generation_id=binding.index_generation_id,
        publication_attempt_id="attempt_001",
        index_uuid="index-uuid-001",
        refresh_checkpoint="refresh-001",
        manifest_root_sha256=binding.manifest_ref.sha256,
        mapping_sha256="3" * 64,
        covered_publication_sequences=(binding.source_publication_seq,),
        projection_sha256="4" * 64,
        validated_document_count=1,
        validated_rule_unit_count=1,
    )
    authority.publish(
        HybridKnowledgePublicationRecord(
            publication_id=publication_id,
            source_id=binding.source_id,
            source_draft_version_id=source_draft_version_id,
            source_snapshot_id=binding.source_snapshot_id,
            source_publication_seq=binding.source_publication_seq,
            candidate_digest="5" * 64,
            generation_id=binding.index_generation_id,
            manifest_ref=binding.manifest_ref,
            attestation=attestation,
            validation_id="validation_001",
            published_at=datetime(2026, 7, 12, tzinfo=UTC),
            published_by="test-user",
        )
    )
    authority.publish_retrieval_profile(
        source_id=binding.source_id,
        profile=KnowledgeRetrievalProfileRevision(
            profile_revision_id=binding.retrieval_profile_revision_id,
            lexical_budget=100,
            dense_budget=100,
            rrf_window=50,
            reranker_revision="reranker-001",
            rerank_budget=50,
            final_budget=16,
        ),
        make_default=True,
    )


@pytest.mark.parametrize(
    ("published_resource_id", "binding_publication_id"),
    [
        ("publication_current", "publication_stale"),
        ("publication_001", "publication_001"),
    ],
)
def test_hybrid_shared_source_publication_guard_fails_closed_for_invalid_identity(
    tmp_path: Path,
    published_resource_id: str,
    binding_publication_id: str,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_hybrid",
        name="Hybrid Knowledge",
        provider="hybrid_index",
        params={},
        actor="test-user",
    )
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": published_resource_id})
    )

    with pytest.raises(ProofAgentError) as exc:
        store._require_resolved_shared_knowledge_sources_active_unlocked(
            ResolvedKnowledgeBindingSet(
                bindings=(_resolved_hybrid_binding(source_publication_id=binding_publication_id),)
            )
        )

    assert exc.value.code == "PA_CONFIG_002"


def test_hybrid_shared_source_publication_guard_accepts_exact_generic_publication(
    tmp_path: Path,
) -> None:
    authority = InMemoryHybridKnowledgeBindingAuthority()
    store = LocalAgentConfigurationStore(
        tmp_path / "config",
        hybrid_binding_authority=authority,
    )
    source = store.create_knowledge_source(
        source_id="ks_hybrid",
        name="Hybrid Knowledge",
        provider="hybrid_index",
        params={},
        actor="test-user",
    )
    assert source.source_draft_version_id is not None
    _seed_hybrid_binding_authority(
        authority,
        source_draft_version_id=source.source_draft_version_id,
    )
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": "publication_001"})
    )
    store._write_knowledge_source_publication(
        KnowledgeSourcePublicationRecord(
            publication_id="record_001",
            source_id=source.source_id,
            resource_kind="hybrid_publication",
            resource_id="publication_001",
            source_draft_version_id=source.source_draft_version_id,
            validation_id="validation_001",
            change_note="Publish governed Hybrid index.",
            published_at="2026-07-12T00:00:00Z",
            published_by="test-user",
            document_count=1,
            smoke_query="policy",
        )
    )

    store._require_resolved_shared_knowledge_sources_active_unlocked(
        ResolvedKnowledgeBindingSet(bindings=(_resolved_hybrid_binding(),))
    )


def test_hybrid_shared_source_publication_guard_rejects_missing_hybrid_authority(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    source = store.create_knowledge_source(
        source_id="ks_hybrid",
        name="Hybrid Knowledge",
        provider="hybrid_index",
        params={},
        actor="test-user",
    )
    assert source.source_draft_version_id is not None
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": "publication_001"})
    )
    store._write_knowledge_source_publication(
        KnowledgeSourcePublicationRecord(
            publication_id="record_001",
            source_id=source.source_id,
            resource_kind="hybrid_publication",
            resource_id="publication_001",
            source_draft_version_id=source.source_draft_version_id,
            validation_id="validation_001",
            change_note="Publish governed Hybrid index.",
            published_at="2026-07-12T00:00:00Z",
            published_by="test-user",
            document_count=1,
            smoke_query="policy",
        )
    )

    with pytest.raises(ProofAgentError) as exc:
        store._require_resolved_shared_knowledge_sources_active_unlocked(
            ResolvedKnowledgeBindingSet(bindings=(_resolved_hybrid_binding(),))
        )

    assert exc.value.code == "PA_CONFIG_002"
    assert "authority" in exc.value.message


def _publish_package(
    tmp_path: Path,
    manifest_path: Path,
) -> tuple[LocalAgentConfigurationStore, str, str]:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    return store, draft.agent_id, version.version_id


def test_registry_defaults_to_customer_facing_insurance_example_agent() -> None:
    registry = PublishedAgentRegistry()

    resolved = registry.resolve_customer_facing("insurance_customer_service")

    assert resolved is not None
    assert resolved.customer_facing
    assert registry.list_agent_ids() == ("insurance_customer_service",)


def test_registry_can_be_explicitly_configured_empty() -> None:
    registry = PublishedAgentRegistry({})

    assert registry.resolve("insurance_customer_service") is None
    assert registry.list_agent_ids() == ()


def test_published_agent_directory_lists_only_active_published_versions(
    tmp_path: Path,
) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)

    response = client.get("/api/chat/agents")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "agent_id": agent_id,
                "display_name": "enterprise_qa",
                "purpose": "Answer enterprise knowledge questions only when evidence supports the answer.",
                "agent_version_id": version_id,
                "customer_facing": False,
            }
        ],
        "meta": {"total": 1},
    }


def test_customer_agent_directory_lists_only_customer_facing_published_versions(
    tmp_path: Path,
) -> None:
    store, _, _ = _publish_package(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    insurance_draft = import_agent_package(
        Path("examples/insurance_customer_service/agent.yaml"),
        store=store,
        actor="test-user",
    )
    insurance_version = store.publish_version(
        agent_id=insurance_draft.agent_id,
        draft_id=insurance_draft.draft_id,
        validation_run_id="run_validation_customer",
        actor="test-user",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)

    response = client.get("/api/customer/agents")

    assert response.status_code == 200
    assert response.json() == {
        "data": [
            {
                "agent_id": "insurance_customer_service",
                "display_name": "insurance_customer_service",
                "purpose": (
                    "Provide read-only customer service for insurance policy and claim questions "
                    "when evidence or authorized account data supports the answer."
                ),
                "agent_version_id": insurance_version.version_id,
                "customer_facing": True,
            }
        ],
        "meta": {"total": 1},
    }


def test_registry_resolves_active_agent_version_from_configuration_store(
    tmp_path: Path,
) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    registry = PublishedAgentRegistry(agents={}, configuration_store=store)

    resolved = registry.resolve(agent_id)

    assert resolved is not None
    assert resolved.agent_id == agent_id
    assert resolved.agent_version_id == version_id
    assert resolved.manifest_path == (
        store.root_dir / "agents" / agent_id / "versions" / version_id / "agent.yaml"
    )
    assert registry.list_agent_ids() == (agent_id,)


def test_published_agent_version_persists_resolved_knowledge_bindings(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        store=store,
        actor="test-user",
    )
    source = store.create_knowledge_source(
        source_id="ks_policy",
        name="Policies",
        provider="local_index",
        params={
            "ingestion_model": {"provider": "deterministic", "name": "routing"},
            "document_selection_budget": 8,
        },
        actor="test-user",
    )
    snapshot = KnowledgeSourceSnapshotManifest(
        schema_version="local_index.snapshot.v2",
        snapshot_id="kssnapshot_001",
        source_id=source.source_id,
        state="READY",
        validation_level="foundation",
        source_draft_version_id=source.source_draft_version_id or "ksdraft_fixture",
        candidate_digest="digest_001",
        foundation_validation_id="ksvalidation_001",
        documents=(),
        created_at="2026-06-05T00:00:00Z",
        created_by="test-user",
    )
    store._write_knowledge_source_snapshot(snapshot)
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": snapshot.snapshot_id})
    )
    draft = store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        actor="test-user",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: enterprise_qa
purpose: "Answer enterprise knowledge questions only when evidence supports the answer."

workflow:
  runtime: langgraph
  template: enterprise_qa

package_knowledge_sources: []

knowledge_bindings:
  - binding_id: kb_policy
    source_ref:
      scope: shared
      source_id: ks_policy

retrieval:
  strategy: single_step
  top_k: 2
  min_score: 0.2

model:
  provider: deterministic
  name: demo

policy:
  file: ./policy.yaml

capabilities:
  tools:
    enabled: true
    file: ./tools.yaml
  memory:
    enabled: true
    provider: session

audit:
  trace_path: ../../runs/latest/trace.jsonl
  receipt_path: ../../runs/latest/governance_receipt.md
""",
            policy_yaml=draft.contract_bundle.policy_yaml,
            tools_yaml=draft.contract_bundle.tools_yaml,
            extra_files=draft.contract_bundle.extra_files,
            advanced_fields=draft.contract_bundle.advanced_fields,
        ),
    )
    resolved_bindings = ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedKnowledgeBinding(
                binding_id="kb_policy",
                source_scope="shared",
                source_id="ks_policy",
                source_version_id="kssnapshot_001",
                provider="local_index",
                provider_params={
                    "snapshot_path": store.root_dir
                    / "knowledge_sources"
                    / "ks_policy"
                    / "snapshots"
                    / "kssnapshot_001",
                    "artifact_root": store.root_dir,
                    "routing_model": {"provider": "deterministic", "name": "routing"},
                },
            ),
        )
    )

    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
        resolved_knowledge_bindings=resolved_bindings,
    )
    registry = PublishedAgentRegistry(agents={}, configuration_store=store)
    resolved_agent = registry.resolve(draft.agent_id)
    persisted = store.get_version(draft.agent_id, version.version_id)

    assert version.resolved_knowledge_bindings == resolved_bindings
    assert persisted is not None
    assert persisted.resolved_knowledge_bindings is not None
    persisted_binding = persisted.resolved_knowledge_bindings.bindings[0]
    assert persisted_binding.source_version_id == "kssnapshot_001"
    assert Path(persisted_binding.provider_params["snapshot_path"]) == (
        store.root_dir / "knowledge_sources" / "ks_policy" / "snapshots" / "kssnapshot_001"
    )
    assert resolved_agent is not None
    assert resolved_agent.resolved_knowledge_bindings == persisted.resolved_knowledge_bindings


def test_published_agent_version_freezes_hybrid_binding_after_source_advances(
    tmp_path: Path,
) -> None:
    authority = InMemoryHybridKnowledgeBindingAuthority()
    store = LocalAgentConfigurationStore(
        tmp_path / "config",
        hybrid_binding_authority=authority,
    )
    draft = import_agent_package(
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
        store=store,
        actor="test-user",
    )
    source = store.create_knowledge_source(
        source_id="ks_hybrid",
        name="Hybrid Knowledge",
        provider="hybrid_index",
        params={},
        actor="test-user",
    )
    assert source.source_draft_version_id is not None
    _seed_hybrid_binding_authority(
        authority,
        source_draft_version_id=source.source_draft_version_id,
    )
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": "publication_001"})
    )
    store._write_knowledge_source_publication(
        KnowledgeSourcePublicationRecord(
            publication_id="record_001",
            source_id=source.source_id,
            resource_kind="hybrid_publication",
            resource_id="publication_001",
            source_draft_version_id=source.source_draft_version_id,
            validation_id="validation_001",
            change_note="Publish governed Hybrid index.",
            published_at="2026-07-12T00:00:00Z",
            published_by="test-user",
            document_count=1,
            smoke_query="policy",
        )
    )
    raw_agent = yaml.safe_load(draft.contract_bundle.agent_yaml)
    raw_agent["knowledge_bindings"] = [
        {
            "binding_id": "kb_hybrid",
            "source_ref": {"scope": "shared", "source_id": source.source_id},
            "retrieval_profile_revision_id": "profile_001",
        }
    ]
    draft = store.update_draft(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        actor="test-user",
        contract_bundle=ContractBundle(
            agent_yaml=yaml.safe_dump(raw_agent, sort_keys=False),
            policy_yaml=draft.contract_bundle.policy_yaml,
            tools_yaml=draft.contract_bundle.tools_yaml,
            extra_files=draft.contract_bundle.extra_files,
            advanced_fields=draft.contract_bundle.advanced_fields,
        ),
    )
    frozen_bindings = ResolvedKnowledgeBindingSet(bindings=(_resolved_hybrid_binding(),))

    version = store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation_hybrid",
        actor="test-user",
        resolved_knowledge_bindings=frozen_bindings,
    )
    store._write_knowledge_source(
        source.model_copy(update={"published_snapshot_id": "publication_002"})
    )
    resolved_agent = PublishedAgentRegistry(
        agents={},
        configuration_store=store,
    ).resolve(draft.agent_id)

    assert resolved_agent is not None
    assert resolved_agent.agent_version_id == version.version_id
    assert resolved_agent.resolved_knowledge_bindings == frozen_bindings
    persisted = store.get_version(draft.agent_id, version.version_id)
    assert persisted is not None
    assert persisted.resolved_knowledge_bindings == frozen_bindings


def test_chat_production_run_records_resolved_agent_version_id(tmp_path: Path) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": agent_id,
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_purpose"] == "production"
    assert detail.json()["agent_id"] == agent_id
    assert detail.json()["agent_version_id"] == version_id


def test_customer_production_run_records_resolved_agent_version_id(tmp_path: Path) -> None:
    store, agent_id, version_id = _publish_package(
        tmp_path,
        Path("examples/insurance_customer_service/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": agent_id, "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["agent_id"] == agent_id
    assert detail.json()["agent_version_id"] == version_id


def test_customer_conversation_rejects_operator_only_published_agent(tmp_path: Path) -> None:
    store, agent_id, _version_id = _publish_package(
        tmp_path,
        Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml"),
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={},
        agent_configuration_store=store,
    )
    client = TestClient(app)

    response = client.post(
        "/api/customer/conversations",
        json={"agent_id": agent_id, "customer_id": "CUST-001"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "message": f"Customer-facing Published Agent not found: {agent_id}",
        "available_agent_ids": [],
    }


def test_execution_api_still_rejects_arbitrary_manifest_paths(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={
            "enterprise_qa": Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
        },
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "agent_yaml": "proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 422


def test_chat_execution_rejects_example_template_without_publication(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_dir=tmp_path / "config",
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "enterprise_qa",
            "question": "What is the reimbursement rule for travel meals?",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "message": "Published Agent not found: enterprise_qa",
        "available_agent_ids": [],
    }
