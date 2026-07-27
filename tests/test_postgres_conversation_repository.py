from __future__ import annotations

import pytest
from sqlalchemy import Engine

from postgres_fixtures import (
    TEST_AGENT_ID,
    TEST_CONVERSATION_ID,
    TEST_RUN_ID,
    TEST_TURN_ID,
    run_record,
    seed_agent_version,
)
from proof_agent.capabilities.persistence.postgres.conversation_repository import (
    PostgresConversationRepository,
)
from proof_agent.capabilities.persistence.postgres.run_repository import (
    PostgresRunMetadataRepository,
)
from proof_agent.contracts import (
    ContextAdmission,
    ConversationRecord,
    ConversationTurn,
    PersistenceConflictError,
    ReceiptOutcome,
    RunMetadataRecord,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def conversation_record() -> ConversationRecord:
    return ConversationRecord(
        conversation_id=TEST_CONVERSATION_ID,
        agent_id=TEST_AGENT_ID,
        title="保险条款咨询",
        created_at="2026-07-15T00:00:00Z",
        updated_at="2026-07-15T00:00:00Z",
    )


def conversation_turn() -> ConversationTurn:
    return ConversationTurn(
        turn_id=TEST_TURN_ID,
        run_id=TEST_RUN_ID,
        agent_id=TEST_AGENT_ID,
        question="等待期如何规定？",
        final_output="依据条款……",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-07-15T00:01:00Z",
        context_admission=ContextAdmission(admitted=False),
    )


def _seed_run(engine: Engine) -> None:
    seed_agent_version(engine)
    record = run_record()
    assert isinstance(record, RunMetadataRecord)
    PostgresRunMetadataRepository(engine).append(record)


def test_postgres_conversation_repository_orders_turns_and_rejects_stale_append(
    postgres_engine: Engine,
) -> None:
    _seed_run(postgres_engine)
    repository = PostgresConversationRepository(postgres_engine)
    conversation = conversation_record()
    turn = conversation_turn()
    repository.create(conversation)

    updated = repository.append_turn(
        conversation.conversation_id,
        turn,
        expected_turn_count=0,
    )

    assert updated == conversation.model_copy(
        update={"updated_at": turn.created_at, "turns": (turn,)}
    )
    assert repository.get(conversation.conversation_id) == updated
    with pytest.raises(PersistenceConflictError):
        repository.append_turn(
            conversation.conversation_id,
            turn.model_copy(
                update={"turn_id": "019ba001-1111-7000-8000-000000000013"}
            ),
            expected_turn_count=0,
        )


def test_postgres_conversation_identity_is_unique(postgres_engine: Engine) -> None:
    repository = PostgresConversationRepository(postgres_engine)
    repository.create(conversation_record())

    with pytest.raises(PersistenceConflictError):
        repository.create(conversation_record())


def test_postgres_conversation_serializes_frozen_evidence_mapping(
    postgres_engine: Engine,
) -> None:
    _seed_run(postgres_engine)
    repository = PostgresConversationRepository(postgres_engine)
    conversation = conversation_record()
    turn = ConversationTurn.model_validate(
        {
            **conversation_turn().model_dump(mode="python"),
            "evidence": (
                {
                    "source": "terms.pdf#p=12",
                    "citation": "terms.pdf#p=12:L3-L8",
                    "status": "accepted",
                },
            )
        }
    )
    repository.create(conversation)

    updated = repository.append_turn(
        conversation.conversation_id,
        turn,
        expected_turn_count=0,
    )

    assert updated.turns[0].evidence == turn.evidence
