import sys
from types import SimpleNamespace

from proof_agent.capabilities.memory.mem0_store import Mem0MemoryStore, _create_default_client
from proof_agent.contracts import (
    MemoryCandidate,
    MemoryQuery,
    MemoryScope,
    MemorySensitivity,
)


class FakeMem0Client:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, object]] = []
        self.search_calls: list[dict[str, object]] = []
        self.delete_all_calls: list[dict[str, object]] = []
        self.search_results: dict[str, object] = {"results": []}

    def add(self, messages: object, **kwargs: object) -> dict[str, object]:
        self.add_calls.append({"messages": messages, **kwargs})
        return {"id": "mem0_123", "memory": "Case focus: inpatient reimbursement."}

    def search(self, query: str, **kwargs: object) -> dict[str, object]:
        self.search_calls.append({"query": query, **kwargs})
        return self.search_results

    def delete_all(self, **kwargs: object) -> dict[str, object]:
        self.delete_all_calls.append(kwargs)
        return {"message": "Memories deleted successfully!"}


class AsyncAddMem0Client(FakeMem0Client):
    def add(self, messages: object, **kwargs: object) -> dict[str, object]:
        self.add_calls.append({"messages": messages, **kwargs})
        return {
            "message": "Memory processing has been queued for background execution",
            "status": "PENDING",
            "event_id": "2c4d1f44-4f7b-4b2f-9f6e-7b5b4f5a1234",
        }


class FakePlatformMemoryClient:
    def __init__(self, *, api_key: str) -> None:
        self.api_key = api_key


class FakeOssMemory:
    pass


def test_mem0_default_client_prefers_platform_client_when_api_key_is_present(
    monkeypatch,
) -> None:
    monkeypatch.setenv("MEM0_API_KEY", "m0-test-key")
    monkeypatch.setitem(
        sys.modules,
        "mem0",
        SimpleNamespace(MemoryClient=FakePlatformMemoryClient, Memory=FakeOssMemory),
    )

    client = _create_default_client()

    assert isinstance(client, FakePlatformMemoryClient)
    assert client.api_key == "m0-test-key"


def test_mem0_store_uses_platform_event_id_as_write_reference() -> None:
    client = AsyncAddMem0Client()
    store = Mem0MemoryStore(client=client)
    candidate = MemoryCandidate(
        scope=MemoryScope.CASE,
        case_id="cust_conv_123",
        agent_id="insurance_customer_service",
        summary="Case focus: inpatient reimbursement.",
        facts={"focus_topics": ["inpatient", "reimbursement"]},
        source_run_id="run_123",
        source_turn_id="turn_123",
        expires_at="2099-01-01T00:00:00Z",
        sensitivity=MemorySensitivity.INTERNAL,
    )

    record = store.append(candidate)

    assert record.memory_id == "mem0_event_2c4d1f44-4f7b-4b2f-9f6e-7b5b4f5a1234"


def test_mem0_store_appends_case_memory_without_changing_contract() -> None:
    client = FakeMem0Client()
    store = Mem0MemoryStore(client=client)
    candidate = MemoryCandidate(
        scope=MemoryScope.CASE,
        case_id="cust_conv_123",
        agent_id="insurance_customer_service",
        summary="Case focus: inpatient reimbursement.",
        facts={"focus_topics": ["inpatient", "reimbursement"]},
        source_run_id="run_123",
        source_turn_id="turn_123",
        expires_at="2099-01-01T00:00:00Z",
        sensitivity=MemorySensitivity.INTERNAL,
    )

    record = store.append(candidate)

    assert record.memory_id == "mem0_123"
    assert record.scope == MemoryScope.CASE
    assert record.case_id == "cust_conv_123"
    add_call = client.add_calls[0]
    assert add_call["run_id"] == "cust_conv_123"
    assert "agent_id" not in add_call
    assert add_call["metadata"] == {
        "proof_agent_scope": "case",
        "proof_agent_case_id": "cust_conv_123",
        "proof_agent_subject_ref": "",
        "proof_agent_agent_id": "insurance_customer_service",
        "proof_agent_source_run_id": "run_123",
        "proof_agent_source_turn_id": "turn_123",
        "proof_agent_expires_at": "2099-01-01T00:00:00Z",
        "proof_agent_sensitivity": "internal",
        "proof_agent_status": "active",
        "proof_agent_facts": {"focus_topics": ["inpatient", "reimbursement"]},
    }


