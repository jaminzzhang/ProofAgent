from pathlib import Path

from proof_agent.capabilities.memory.local_store import LocalMemoryStore
from proof_agent.contracts import (
    MemoryCandidate,
    MemoryQuery,
    MemoryScope,
    MemorySensitivity,
)


def test_local_store_manages_customer_persistent_user_memory_by_subject(tmp_path: Path) -> None:
    store = LocalMemoryStore(tmp_path / "memory")
    candidate = MemoryCandidate(
        scope=MemoryScope.USER,
        subject_ref="CUST-001",
        agent_id="insurance_customer_service",
        summary="Customer interest: claim reports by month.",
        facts={"interest_topics": ["claim_reports"], "preferred_views": ["monthly_summary"]},
        source_run_id="run_123",
        source_turn_id="turn_123",
        expires_at="2099-01-01T00:00:00Z",
        sensitivity=MemorySensitivity.INTERNAL,
    )

    stored = store.append(candidate)
    same_subject = store.read(
        MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            agent_id="insurance_customer_service",
            max_records=5,
        )
    )
    other_subject = store.read(
        MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-002",
            agent_id="insurance_customer_service",
            max_records=5,
        )
    )
    exported = store.export_subject(
        agent_id="insurance_customer_service",
        subject_ref="CUST-001",
    )
    deleted_count = store.soft_delete_subject(
        agent_id="insurance_customer_service",
        subject_ref="CUST-001",
    )
    after_delete = store.read(
        MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            agent_id="insurance_customer_service",
            max_records=5,
        )
    )

    assert stored.subject_ref == "CUST-001"
    assert same_subject == (stored,)
    assert other_subject == ()
    assert exported == (stored,)
    assert deleted_count == 1
    assert after_delete == ()
