from __future__ import annotations

import pytest
from sqlalchemy import Engine

from proof_agent.capabilities.persistence.postgres.audit_repository import (
    PostgresAuditRepository,
)
from proof_agent.contracts import (
    AuditActorFacts,
    AuditCategory,
    AuditMetadataRecord,
    AuditOutcome,
    PersistenceConflictError,
)


pytestmark = pytest.mark.postgres_integration
pytest_plugins = ("postgres_fixtures",)


def audit_event() -> AuditMetadataRecord:
    return AuditMetadataRecord(
        audit_id="019ba001-1111-7000-8000-000000000030",
        category=AuditCategory.CONFIGURATION,
        event_type="agent.version.published",
        outcome=AuditOutcome.SUCCEEDED,
        actor=AuditActorFacts(
            subject="operator-1",
            identity_provider="enterprise-oidc",
            session_id="session-1",
            permissions=("agent.publish",),
        ),
        occurred_at="2026-07-15T00:01:00Z",
        target_type="agent_version",
        target_id="agent_management_insurance_specialist:v1",
        metadata={"draft_revision": 1},
    )


def test_postgres_audit_repository_is_append_only_and_trace_safe(
    postgres_engine: Engine,
) -> None:
    repository = PostgresAuditRepository(postgres_engine)
    event = audit_event()
    repository.append(event)

    assert repository.get(event.audit_id) == event
    assert not hasattr(repository, "update")
    assert not hasattr(repository, "delete")
    with pytest.raises(PersistenceConflictError):
        repository.append(event)
