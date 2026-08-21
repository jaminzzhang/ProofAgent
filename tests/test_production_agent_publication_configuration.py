from __future__ import annotations

from proof_agent.contracts import (
    ContractBundle,
    DraftKnowledgeReleaseBindingCandidate,
    DraftAgent,
    PostgresEncryptedModelCredentialReference,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfigurationProjector,
)


class ModelConnections:
    def __init__(self, connections: tuple[SharedModelConnection, ...]) -> None:
        self._connections = {item.connection_id: item for item in connections}

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        return self._connections.get(connection_id)


def test_projector_reports_complete_authoring_snapshot_without_claiming_formal_binding() -> None:
    projector = ProductionAgentPublicationConfigurationProjector(
        configuration_store=ModelConnections((_model_connection(),))
    )

    projection = projector.project(
        draft=_draft(candidate=_candidate()),
        revision=11,
        catalog=_catalog(),
    )

    assert projection.draft_revision == 11
    assert projection.authoring_configuration_state == "ready"
    assert projection.formal_publication_state == "workspace_draft_not_bound"
    assert projection.can_publish_from_dashboard is False
    assert projection.workflow_template == "react_enterprise_qa_v3"
    assert projection.workflow_template_descriptor_version == "react_enterprise_qa.v3"
    assert projection.knowledge_release_candidate == _candidate()
    assert projection.knowledge_release_queryable is True
    assert [item.role for item in projection.model_roles] == [
        "final_answer",
        "react_planner",
        "harness_review",
    ]
    assert all(item.connection_id == "model_deepseek" for item in projection.model_roles)
    assert all(item.lifecycle_state == "ACTIVE" for item in projection.model_roles)
    assert projection.configuration_blockers == ()
    assert projection.phase_f_evidence_requirements == (
        "shadow",
        "capacity",
        "acceptance",
        "recovery",
    )
    assert projection.online_smoke_required is True
    assert projection.activation_mode == "postgres_atomic_cas"


def test_projector_fails_closed_on_incomplete_or_inadmissible_draft_inputs() -> None:
    projector = ProductionAgentPublicationConfigurationProjector(
        configuration_store=ModelConnections(())
    )

    projection = projector.project(
        draft=_draft(
            candidate=None,
            agent_yaml=(
                "name: agent_management_insurance_specialist\n"
                "purpose: Test.\n"
                "workflow:\n"
                "  template: unsupported_workflow\n"
                "model:\n"
                "  provider: deterministic\n"
                "  name: answer\n"
                "react:\n"
                "  planner:\n"
                "    model_source: shared\n"
                "    connection_id: missing-model\n"
                "review:\n"
                "  subagent:\n"
                "    model_source: shared\n"
                "    connection_id: missing-model\n"
                "    fail_closed: false\n"
                "package_knowledge_sources:\n"
                "  - source_id: local\n"
                "knowledge_bindings:\n"
                "  - binding_id: legacy\n"
                "capabilities:\n"
                "  tools:\n"
                "    enabled: true\n"
                "  memory:\n"
                "    enabled: true\n"
            ),
        ),
        revision=4,
        catalog=_catalog(state="unavailable"),
    )

    assert projection.authoring_configuration_state == "blocked"
    assert projection.formal_publication_state == "workspace_draft_not_bound"
    assert {item.code for item in projection.configuration_blockers} == {
        "workflow_not_production_admissible",
        "package_knowledge_not_allowed",
        "legacy_knowledge_binding_not_allowed",
        "knowledge_release_candidate_required",
        "kss_catalog_not_ready",
        "shared_model_connection_required",
        "shared_model_connection_missing",
        "review_must_fail_closed",
        "tools_must_be_disabled",
        "memory_must_be_disabled",
    }


