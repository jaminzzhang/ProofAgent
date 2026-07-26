from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.schema import (
    agent_drafts,
    agent_version_shared_asset_refs,
    agent_versions,
    knowledge_sources,
)
from proof_agent.capabilities.persistence.postgres.tool_repository import (
    PostgresToolAssetRepository,
)
from proof_agent.contracts import (
    EnvironmentModelCredentialReference,
    KnowledgeSource,
    KnowledgeSourceLifecycleState,
    PersistenceConflictError,
    SharedAssetKind,
    SharedModelConnection,
    SharedModelConnectionLifecycleState,
    ToolSource,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _model_connection(*, model_identifier: str = "model-v1") -> SharedModelConnection:
    return SharedModelConnection(
        connection_id="answer-model",
        display_name="Answer Model",
        provider="openai",
        model_identifier=model_identifier,
        credential_ref=EnvironmentModelCredentialReference(type="env", name="MODEL_API_KEY"),
        lifecycle_state=SharedModelConnectionLifecycleState.ACTIVE,
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )


def test_postgres_model_repository_keeps_immutable_versions(
    postgres_engine: Engine,
) -> None:
    repository = PostgresModelAssetRepository(postgres_engine)
    first = repository.save_connection(_model_connection(), expected_revision=0)
    updated_connection = _model_connection(model_identifier="model-v2").model_copy(
        update={"updated_at": "2026-07-15T00:01:00Z"}
    )
    second = repository.save_connection(updated_connection, expected_revision=1)

    assert first.kind is SharedAssetKind.MODEL_CONNECTION
    assert first.revision == 1
    assert second.revision == 2
    assert repository.get_model_connection("answer-model") == updated_connection
    assert repository.list_model_connections() == (updated_connection,)
    assert repository.resolve_version("answer-model", version_id=first.version_id) == first
    assert repository.resolve_version("answer-model") == second
    with pytest.raises(PersistenceConflictError):
        repository.save_connection(_model_connection(), expected_revision=1)


def test_postgres_model_repository_counts_exact_configuration_references(
    postgres_engine: Engine,
) -> None:
    repository = PostgresModelAssetRepository(postgres_engine)
    model_version = repository.save_connection(_model_connection(), expected_revision=0)
    now = datetime(2026, 7, 15, tzinfo=UTC)
    draft_id = UUID("019ba001-1111-7000-8000-000000000401")
    agent_version_id = UUID("019ba001-1111-7000-8000-000000000402")
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.insert(agent_drafts).values(
                draft_id=draft_id,
                agent_id="enterprise-qa",
                revision=1,
                draft_json={
                    "contract_bundle": {
                        "agent_yaml": """
model:
  model_source: shared
  connection_id: answer-model
review:
  model_source: shared
  connection_id: answer-model
""",
                    }
                },
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            sa.insert(agent_versions).values(
                version_id=agent_version_id,
                agent_id="enterprise-qa",
                source_draft_id=draft_id,
                source_draft_revision=1,
                version_json={},
                published_at=now,
                published_by="publisher",
            )
        )
        connection.execute(
            sa.insert(agent_version_shared_asset_refs).values(
                agent_version_id=agent_version_id,
                asset_kind="model_connection",
                asset_id="answer-model",
                asset_version_id=UUID(model_version.version_id),
                asset_revision=model_version.revision,
                content_sha256=model_version.content_digest,
            )
        )
        connection.execute(
            sa.insert(knowledge_sources).values(
                source_id="insurance-clauses",
                revision=1,
                lifecycle_state="ACTIVE",
                configuration_json={
                    "params": {
                        "ingestion_model": {
                            "model_source": "shared",
                            "connection_id": "answer-model",
                        },
                        "unrelated": {
                            "model_source": "shared",
                            "connection_id": "other-model",
                        },
                    }
                },
                created_at=now,
                updated_at=now,
            )
        )

    summary = repository.get_model_connection_reference_summary("answer-model")

    assert summary.draft_agent_reference_count == 2
    assert summary.published_agent_version_reference_count == 1
    assert summary.knowledge_source_reference_count == 1
    assert summary.in_flight_operation_count == 0
    assert summary.audit_retention_blocked is True


def test_postgres_knowledge_and_tool_repositories_resolve_exact_versions(
    postgres_engine: Engine,
) -> None:
    knowledge = PostgresKnowledgeAssetRepository(postgres_engine)
    tools = PostgresToolAssetRepository(postgres_engine)
    source = KnowledgeSource(
        source_id="insurance-clauses",
        name="Insurance Clauses",
        provider="hybrid_index",
        lifecycle_state=KnowledgeSourceLifecycleState.ACTIVE,
        params={"publication_authority": "postgres_s3_opensearch"},
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
        source_draft_version_id="source-draft-1",
    )
    tool = ToolSource(
        source_id="policy-lookup",
        name="Policy Lookup",
        source_type="http",
        provider="http_json",
        tool_contract_ids=("policy.lookup",),
        params={"base_url": "https://tools.internal.example"},
        config_revision=1,
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )

    knowledge_ref = knowledge.save_source(source, expected_revision=0)
    tool_ref = tools.save_source(tool, expected_revision=0)

    assert knowledge.get_knowledge_source(source.source_id) == source
    assert tools.get_tool_source(tool.source_id) == tool
    assert knowledge.resolve_version(
        source.source_id, version_id=knowledge_ref.version_id
    ) == knowledge_ref
    assert tools.resolve_version(tool.source_id, version_id=tool_ref.version_id) == tool_ref
