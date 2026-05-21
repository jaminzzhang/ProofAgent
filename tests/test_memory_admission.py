from proof_agent.contracts import (
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemorySensitivity,
    MemoryStatus,
)
from proof_agent.control.memory.admission import admit_memory


def test_user_memory_admission_requires_consent_and_matching_subject() -> None:
    record = MemoryRecord(
        memory_id="mem_user_123",
        scope=MemoryScope.USER,
        subject_ref="CUST-001",
        agent_id="insurance_customer_service",
        summary="Customer interest: claim reports by month.",
        facts={"interest_topics": ["claim_reports"]},
        source_run_id="run_123",
        source_turn_id="turn_123",
        created_at="2026-05-21T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
        sensitivity=MemorySensitivity.INTERNAL,
        status=MemoryStatus.ACTIVE,
    )

    without_consent = admit_memory(
        (record,),
        query=MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            agent_id="insurance_customer_service",
            consent_granted=False,
        ),
    )
    wrong_subject = admit_memory(
        (record,),
        query=MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-002",
            agent_id="insurance_customer_service",
            consent_granted=True,
        ),
    )
    admitted = admit_memory(
        (record,),
        query=MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            agent_id="insurance_customer_service",
            consent_granted=True,
        ),
    )

    assert without_consent.admitted is False
    assert without_consent.rejection_reasons == {"mem_user_123": "consent_required"}
    assert wrong_subject.admitted is False
    assert wrong_subject.rejection_reasons == {"mem_user_123": "subject_ref_mismatch"}
    assert admitted.admitted is True
    assert admitted.included_memory_ids == ("mem_user_123",)
