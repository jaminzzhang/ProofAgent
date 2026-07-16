from __future__ import annotations

from collections.abc import Iterator
import os
from uuid import uuid4

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url


@pytest.fixture
def postgres_dsn() -> Iterator[str]:
    """Yield an isolated schema on the explicitly configured real PostgreSQL server."""

    base_dsn = os.environ.get("PROOF_AGENT_TEST_POSTGRES_DSN", "").strip()
    if not base_dsn:
        if os.environ.get("PROOF_AGENT_REQUIRE_POSTGRES_TESTS") == "1":
            pytest.fail("PROOF_AGENT_TEST_POSTGRES_DSN is required for PostgreSQL tests")
        pytest.skip("real PostgreSQL DSN is not configured")
    schema = f"proof_agent_test_{uuid4().hex}"
    base_engine = create_engine(base_dsn)
    with base_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = make_url(base_dsn)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    isolated_dsn = url.set(query=query).render_as_string(hide_password=False)
    try:
        yield isolated_dsn
    finally:
        with base_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        base_engine.dispose()


@pytest.fixture
def postgres_engine(postgres_dsn: str) -> Iterator[Engine]:
    from proof_agent.capabilities.persistence.postgres.database import upgrade_database

    upgrade_database(postgres_dsn)
    engine = create_engine(postgres_dsn, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()


TEST_AGENT_ID = "agent_management_insurance_specialist"
TEST_AGENT_VERSION_ID = "019ba001-1111-7000-8000-000000000001"
TEST_DRAFT_ID = "019ba001-1111-7000-8000-000000000002"
TEST_RUN_ID = "019ba001-1111-7000-8000-000000000010"
TEST_CONVERSATION_ID = "019ba001-1111-7000-8000-000000000011"
TEST_TURN_ID = "019ba001-1111-7000-8000-000000000012"


def seed_agent_version(engine: Engine) -> None:
    """Create only the parent rows required by Run repository tests."""

    from datetime import UTC, datetime
    from uuid import UUID

    from proof_agent.capabilities.persistence.postgres.schema import (
        agent_drafts,
        agent_versions,
    )

    now = datetime(2026, 7, 15, tzinfo=UTC)
    with engine.begin() as connection:
        connection.execute(
            agent_drafts.insert().values(
                draft_id=UUID(TEST_DRAFT_ID),
                agent_id=TEST_AGENT_ID,
                revision=1,
                draft_json={"fixture": True},
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            agent_versions.insert().values(
                version_id=UUID(TEST_AGENT_VERSION_ID),
                agent_id=TEST_AGENT_ID,
                source_draft_id=UUID(TEST_DRAFT_ID),
                source_draft_revision=1,
                version_json={"fixture": True},
                published_at=now,
                published_by="test-fixture",
            )
        )


def run_record() -> object:
    from proof_agent.contracts import (
        RunLifecycleState,
        RunMetadataRecord,
        RunPurpose,
    )

    return RunMetadataRecord(
        run_id=TEST_RUN_ID,
        state=RunLifecycleState.QUEUED,
        state_version=1,
        run_purpose=RunPurpose.PRODUCTION,
        agent_id=TEST_AGENT_ID,
        agent_version_id=TEST_AGENT_VERSION_ID,
        submitted_by="operator-1",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )
