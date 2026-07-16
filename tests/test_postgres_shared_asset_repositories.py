from __future__ import annotations

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.knowledge_repository import (
    PostgresKnowledgeAssetRepository,
)
from proof_agent.capabilities.persistence.postgres.model_repository import (
    PostgresModelAssetRepository,
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
