from __future__ import annotations

from datetime import UTC, datetime

import pytest

from knowledge_source_service.adapters.memory.artifacts import (
    InMemoryImmutableArtifactStore,
)
from knowledge_source_service.adapters.postgres.access_control import (
    KnowledgeAccessConflict,
    PostgresKnowledgeAccessControl,
)
from knowledge_source_service.adapters.postgres.knowledge_catalog import (
    PostgresKnowledgeCatalog,
)
from knowledge_source_service.adapters.postgres.migrations import (
    apply_knowledge_service_migrations,
)
from knowledge_source_service.application.document_intake import (
    DocumentIntakeApplication,
    DocumentIntakeCommand,
)
from knowledge_source_service.application.knowledge_releases import (
    KnowledgeReleaseApplication,
    PublishKnowledgeReleaseCommand,
)
from knowledge_source_service.contracts.knowledge_query import CreateKnowledgeQueryRequest


pytestmark = pytest.mark.postgres_integration


def test_one_space_allows_multiple_agents_without_grant_or_budget_widening(
    kss_postgres_dsn: str,
) -> None:
    apply_knowledge_service_migrations(kss_postgres_dsn)
    artifacts = InMemoryImmutableArtifactStore()
    catalog = PostgresKnowledgeCatalog.from_dsn(
        kss_postgres_dsn,
        artifacts=artifacts,
    )
    catalog.create_space("space-shared")
    catalog.create_source(
        knowledge_space_id="space-shared",
        knowledge_source_id="source-policy",
    )
    catalog.create_base(
        knowledge_space_id="space-shared",
        knowledge_base_id="base-policy",
    )
    source_version = DocumentIntakeApplication(
        artifacts=artifacts,
        catalog=catalog,
        pipeline_revision="document-pipeline-v1",
        max_content_bytes=1024,
    ).create_source_version(
        DocumentIntakeCommand(
            knowledge_space_id="space-shared",
            knowledge_source_id="source-policy",
            display_filename="policy.md",
            media_type="text/markdown",
            content="# 规则\n共享规则。\n".encode(),
        )
    )
    release = KnowledgeReleaseApplication(
        artifacts=artifacts,
        catalog=catalog,
    ).publish(
        PublishKnowledgeReleaseCommand(
            knowledge_space_id="space-shared",
            knowledge_base_id="base-policy",
            knowledge_source_version_ids=(
                source_version.version.knowledge_source_version_id,
            ),
        )
    ).release

    access = PostgresKnowledgeAccessControl.from_dsn(kss_postgres_dsn)
    access.register_client(client_id="agent-alpha", bearer_token="alpha-secret-token-1")
    access.register_client(client_id="agent-beta", bearer_token="beta-secret-token-22")
    access.register_client(client_id="agent-no-grant", bearer_token="none-secret-token-33")
    for client_id, grant_id, digest_character in (
        ("agent-alpha", "grant-alpha", "a"),
        ("agent-beta", "grant-beta", "b"),
    ):
        access.grant_release_query(
            client_grant_id=grant_id,
            client_id=client_id,
            knowledge_base_release_id=release.knowledge_base_release_id,
            allowed_strategies=("single_pass", "agentic"),
            max_rounds=3,
            max_model_calls=6,
            max_candidates=100,
            max_model_tokens=5000,
            max_duration_ms=10_000,
            effective_access_scope_digest=f"sha256:{digest_character * 64}",
        )

    request = CreateKnowledgeQueryRequest.model_validate(
        {
            "knowledge_base_release_id": release.knowledge_base_release_id,
            "question": "共享规则是什么？",
            "strategy": "agentic",
            "execution_budget": {
                "max_rounds": 2,
                "max_model_calls": 4,
                "max_candidates": 50,
                "max_model_tokens": 4000,
                "max_duration_ms": 8000,
            },
            "deadline_at": datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
        }
    )
    alpha = access.authorize(client_id="agent-alpha", request=request)
    beta = access.authorize(client_id="agent-beta", request=request)

    assert access.authenticate_bearer_token("alpha-secret-token-1") == "agent-alpha"
    assert access.authenticate_bearer_token("wrong-secret-token") is None
    assert alpha is not None and alpha.knowledge_space_id == "space-shared"
    assert beta is not None and beta.knowledge_space_id == "space-shared"
    assert alpha.client_grant_id == "grant-alpha"
    assert beta.client_grant_id == "grant-beta"
    assert alpha.effective_access_scope_digest != beta.effective_access_scope_digest
    assert access.authorize(client_id="agent-no-grant", request=request) is None

    over_budget = request.model_copy(
        update={
            "execution_budget": request.execution_budget.model_copy(
                update={"max_candidates": 101}
            )
        }
    )
    assert access.authorize(client_id="agent-alpha", request=over_budget) is None
    with pytest.raises(KnowledgeAccessConflict):
        access.register_client(
            client_id="agent-alpha",
            bearer_token="different-secret-token",
        )
