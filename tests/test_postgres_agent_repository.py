from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.contracts import (
    ActiveAgentPointerExpectation,
    ActiveAgentVersion,
    AgentActivationRecord,
    AgentPublicationRecord,
    ConfigurationOperation,
    ConfigurationOperationAudit,
    ContractBundle,
    DraftAgent,
    EnvironmentModelCredentialReference,
    ExactArtifactRef,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentPhaseFRecord,
    FormalProductionAgentPublicationEvidence,
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
    ProductionSecretHandle,
    PublishedAgentVersion,
    ReceiptOutcome,
    RegisteredProductionAgentReleaseReference,
    ResolvedKnowledgeBindingSet,
    ResolvedKnowledgeSourceServiceBinding,
    ResolvedSharedAssetVersions,
    SecretPurpose,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

_AGENT_ID = "agent_management_insurance_specialist"
_DRAFT_ID = "019ba001-1111-7000-8000-000000000101"
_VERSION_ID = "019ba001-1111-7000-8000-000000000102"


def _draft(
    *,
    purpose: str = "Answer insurance questions",
    agent_id: str = _AGENT_ID,
    draft_id: str = _DRAFT_ID,
    updated_at: str = "2026-07-15T00:00:00Z",
) -> DraftAgent:
    return DraftAgent(
        agent_id=agent_id,
        draft_id=draft_id,
        display_name="Insurance Specialist",
        purpose=purpose,
        contract_bundle=ContractBundle(
            agent_yaml="schema_version: 3\n",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        created_at="2026-07-15T00:00:00Z",
        updated_at=updated_at,
        created_by="operator-1",
        updated_by="operator-1",
    )


def _publication(
    draft: DraftAgent,
    *,
    draft_revision: int,
    version_id: str = _VERSION_ID,
) -> AgentPublicationRecord:
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id=version_id,
        source_draft_id=draft.draft_id,
        validation_run_id="019ba001-1111-7000-8000-000000000103",
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at="2026-07-15T00:01:00Z",
        published_by="operator-1",
    )
    return AgentPublicationRecord(
        version=version,
        activation=ActiveAgentVersion(
            agent_id=draft.agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by=version.published_by,
        ),
        draft_revision=draft_revision,
    )


def _formal_publication(
    draft: DraftAgent,
    *,
    draft_revision: int,
) -> AgentPublicationRecord:
    validation_run_id = "019ba001-1111-7000-8000-000000000103"
    phase_f_record = FormalProductionAgentPhaseFRecord(
        record_id="019ba001-1111-7000-8000-000000000106",
        provisional_version_id=_VERSION_ID,
        validation_run_id=validation_run_id,
        formal_candidate_sha256="1" * 64,
        knowledge_release_candidate_sha256="2" * 64,
        evidence={
            "shadow": _artifact("shadow", "3"),
            "capacity": _artifact("capacity", "4"),
            "acceptance": _artifact("acceptance", "5"),
            "recovery": _artifact("recovery", "6"),
        },
        created_at="2026-07-15T00:00:30Z",
        created_by="operator-1",
        record_sha256="7" * 64,
    )
    reference = RegisteredProductionAgentReleaseReference(
        knowledge_space_id="insurance",
        knowledge_base_id="insurance-guidance",
        knowledge_base_release_id="release-insurance-v3",
        external_resource_id=_VERSION_ID,
        release_reference_id="019ba001-1111-7000-8000-000000000107",
        authenticated_client_id="proof-agent-production",
        registered_at=datetime(2026, 7, 15, 0, 0, 40, tzinfo=UTC),
    )
    smoke_result = FormalProductionAgentOnlineSmokeResult(
        agent_id=draft.agent_id,
        provisional_version_id=_VERSION_ID,
        validation_run_id=validation_run_id,
        release_reference_id=reference.release_reference_id,
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        accepted_citation_count=2,
        trace_ref=_artifact("trace", "8"),
        receipt_ref=_artifact("receipt", "9"),
    )
    formal_evidence = FormalProductionAgentPublicationEvidence(
        source_draft_revision=draft_revision,
        phase_f_record=phase_f_record,
        release_reference=reference,
        online_smoke_result=smoke_result,
    )
    operation = ConfigurationOperationAudit(
        operation_id="019ba001-1111-7000-8000-000000000108",
        operation=ConfigurationOperation.PUBLISHED,
        actor="operator-1",
        created_at="2026-07-15T00:01:00Z",
    )
    version = PublishedAgentVersion(
        agent_id=draft.agent_id,
        version_id=_VERSION_ID,
        source_draft_id=draft.draft_id,
        validation_run_id=validation_run_id,
        display_name=draft.display_name,
        purpose=draft.purpose,
        contract_bundle=draft.contract_bundle,
        published_at="2026-07-15T00:01:00Z",
        published_by="operator-1",
        operation_audit=(operation,),
        resolved_knowledge_bindings=ResolvedKnowledgeBindingSet(
            bindings=(
                ResolvedKnowledgeSourceServiceBinding(
                    binding_id="production-kss-insurance",
                    knowledge_base_release_id=reference.knowledge_base_release_id,
                    client_credential_ref=ProductionSecretHandle(
                        protocol_id="vault-kv-v2",
                        handle_id="proofagent/kss/client",
                        purpose=SecretPurpose.KNOWLEDGE_CREDENTIAL,
                        version_id="secret-version-7",
                    ),
                    admission_scorer_id="proofagent-admission-scorer",
                    admission_scorer_revision="scorer-v4",
                ),
            )
        ),
        formal_production_evidence=formal_evidence,
    )
    return AgentPublicationRecord(
        version=version,
        activation=ActiveAgentVersion(
            agent_id=version.agent_id,
            version_id=version.version_id,
            activated_at=version.published_at,
            activated_by=version.published_by,
        ),
        draft_revision=draft_revision,
        active_pointer_expectation=ActiveAgentPointerExpectation(version_id=None),
    )


def _artifact(kind: str, digest_character: str) -> ExactArtifactRef:
    return ExactArtifactRef(
        artifact_uri=f"s3://proof-agent/formal-publication/{kind}.json",
        version_id=f"opaque-{kind}",
        sha256=digest_character * 64,
        size_bytes=128,
        media_type="application/json",
    )


def _publish_second_version(
    repository: PostgresAgentLifecycleRepository,
) -> AgentPublicationRecord:
    draft_value = _draft(
        purpose="Second version",
        draft_id="019ba001-1111-7000-8000-000000000104",
        updated_at="2026-07-15T00:02:00Z",
    )
    draft = repository.save_draft(draft_value, expected_revision=0)
    publication = _publication(
        draft.draft,
        draft_revision=draft.revision,
        version_id="019ba001-1111-7000-8000-000000000105",
    )
    return repository.publish_version(
        publication,
        expected_draft_revision=draft.revision,
    )


def test_postgres_agent_repository_conditionally_saves_draft(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)

    first = repository.save_draft(_draft(), expected_revision=0)
    second = repository.save_draft(
        _draft(purpose="Updated purpose"),
        expected_revision=first.revision,
    )

    assert UUID(first.draft.draft_id).version == 7
    assert first.revision == 1
    assert second.revision == 2
    assert repository.get_draft(_AGENT_ID, _DRAFT_ID) == second
    with pytest.raises(PersistenceConflictError):
        repository.save_draft(_draft(purpose="stale"), expected_revision=1)


def test_postgres_agent_repository_lists_revisioned_drafts_latest_first(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    older = repository.save_draft(_draft(), expected_revision=0)
    newer = repository.save_draft(
        _draft(
            draft_id="019ba001-1111-7000-8000-000000000104",
            updated_at="2026-07-15T00:01:00Z",
        ),
        expected_revision=0,
    )
    repository.save_draft(
        _draft(
            agent_id="another-agent",
            draft_id="019ba001-1111-7000-8000-000000000105",
            updated_at="2026-07-15T00:02:00Z",
        ),
        expected_revision=0,
    )

    assert repository.list_drafts(_AGENT_ID) == (newer, older)
    assert len(repository.list_drafts()) == 3


def test_postgres_agent_repository_atomically_publishes_immutable_version(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    draft = repository.save_draft(_draft(), expected_revision=0)
    publication = _publication(draft.draft, draft_revision=draft.revision)

    saved = repository.publish_version(
        publication,
        expected_draft_revision=draft.revision,
    )
    repository.save_draft(
        _draft(purpose="Changed after publication"),
        expected_revision=draft.revision,
    )

    assert saved == publication
    assert repository.get_published(_AGENT_ID, _VERSION_ID) == publication.version
    assert repository.list_published(_AGENT_ID) == (publication.version,)
    assert repository.get_active(_AGENT_ID) == publication.activation
    persisted = repository.get_published(_AGENT_ID, _VERSION_ID)
    assert persisted is not None
    assert persisted.purpose == draft.draft.purpose


def test_postgres_agent_repository_round_trips_formal_publication_evidence(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    draft = repository.save_draft(_draft(), expected_revision=0)
    publication = _formal_publication(draft.draft, draft_revision=draft.revision)

    repository.publish_version(
        publication,
        expected_draft_revision=draft.revision,
    )

    assert repository.get_published(_AGENT_ID, _VERSION_ID) == publication.version
    assert repository.get_active(_AGENT_ID) == publication.activation


def test_postgres_agent_repository_allows_only_one_concurrent_revision_winner(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    repository.save_draft(_draft(), expected_revision=0)
    barrier = Barrier(2)

    def update(purpose: str) -> str:
        barrier.wait(timeout=5)
        try:
            repository.save_draft(_draft(purpose=purpose), expected_revision=1)
        except PersistenceConflictError:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(update, ("Concurrent A", "Concurrent B")))

    assert sorted(results) == ["conflict", "saved"]
    persisted = repository.get_draft(_AGENT_ID, _DRAFT_ID)
    assert persisted is not None
    assert persisted.revision == 2
    assert persisted.draft.purpose in {"Concurrent A", "Concurrent B"}


def test_postgres_agent_publication_allows_only_one_active_pointer_cas_winner(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    base_draft = repository.save_draft(_draft(), expected_revision=0)
    base = _publication(base_draft.draft, draft_revision=base_draft.revision)
    repository.publish_version(base, expected_draft_revision=base_draft.revision)

    candidates = []
    for suffix in ("201", "202"):
        draft_value = _draft(purpose=f"Concurrent candidate {suffix}").model_copy(
            update={
                "draft_id": f"019ba001-1111-7000-8000-000000000{suffix}",
            }
        )
        draft = repository.save_draft(draft_value, expected_revision=0)
        candidate = _publication(
            draft.draft,
            draft_revision=draft.revision,
            version_id=f"019ba001-1111-7000-8000-0000000003{suffix[-2:]}",
        ).model_copy(
            update={
                "active_pointer_expectation": ActiveAgentPointerExpectation(
                    version_id=base.version.version_id
                )
            }
        )
        candidates.append(candidate)

    barrier = Barrier(2)

    def publish(candidate: AgentPublicationRecord) -> str:
        barrier.wait(timeout=5)
        try:
            repository.publish_version(
                candidate,
                expected_draft_revision=candidate.draft_revision,
            )
        except PersistencePointerConflictError:
            return "conflict"
        return "published"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(publish, candidates))

    assert sorted(results) == ["conflict", "published"]
    active = repository.get_active(_AGENT_ID)
    assert active is not None
    assert active.version_id in {item.version.version_id for item in candidates}
    persisted = [
        repository.get_published(_AGENT_ID, item.version.version_id) for item in candidates
    ]
    assert sum(item is not None for item in persisted) == 1


def test_postgres_agent_repository_rolls_back_with_exact_active_pointer_cas(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    draft = repository.save_draft(_draft(), expected_revision=0)
    first = _publication(draft.draft, draft_revision=draft.revision)
    repository.publish_version(first, expected_draft_revision=draft.revision)
    second = _publish_second_version(repository)
    rollback = AgentActivationRecord(
        activation=ActiveAgentVersion(
            agent_id=_AGENT_ID,
            version_id=first.version.version_id,
            activated_at="2026-07-15T00:03:00Z",
            activated_by="operator-2",
            rollback_from_version_id=second.version.version_id,
        ),
        active_pointer_expectation=ActiveAgentPointerExpectation(
            version_id=second.version.version_id
        ),
    )

    assert repository.activate_version(rollback) == rollback
    assert repository.get_active(_AGENT_ID) == rollback.activation
    assert repository.get_published(_AGENT_ID, first.version.version_id) == (first.version)
    assert repository.get_published(_AGENT_ID, second.version.version_id) == (second.version)

    with pytest.raises(PersistencePointerConflictError):
        repository.activate_version(
            rollback.model_copy(
                update={
                    "activation": rollback.activation.model_copy(
                        update={
                            "version_id": second.version.version_id,
                            "rollback_from_version_id": second.version.version_id,
                        }
                    )
                }
            )
        )

    missing = AgentActivationRecord(
        activation=ActiveAgentVersion(
            agent_id=_AGENT_ID,
            version_id="019ba001-1111-7000-8000-000000000199",
            activated_at="2026-07-15T00:04:00Z",
            activated_by="operator-2",
            rollback_from_version_id=first.version.version_id,
        ),
        active_pointer_expectation=ActiveAgentPointerExpectation(
            version_id=first.version.version_id
        ),
    )
    with pytest.raises(PersistenceNotFoundError):
        repository.activate_version(missing)

    assert repository.get_active(_AGENT_ID) == rollback.activation


def test_postgres_agent_rollback_allows_only_one_pointer_cas_winner(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAgentLifecycleRepository(postgres_engine)
    draft = repository.save_draft(_draft(), expected_revision=0)
    first = _publication(draft.draft, draft_revision=draft.revision)
    repository.publish_version(first, expected_draft_revision=draft.revision)
    second = _publish_second_version(repository)
    rollback = AgentActivationRecord(
        activation=ActiveAgentVersion(
            agent_id=_AGENT_ID,
            version_id=first.version.version_id,
            activated_at="2026-07-15T00:03:00Z",
            activated_by="operator-2",
            rollback_from_version_id=second.version.version_id,
        ),
        active_pointer_expectation=ActiveAgentPointerExpectation(
            version_id=second.version.version_id
        ),
    )
    barrier = Barrier(2)

    def activate(_: int) -> str:
        barrier.wait(timeout=5)
        try:
            repository.activate_version(rollback)
        except PersistencePointerConflictError:
            return "conflict"
        return "activated"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(activate, range(2)))

    assert sorted(results) == ["activated", "conflict"]
    assert repository.get_active(_AGENT_ID) == rollback.activation


def test_postgres_agent_publication_freezes_only_existing_exact_shared_versions(
    postgres_engine: Engine,
) -> None:
    agents = PostgresAgentLifecycleRepository(postgres_engine)
    models = PostgresModelAssetRepository(postgres_engine)
    model_ref = models.save_connection(
        SharedModelConnection(
            connection_id="answer-model",
            display_name="Answer Model",
            provider="openai",
            model_identifier="gpt-test",
            credential_ref=EnvironmentModelCredentialReference(type="env", name="MODEL_API_KEY"),
            lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
            created_at="2026-07-15T00:00:00Z",
            updated_at="2026-07-15T00:00:00Z",
        ),
        expected_revision=0,
    )
    draft = agents.save_draft(_draft(), expected_revision=0)
    publication = _publication(draft.draft, draft_revision=1)
    publication = publication.model_copy(
        update={
            "version": publication.version.model_copy(
                update={
                    "resolved_shared_asset_versions": ResolvedSharedAssetVersions(
                        versions=(model_ref,)
                    )
                }
            )
        }
    )

    agents.publish_version(publication, expected_draft_revision=1)

    assert agents.get_published(_AGENT_ID, _VERSION_ID) == publication.version


def test_postgres_agent_publication_rolls_back_on_missing_shared_version(
    postgres_engine: Engine,
) -> None:
    agents = PostgresAgentLifecycleRepository(postgres_engine)
    models = PostgresModelAssetRepository(postgres_engine)
    model_ref = models.save_connection(
        SharedModelConnection(
            connection_id="answer-model",
            display_name="Answer Model",
            provider="openai",
            model_identifier="gpt-test",
            credential_ref=EnvironmentModelCredentialReference(type="env", name="MODEL_API_KEY"),
            lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
            created_at="2026-07-15T00:00:00Z",
            updated_at="2026-07-15T00:00:00Z",
        ),
        expected_revision=0,
    )
    missing_ref = model_ref.model_copy(
        update={"version_id": "019ba001-1111-7000-8000-000000000199"}
    )
    draft = agents.save_draft(_draft(), expected_revision=0)
    publication = _publication(draft.draft, draft_revision=1)
    publication = publication.model_copy(
        update={
            "version": publication.version.model_copy(
                update={
                    "resolved_shared_asset_versions": ResolvedSharedAssetVersions(
                        versions=(missing_ref,)
                    )
                }
            )
        }
    )

    with pytest.raises(PersistenceNotFoundError):
        agents.publish_version(publication, expected_draft_revision=1)

    assert agents.get_published(_AGENT_ID, _VERSION_ID) is None
    assert agents.get_active(_AGENT_ID) is None
