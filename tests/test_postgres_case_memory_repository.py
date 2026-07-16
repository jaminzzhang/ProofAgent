from __future__ import annotations

import pytest
from sqlalchemy import Engine

from postgres_fixtures import (
    TEST_AGENT_ID,
    TEST_CONVERSATION_ID,
    TEST_RUN_ID,
    TEST_TURN_ID,
)
from proof_agent.capabilities.persistence.postgres.case_memory_repository import (
    PostgresCaseMemoryRepository,
)
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.contracts import (
    CaseMemoryAdmission,
    MemoryCandidate,
    MemoryQuery,
    MemoryScope,
)
from test_postgres_conversation_repository import (
    _seed_run,
    conversation_record,
    conversation_turn,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def _seed_conversation(engine: Engine) -> None:
    _seed_run(engine)
    conversations = PostgresConversationRepository(engine)
    conversations.create(conversation_record())
    conversations.append_turn(
        TEST_CONVERSATION_ID,
        conversation_turn(),
        expected_turn_count=0,
    )


def test_postgres_case_memory_is_hidden_at_expiry_and_marked_deleted(
    postgres_engine: Engine,
) -> None:
    _seed_conversation(postgres_engine)
    repository = PostgresCaseMemoryRepository(postgres_engine)
    admission = CaseMemoryAdmission(
        candidate=MemoryCandidate(
            scope=MemoryScope.CASE,
            case_id=TEST_CONVERSATION_ID,
            agent_id=TEST_AGENT_ID,
            summary="关注等待期。",
            facts={"case_focus": ["waiting_period"]},
            source_run_id=TEST_RUN_ID,
            source_turn_id=TEST_TURN_ID,
            expires_at="2026-08-14T00:00:00Z",
        ),
        admitted_at="2026-07-15T00:00:00Z",
    )
    stored = repository.admit(admission)
    query = MemoryQuery(
        scope=MemoryScope.CASE,
        case_id=TEST_CONVERSATION_ID,
        agent_id=TEST_AGENT_ID,
    )

    assert repository.read(query, as_of="2026-08-13T23:59:59Z") == (stored,)
    assert repository.read(query, as_of="2026-08-14T00:00:00Z") == ()
    assert repository.expire_due(as_of="2026-08-14T00:00:00Z") == 1
    assert repository.expire_due(as_of="2026-08-14T00:00:00Z") == 0