def test_projector_blocks_inline_model_credential_markers_without_echoing_values() -> None:
    projector = ProductionAgentPublicationConfigurationProjector(
        configuration_store=ModelConnections((_model_connection(),))
    )
    agent_yaml = _ready_agent_yaml().replace(
        "  connection_id: model_deepseek\n",
        (
            "  connection_id: model_deepseek\n"
            "  credential_ref:\n"
            "    type: env\n"
            "    name: /private/inline-secret\n"
            "  params:\n"
            "    api_key_env: INLINE_SECRET\n"
        ),
        1,
    )

    projection = projector.project(
        draft=_draft(candidate=_candidate(), agent_yaml=agent_yaml),
        revision=11,
        catalog=_catalog(),
    )

    assert projection.authoring_configuration_state == "blocked"
    assert "inline_model_credentials_not_allowed" in {
        item.code for item in projection.configuration_blockers
    }
    assert projection.model_roles[0].configuration_state == "blocked"
    messages = " ".join(item.message for item in projection.configuration_blockers)
    assert "/private/inline-secret" not in messages
    assert "INLINE_SECRET" not in messages


def test_projector_blocks_contract_identity_that_does_not_match_the_draft() -> None:
    projector = ProductionAgentPublicationConfigurationProjector(
        configuration_store=ModelConnections((_model_connection(),))
    )

    projection = projector.project(
        draft=_draft(
            candidate=_candidate(),
            agent_yaml=_ready_agent_yaml().replace(
                "name: agent_management_insurance_specialist",
                "name: different_agent",
                1,
            ),
        ),
        revision=11,
        catalog=_catalog(),
    )

    assert projection.authoring_configuration_state == "blocked"
    assert "agent_identity_mismatch" in {
        item.code for item in projection.configuration_blockers
    }


def _draft(
    *,
    candidate: DraftKnowledgeReleaseBindingCandidate | None,
    agent_yaml: str | None = None,
) -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="019ba001-1111-7000-8000-000000000701",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        contract_bundle=ContractBundle(
            agent_yaml=agent_yaml or _ready_agent_yaml(),
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        knowledge_release_binding_candidate=candidate,
        created_at="2026-08-12T00:00:00Z",
        updated_at="2026-08-22T00:00:00Z",
        created_by="operator-1",
        updated_by="operator-1",
    )


def _ready_agent_yaml() -> str:
    return (
        "name: agent_management_insurance_specialist\n"
        "purpose: Test.\n"
        "workflow:\n"
        "  template: react_enterprise_qa_v3\n"
        "  template_descriptor_version: react_enterprise_qa.v3\n"
        "model:\n"
        "  model_source: shared\n"
        "  connection_id: model_deepseek\n"
        "react:\n"
        "  planner:\n"
        "    model_source: shared\n"
        "    connection_id: model_deepseek\n"
        "review:\n"
        "  subagent:\n"
        "    model_source: shared\n"
        "    connection_id: model_deepseek\n"
        "    fail_closed: true\n"
        "package_knowledge_sources: []\n"
        "knowledge_bindings: []\n"
        "capabilities:\n"
        "  tools:\n"
        "    enabled: false\n"
        "  memory:\n"
        "    enabled: false\n"
    )


def _candidate() -> DraftKnowledgeReleaseBindingCandidate:
    return DraftKnowledgeReleaseBindingCandidate(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_version_id="insurance-guidance-v3",
        knowledge_base_release_id="release-a4b70851cb914862000e15c3",
    )


def _catalog(*, state: str = "ready") -> KnowledgeServiceManagementWorkspace:
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state=state,
            revision="kss-release-2026-08-22",
        ),
        spaces=(),
        sources=(),
        bases=(),
        source_versions=(),
        releases=(
            KnowledgeServiceReleaseProjection(
                **_candidate().model_dump(mode="python"),
                source_version_count=3,
                state="queryable",
            ),
        ),
    )


def _model_connection() -> SharedModelConnection:
    return SharedModelConnection(
        connection_id="model_deepseek",
        display_name="DeepSeek",
        provider="deepseek",
        model_identifier="deepseek-chat",
        credential_ref=PostgresEncryptedModelCredentialReference(),
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at="2026-08-20T00:00:00Z",
        updated_at="2026-08-20T00:00:00Z",
    )