def test_mem0_store_appends_case_memory_as_proof_agent_controlled_record() -> None:
    client = FakeMem0Client()
    store = Mem0MemoryStore(client=client)
    candidate = MemoryCandidate(
        scope=MemoryScope.CASE,
        case_id="cust_conv_123",
        agent_id="insurance_customer_service",
        summary="Case focus: inpatient reimbursement.",
        facts={"focus_topics": ["inpatient", "reimbursement"]},
        source_run_id="run_123",
        source_turn_id="turn_123",
        expires_at="2099-01-01T00:00:00Z",
        sensitivity=MemorySensitivity.INTERNAL,
    )

    store.append(candidate)

    add_call = client.add_calls[0]
    assert add_call["run_id"] == "cust_conv_123"
    assert "agent_id" not in add_call
    assert add_call["infer"] is False
    assert add_call["expiration_date"] == "2099-01-01"
    assert add_call["metadata"] == {
        "proof_agent_scope": "case",
        "proof_agent_case_id": "cust_conv_123",
        "proof_agent_subject_ref": "",
        "proof_agent_agent_id": "insurance_customer_service",
        "proof_agent_source_run_id": "run_123",
        "proof_agent_source_turn_id": "turn_123",
        "proof_agent_expires_at": "2099-01-01T00:00:00Z",
        "proof_agent_sensitivity": "internal",
        "proof_agent_status": "active",
        "proof_agent_facts": {"focus_topics": ["inpatient", "reimbursement"]},
    }


def test_mem0_store_appends_customer_persistent_user_memory_with_subject_ref() -> None:
    client = FakeMem0Client()
    store = Mem0MemoryStore(client=client)
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

    record = store.append(candidate)

    assert record.scope == MemoryScope.USER
    assert record.subject_ref == "CUST-001"
    add_call = client.add_calls[0]
    assert add_call["user_id"] == "CUST-001"
    assert "agent_id" not in add_call
    assert add_call["metadata"] == {
        "proof_agent_scope": "user",
        "proof_agent_case_id": "",
        "proof_agent_subject_ref": "CUST-001",
        "proof_agent_agent_id": "insurance_customer_service",
        "proof_agent_source_run_id": "run_123",
        "proof_agent_source_turn_id": "turn_123",
        "proof_agent_expires_at": "2099-01-01T00:00:00Z",
        "proof_agent_sensitivity": "internal",
        "proof_agent_status": "active",
        "proof_agent_facts": {
            "interest_topics": ["claim_reports"],
            "preferred_views": ["monthly_summary"],
        },
    }


def test_mem0_store_appends_user_memory_as_subject_scoped_record() -> None:
    client = FakeMem0Client()
    store = Mem0MemoryStore(client=client)
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

    store.append(candidate)

    add_call = client.add_calls[0]
    assert add_call["user_id"] == "CUST-001"
    assert "agent_id" not in add_call
    assert add_call["infer"] is False
    assert add_call["expiration_date"] == "2099-01-01"


def test_mem0_store_reads_same_case_memory_with_bounded_search() -> None:
    client = FakeMem0Client()
    client.search_results = {
        "results": [
            {
                "id": "mem0_123",
                "memory": "Case focus: inpatient reimbursement.",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": {
                    "proof_agent_scope": "case",
                    "proof_agent_case_id": "cust_conv_123",
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_source_run_id": "run_123",
                    "proof_agent_source_turn_id": "turn_123",
                    "proof_agent_expires_at": "2099-01-01T00:00:00Z",
                    "proof_agent_sensitivity": "internal",
                    "proof_agent_status": "active",
                    "proof_agent_facts": {"focus_topics": ["inpatient", "reimbursement"]},
                },
            }
        ]
    }
    store = Mem0MemoryStore(client=client)

    records = store.read(
        MemoryQuery(
            scope=MemoryScope.CASE,
            case_id="cust_conv_123",
            agent_id="insurance_customer_service",
            max_records=3,
            query_text="that reimbursement again",
        )
    )

    assert len(records) == 1
    assert records[0].memory_id == "mem0_123"
    search_call = client.search_calls[0]
    assert search_call["query"] == "that reimbursement again"
    assert search_call["top_k"] == 3
    assert "agent_id" not in search_call
    assert "run_id" not in search_call
    assert search_call["filters"] == {
        "AND": [
            {"run_id": "cust_conv_123"},
            {
                "metadata": {
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_scope": "case",
                }
            },
        ]
    }
    assert search_call["show_expired"] is False


