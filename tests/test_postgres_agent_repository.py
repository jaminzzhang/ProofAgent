from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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
    AgentPublicationRecord,
    ContractBundle,
    DraftAgent,
    EnvironmentModelCredentialReference,
    PersistenceConflictError,
    PersistenceNotFoundError,
    PersistencePointerConflictError,
    PublishedAgentVersion,
    ResolvedSharedAssetVersions,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)

_AGENT_ID = "agent_management_insurance_specialist"
_DRAFT_ID = "019ba001-1111-7000-8000-000000000101"
_VERSION_ID = "019ba001-1111-7000-8000-000000000102"


def _draft(*, purpose: str = "Answer insurance questions") -> DraftAgent:
    return DraftAgent(
        agent_id=_AGENT_ID,
        draft_id=_DRAFT_ID,
        display_name="Insurance Specialist",
        purpose=purpose,
        contract_bundle=ContractBundle(
            agent_yaml="schema_version: 3\n",
            policy_yaml="rules: []\n",
            tools_yaml="tools: []\n",
        ),
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
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
        repository.get_published(_AGENT_ID, item.version.version_id)
        for item in candidates
    ]
    assert sum(item is not None for item in persisted) == 1


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
            credential_ref=EnvironmentModelCredentialReference(
                type="env", name="MODEL_API_KEY"
            ),
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
            credential_ref=EnvironmentModelCredentialReference(
                type="env", name="MODEL_API_KEY"
            ),
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
