from __future__ import annotations

from types import TracebackType
from typing import Literal

import pytest
from pydantic import ValidationError

from proof_agent.configuration.knowledge_release import (
    knowledge_release_candidate_sha256,
)
from proof_agent.contracts import (
    AgentDraftRecord,
    ContractBundle,
    DraftAgent,
    DraftKnowledgeReleaseBindingCandidate,
    FormalProductionAgentCandidate,
    PostgresEncryptedModelCredentialReference,
    ProductionKssBindingProfile,
    ProductionSecretHandle,
    SecretPurpose,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)
from proof_agent.contracts.knowledge_service_management import (
    KnowledgeServiceManagementWorkspace,
    KnowledgeServiceReadinessProjection,
    KnowledgeServiceReleaseProjection,
)
from proof_agent.control.formal_production_agent_candidate import (
    FormalProductionAgentCandidateAssembler,
    FormalProductionAgentCandidateRejected,
    FormalProductionKnowledgeReleaseCatalog,
)
from proof_agent.control.production_agent_publication_configuration import (
    ProductionAgentPublicationConfigurationProjector,
)


class _DraftRepository:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.record = record

    def get_draft(self, agent_id: str, draft_id: str) -> AgentDraftRecord | None:
        if self.record is None:
            return None
        if self.record.draft.agent_id != agent_id or self.record.draft.draft_id != draft_id:
            return None
        return self.record


class _ReadOnlyUnitOfWork:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.agents = _DraftRepository(record)
        self.committed = False

    def __enter__(self) -> _ReadOnlyUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    def commit(self) -> None:
        self.committed = True


class _UnitOfWorkFactory:
    def __init__(self, record: AgentDraftRecord | None) -> None:
        self.record = record
        self.units: list[_ReadOnlyUnitOfWork] = []

    def __call__(self) -> _ReadOnlyUnitOfWork:
        unit = _ReadOnlyUnitOfWork(self.record)
        self.units.append(unit)
        return unit


class _Catalog:
    def __init__(self, workspace: KnowledgeServiceManagementWorkspace) -> None:
        self._workspace = workspace

    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        return self._workspace


class _UnavailableCatalog:
    def workspace(self) -> KnowledgeServiceManagementWorkspace:
        raise RuntimeError("private upstream failure")


class _ModelConnections:
    def __init__(self, connection: SharedModelConnection) -> None:
        self._connection = connection

    def get_model_connection(self, connection_id: str) -> SharedModelConnection | None:
        if connection_id == self._connection.connection_id:
            return self._connection
        return None


def test_assembler_roots_candidate_in_exact_draft_revision_and_draft_release() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    uow_factory = _UnitOfWorkFactory(record)
    assembler = FormalProductionAgentCandidateAssembler(
        unit_of_work_factory=uow_factory,
        knowledge_release_catalog=_Catalog(_catalog()),
        publication_configuration_projector=ProductionAgentPublicationConfigurationProjector(
            configuration_store=_ModelConnections(_model_connection())
        ),
    )

    assembled = assembler.assemble(
        agent_id=record.draft.agent_id,
        draft_id=record.draft.draft_id,
        draft_revision=record.revision,
        binding_profile=_binding_profile(),
    )

    assert assembled.agent_id == record.draft.agent_id
    assert assembled.draft_id == record.draft.draft_id
    assert assembled.draft_revision == 11
    assert assembled.contract_bundle == record.draft.contract_bundle
    assert assembled.knowledge_release_candidate == _candidate()
    assert assembled.knowledge_service_catalog_revision == "kss-catalog-42"
    assert len(assembled.resolved_knowledge_bindings.bindings) == 1
    binding = assembled.resolved_knowledge_bindings.bindings[0]
    assert binding.knowledge_base_release_id == _candidate().knowledge_base_release_id
    assert binding.binding_id == _binding_profile().binding_id
    assert binding.client_credential_ref == _binding_profile().client_credential_ref
    assert binding.admission_scorer_id == _binding_profile().admission_scorer_id
    assert binding.admission_scorer_revision == _binding_profile().admission_scorer_revision
    assert assembled.knowledge_release_candidate_sha256 == (
        knowledge_release_candidate_sha256(
            assembled.contract_bundle,
            assembled.resolved_knowledge_bindings,
        )
    )
    assert len(assembled.formal_candidate_sha256) == 64
    assert all(not unit.committed for unit in uow_factory.units)


def test_assembler_rejects_a_stale_draft_revision_before_reading_kss() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=12)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_UnavailableCatalog(),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=11,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_draft_revision_conflict"
    assert "private upstream failure" not in str(raised.value)


def test_assembler_rejects_a_missing_named_draft() -> None:
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(None),
        catalog=_Catalog(_catalog()),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id="agent_management_insurance_specialist",
            draft_id="019ba001-1111-7000-8000-000000000701",
            draft_revision=11,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_draft_not_found"


def test_assembler_revalidates_the_full_release_tuple_as_queryable() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog(release_state="deprecated")),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_authoring_blocked"
    assert raised.value.blocker_codes == ("knowledge_release_not_queryable",)


def test_assembler_rejects_a_queryable_release_with_a_foreign_parent_tuple() -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog(release_base_version_id="foreign-base-version")),
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_authoring_blocked"
    assert raised.value.blocker_codes == ("knowledge_release_not_queryable",)


@pytest.mark.parametrize(
    "catalog_kind",
    ["raises", "unavailable", "unversioned"],
)
def test_assembler_rejects_an_unavailable_or_unversioned_live_catalog(
    catalog_kind: str,
) -> None:
    record = AgentDraftRecord(draft=_draft(), revision=11)
    catalogs: dict[str, FormalProductionKnowledgeReleaseCatalog] = {
        "raises": _UnavailableCatalog(),
        "unavailable": _Catalog(_catalog(readiness_state="unavailable")),
        "unversioned": _Catalog(_catalog(catalog_revision=None)),
    }
    assembler = _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=catalogs[catalog_kind],
    )

    with pytest.raises(FormalProductionAgentCandidateRejected) as raised:
        assembler.assemble(
            agent_id=record.draft.agent_id,
            draft_id=record.draft.draft_id,
            draft_revision=record.revision,
            binding_profile=_binding_profile(),
        )

    assert raised.value.code == "formal_candidate_catalog_unavailable"
    assert "private upstream failure" not in str(raised.value)


def test_binding_profile_cannot_select_a_release_or_use_an_unversioned_secret() -> None:
    payload = _binding_profile().model_dump(mode="python")
    payload["knowledge_base_release_id"] = "environment-selected-release"

    with pytest.raises(ValidationError, match="knowledge_base_release_id"):
        ProductionKssBindingProfile.model_validate(payload)

    unversioned_payload = _binding_profile().model_dump(mode="python")
    unversioned_payload["client_credential_ref"] = ProductionSecretHandle(
        protocol_id="vault-kv-v2",
        handle_id="proofagent/kss/client",
        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
        version_id=None,
    )
    with pytest.raises(ValidationError, match="versioned credential"):
        ProductionKssBindingProfile.model_validate(unversioned_payload)

    wrong_purpose_payload = _binding_profile().model_dump(mode="python")
    wrong_purpose_payload["client_credential_ref"] = ProductionSecretHandle(
        protocol_id="vault-kv-v2",
        handle_id="proofagent/kss/client",
        purpose=SecretPurpose.MODEL_CREDENTIAL,
        version_id="secret-version-7",
    )
    with pytest.raises(ValidationError, match="Knowledge credential"):
        ProductionKssBindingProfile.model_validate(wrong_purpose_payload)


def test_formal_candidate_digest_changes_when_the_exact_revision_changes() -> None:
    first_record = AgentDraftRecord(draft=_draft(), revision=11)
    second_record = AgentDraftRecord(draft=_draft(), revision=12)

    first = _assemble(first_record)
    second = _assemble(second_record)

    assert first.knowledge_release_candidate_sha256 == (second.knowledge_release_candidate_sha256)
    assert first.formal_candidate_sha256 != second.formal_candidate_sha256


def _assemble(record: AgentDraftRecord) -> FormalProductionAgentCandidate:
    return _assembler(
        uow_factory=_UnitOfWorkFactory(record),
        catalog=_Catalog(_catalog()),
    ).assemble(
        agent_id=record.draft.agent_id,
        draft_id=record.draft.draft_id,
        draft_revision=record.revision,
        binding_profile=_binding_profile(),
    )


def _assembler(
    *,
    uow_factory: _UnitOfWorkFactory,
    catalog: FormalProductionKnowledgeReleaseCatalog,
) -> FormalProductionAgentCandidateAssembler:
    return FormalProductionAgentCandidateAssembler(
        unit_of_work_factory=uow_factory,
        knowledge_release_catalog=catalog,
        publication_configuration_projector=ProductionAgentPublicationConfigurationProjector(
            configuration_store=_ModelConnections(_model_connection())
        ),
    )


def _draft() -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="019ba001-1111-7000-8000-000000000701",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions.",
        contract_bundle=ContractBundle(
            agent_yaml=_ready_agent_yaml(),
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        knowledge_release_binding_candidate=_candidate(),
        created_at="2026-08-12T00:00:00Z",
        updated_at="2026-08-30T00:00:00Z",
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


def _catalog(
    *,
    release_state: Literal["queryable", "deprecated", "retired", "revoked"] = "queryable",
    readiness_state: Literal["ready", "unavailable"] = "ready",
    catalog_revision: str | None = "kss-catalog-42",
    release_base_version_id: str | None = None,
) -> KnowledgeServiceManagementWorkspace:
    release_payload = _candidate().model_dump(mode="python")
    if release_base_version_id is not None:
        release_payload["knowledge_base_version_id"] = release_base_version_id
    return KnowledgeServiceManagementWorkspace(
        readiness=KnowledgeServiceReadinessProjection(
            state=readiness_state,
            revision=catalog_revision,
        ),
        spaces=(),
        sources=(),
        bases=(),
        source_versions=(),
        releases=(
            KnowledgeServiceReleaseProjection(
                **release_payload,
                source_version_count=3,
                state=release_state,
            ),
        ),
    )


def _binding_profile() -> ProductionKssBindingProfile:
    return ProductionKssBindingProfile(
        binding_id="production-kss-insurance",
        client_credential_ref=ProductionSecretHandle(
            protocol_id="vault-kv-v2",
            handle_id="proofagent/kss/client",
            purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
            version_id="secret-version-7",
        ),
        admission_scorer_id="proofagent-admission-scorer",
        admission_scorer_revision="scorer-v4",
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