def test_mem0_store_reads_customer_persistent_user_memory_by_subject_ref() -> None:
    client = FakeMem0Client()
    client.search_results = {
        "results": [
            {
                "id": "mem0_user_123",
                "memory": "Customer interest: claim reports by month.",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": {
                    "proof_agent_scope": "user",
                    "proof_agent_case_id": "",
                    "proof_agent_subject_ref": "CUST-001",
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_source_run_id": "run_123",
                    "proof_agent_source_turn_id": "turn_123",
                    "proof_agent_expires_at": "2099-01-01T00:00:00Z",
                    "proof_agent_sensitivity": "internal",
                    "proof_agent_status": "active",
                    "proof_agent_facts": {
                        "interest_topics": ["claim_reports"],
                        "preferred_views": ["monthly_summary"],
                    },
                },
            }
        ]
    }
    store = Mem0MemoryStore(client=client)

    records = store.read(
        MemoryQuery(
            scope=MemoryScope.USER,
            subject_ref="CUST-001",
            agent_id="insurance_customer_service",
            max_records=3,
            query_text="reports",
        )
    )

    assert len(records) == 1
    assert records[0].memory_id == "mem0_user_123"
    assert records[0].subject_ref == "CUST-001"
    search_call = client.search_calls[0]
    assert search_call["query"] == "reports"
    assert search_call["top_k"] == 3
    assert search_call["filters"] == {
        "AND": [
            {"user_id": "CUST-001"},
            {
                "metadata": {
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_scope": "user",
                }
            },
        ]
    }
    assert search_call["show_expired"] is False


def test_mem0_store_soft_deletes_case_memory_by_agent_and_run_scope() -> None:
    client = FakeMem0Client()
    client.search_results = {
        "results": [
            {
                "id": "mem0_123",
                "memory": "Case focus: inpatient reimbursement.",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": {
                    "proof_agent_scope": "case",
                    "proof_agent_case_id": "cust_conv_123",
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_source_run_id": "run_123",
                    "proof_agent_source_turn_id": "turn_123",
                    "proof_agent_expires_at": "2099-01-01T00:00:00Z",
                    "proof_agent_sensitivity": "internal",
                    "proof_agent_status": "active",
                    "proof_agent_facts": {"focus_topics": ["inpatient", "reimbursement"]},
                },
            }
        ]
    }
    store = Mem0MemoryStore(client=client)

    deleted_count = store.soft_delete_case(
        agent_id="insurance_customer_service",
        case_id="cust_conv_123",
    )

    assert deleted_count == 1
    assert client.delete_all_calls == [
        {
            "run_id": "cust_conv_123",
            "metadata": {
                "proof_agent_agent_id": "insurance_customer_service",
                "proof_agent_scope": "case",
            },
        }
    ]


def test_mem0_store_soft_deletes_customer_persistent_user_memory_by_subject_ref() -> None:
    client = FakeMem0Client()
    client.search_results = {
        "results": [
            {
                "id": "mem0_user_123",
                "memory": "Customer interest: claim reports by month.",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": {
                    "proof_agent_scope": "user",
                    "proof_agent_case_id": "",
                    "proof_agent_subject_ref": "CUST-001",
                    "proof_agent_agent_id": "insurance_customer_service",
                    "proof_agent_source_run_id": "run_123",
                    "proof_agent_source_turn_id": "turn_123",
                    "proof_agent_expires_at": "2099-01-01T00:00:00Z",
                    "proof_agent_sensitivity": "internal",
                    "proof_agent_status": "active",
                    "proof_agent_facts": {"interest_topics": ["claim_reports"]},
                },
            }
        ]
    }
    store = Mem0MemoryStore(client=client)

    deleted_count = store.soft_delete_subject(
        agent_id="insurance_customer_service",
        subject_ref="CUST-001",
    )

    assert deleted_count == 1
    assert client.delete_all_calls == [
        {
            "user_id": "CUST-001",
            "metadata": {
                "proof_agent_agent_id": "insurance_customer_service",
                "proof_agent_scope": "user",
            },
        }
    ]
