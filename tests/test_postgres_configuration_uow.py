from __future__ import annotations

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.agent_repository import (
    PostgresAgentLifecycleRepository,
)
from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.capabilities.persistence.postgres.configuration_uow import (
    PostgresConfigurationUnitOfWork,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    ContractBundle,
    DraftAgent,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def draft() -> DraftAgent:
    return DraftAgent(
        agent_id="agent_management_insurance_specialist",
        draft_id="019ba001-1111-7000-8000-000000000040",
        display_name="Insurance Specialist",
        purpose="Answer governed insurance questions",
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


def audit_event() -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000041",
        category=AuditCategory.CONFIGURATION,
        event_type="agent.draft.saved",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="enterprise-oidc",
            session_id="session-1",
        ),
        occurred_at="2026-07-15T00:00:00Z",
        target_type="agent_draft",
        target_id="019ba001-1111-7000-8000-000000000040",
    )


def test_postgres_configuration_unit_of_work_rolls_back_all_repositories(
    postgres_engine: Engine,
) -> None:
    event = audit_event()
    with pytest.raises(RuntimeError, match="fail before commit"):
        with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
            uow.agents.save_draft(draft(), expected_revision=0)
            uow.audit.append(event)
            uow.commit()
            raise RuntimeError("fail before commit")

    assert PostgresAgentLifecycleRepository(postgres_engine).get_draft(
        draft().agent_id, draft().draft_id
    ) is None
    assert PostgresAuditRepository(postgres_engine).get(event.audit_id) is None


def test_postgres_configuration_unit_of_work_commits_all_repositories(
    postgres_engine: Engine,
) -> None:
    event = audit_event()
    with PostgresConfigurationUnitOfWork(postgres_engine) as uow:
        saved = uow.agents.save_draft(draft(), expected_revision=0)
        uow.audit.append(event)
        uow.commit()

    assert PostgresAgentLifecycleRepository(postgres_engine).get_draft(
        draft().agent_id, draft().draft_id
    ) == saved
    assert PostgresAuditRepository(postgres_engine).get(event.audit_id) == event
