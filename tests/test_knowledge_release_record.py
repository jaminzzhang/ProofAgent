from __future__ import annotations

import pytest

from proof_agent.configuration.knowledge_release import (
    require_knowledge_release_record,
    seal_knowledge_release_record,
)
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    ContractBundle,
    ExactArtifactRef,
    ResolvedHybridKnowledgeBinding,
    ResolvedKnowledgeBindingSet,
)
from proof_agent.errors import ProofAgentError


def _artifact(kind: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://release-evidence/{kind}.json",
        version_id=f"{kind}-v1",
        sha256={
            "shadow": "a",
            "capacity": "b",
            "acceptance": "c",
            "recovery": "d",
        }[kind]
        * 64,
        size_bytes=1024,
        media_type="application/json",
    )


def _bundle() -> ContractBundle:
    return ContractBundle(
        agent_yaml="name: insurance-specialist\n",
        policy_yaml="rules: []\n",
        tools_yaml="tools: []\n",
    )


def _bindings() -> ResolvedKnowledgeBindingSet:
    return ResolvedKnowledgeBindingSet(
        bindings=(
            ResolvedHybridKnowledgeBinding(
                binding_id="kb_hybrid",
                source_id="ks_hybrid",
                source_publication_id="publication-1",
                source_snapshot_id="snapshot-1",
                index_generation_id="generation-1",
                source_publication_seq=1,
                retrieval_profile_revision_id="profile-1",
                manifest_ref=_artifact("shadow"),
                publication_attestation_id="attestation-1",
            ),
        )
    )


def test_release_record_binds_candidate_and_all_four_evidence_artifacts() -> None:
    record = seal_knowledge_release_record(
        record_id="knowledge-release-1",
        contract_bundle=_bundle(),
        resolved_knowledge_bindings=_bindings(),
        shadow_artifact=_artifact("shadow"),
        capacity_artifact=_artifact("capacity"),
        acceptance_artifact=_artifact("acceptance"),
        recovery_artifact=_artifact("recovery"),
        created_at="2026-07-14T00:00:00Z",
        created_by="release-service",
    )

    require_knowledge_release_record(
        record=record,
        contract_bundle=_bundle(),
        resolved_knowledge_bindings=_bindings(),
    )

    assert len(record.candidate_sha256) == 64
    assert len(record.record_sha256) == 64


def test_release_record_rejects_candidate_drift() -> None:
    record = seal_knowledge_release_record(
        record_id="knowledge-release-1",
        contract_bundle=_bundle(),
        resolved_knowledge_bindings=_bindings(),
        shadow_artifact=_artifact("shadow"),
        capacity_artifact=_artifact("capacity"),
        acceptance_artifact=_artifact("acceptance"),
        recovery_artifact=_artifact("recovery"),
        created_at="2026-07-14T00:00:00Z",
        created_by="release-service",
    )
    changed = _bundle().model_copy(update={"policy_yaml": "rules:\n  - effect: deny\n"})

    with pytest.raises(ProofAgentError, match="candidate"):
        require_knowledge_release_record(
            record=record,
            contract_bundle=changed,
            resolved_knowledge_bindings=_bindings(),
        )


def test_hybrid_agent_publication_requires_registered_release_record(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    draft = store.create_draft(
        agent_id="insurance-specialist",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        contract_bundle=ContractBundle(
            agent_yaml="""
name: insurance-specialist
knowledge_bindings:
  - binding_id: kb_hybrid
    source_ref:
      scope: shared
      source_id: ks_hybrid
""",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        actor="author",
    )

    with pytest.raises(ProofAgentError, match="Knowledge Release Record"):
        store.publish_version(
            agent_id=draft.agent_id,
            draft_id=draft.draft_id,
            validation_run_id="validation-1",
            actor="publisher",
            resolved_knowledge_bindings=_bindings(),
        )


def test_release_record_registration_requires_independent_evidence_authority(tmp_path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    record = seal_knowledge_release_record(
        record_id="knowledge-release-1",
        contract_bundle=_bundle(),
        resolved_knowledge_bindings=_bindings(),
        shadow_artifact=_artifact("shadow"),
        capacity_artifact=_artifact("capacity"),
        acceptance_artifact=_artifact("acceptance"),
        recovery_artifact=_artifact("recovery"),
        created_at="2026-07-14T00:00:00Z",
        created_by="release-service",
    )

    with pytest.raises(ProofAgentError, match="evidence authority"):
        store.record_knowledge_release(
            record=record,
            contract_bundle=_bundle(),
            resolved_knowledge_bindings=_bindings(),
        )
