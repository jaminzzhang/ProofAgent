from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient

from proof_agent.contracts import ReceiptOutcome, RunDetail
from proof_agent.capabilities.memory.mem0_store import Mem0MemoryStore
from proof_agent.configuration.importer import import_agent_package
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.delivery.customer_api import _customer_safe_message, _safe_sources
from proof_agent.observability.api.app import create_app as create_dashboard_app


def create_app(
    *,
    history_dir: Path,
    runs_dir: Path,
    conversations_dir: Path,
    published_agents: dict[str, Path] | None = None,
    agent_configuration_store: LocalAgentConfigurationStore | None = None,
    **kwargs: object,
):
    if published_agents is None and agent_configuration_store is None:
        agent_configuration_store = _publish_agent_package(
            history_dir.parent,
            Path("examples/insurance_customer_service/agent.yaml"),
        )
        published_agents = {}
    return create_dashboard_app(
        history_dir=history_dir,
        runs_dir=runs_dir,
        conversations_dir=conversations_dir,
        published_agents=published_agents,
        agent_configuration_store=agent_configuration_store,
        **kwargs,
    )


def _publish_agent_package(
    root_dir: Path,
    manifest_path: Path,
) -> LocalAgentConfigurationStore:
    store = LocalAgentConfigurationStore(root_dir / "config")
    draft = import_agent_package(manifest_path, store=store, actor="test-user")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="run_validation",
        actor="test-user",
    )
    return store


class RecordingMem0Client:
    def __init__(self) -> None:
        self.memories: list[dict[str, object]] = []
        self.delete_all_calls: list[dict[str, object]] = []

    def add(self, messages: object, **kwargs: object) -> dict[str, object]:
        metadata = kwargs["metadata"]
        assert isinstance(metadata, dict)
        memory_id = f"mem0_{len(self.memories) + 1}"
        self.memories.append(
            {
                "id": memory_id,
                "memory": "Case focus: inpatient reimbursement.",
                "created_at": "2026-05-21T00:00:00Z",
                "metadata": metadata,
            }
        )
        return {"id": memory_id}

    def search(self, query: str, **kwargs: object) -> dict[str, object]:
        _ = query
        filters = kwargs.get("filters")
        assert isinstance(filters, dict)
        expected_case = filters["AND"][0]["run_id"]  # type: ignore[index]
        metadata_filter = filters["AND"][1]["metadata"]  # type: ignore[index]
        expected_agent = metadata_filter["proof_agent_agent_id"]  # type: ignore[index]
        expected_scope = metadata_filter["proof_agent_scope"]  # type: ignore[index]
        return {
            "results": [
                memory
                for memory in self.memories
                if isinstance(memory["metadata"], dict)
                and memory["metadata"]["proof_agent_agent_id"] == expected_agent
                and memory["metadata"]["proof_agent_scope"] == expected_scope
                and memory["metadata"]["proof_agent_case_id"] == expected_case
            ]
        }

    def delete_all(self, **kwargs: object) -> dict[str, object]:
        self.delete_all_calls.append(kwargs)
        expected_case = kwargs["run_id"]
        metadata_filter = kwargs["metadata"]
        assert isinstance(metadata_filter, dict)
        expected_agent = metadata_filter["proof_agent_agent_id"]
        expected_scope = metadata_filter["proof_agent_scope"]
        self.memories = [
            memory
            for memory in self.memories
            if not (
                isinstance(memory["metadata"], dict)
                and memory["metadata"]["proof_agent_agent_id"] == expected_agent
                and memory["metadata"]["proof_agent_scope"] == expected_scope
                and memory["metadata"]["proof_agent_case_id"] == expected_case
            )
        ]
        return {"message": "Memories deleted successfully!"}


def test_customer_run_returns_customer_safe_projection(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    assert created.status_code == 200
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "message" in body
    assert "safe_sources" in body
    assert "links" not in body
    assert "governance_details" not in body
    assert "approval_state" not in body


def test_customer_safe_message_removes_internal_citation_markers() -> None:
    message = (
        "住院理赔需要提供理赔申请书和费用清单 "
        "[citation:knowledge://source/ks_myks2/document/doc_5750121a]。"
    )

    safe_message = _customer_safe_message(message)

    assert safe_message == "住院理赔需要提供理赔申请书和费用清单。"
    assert "[citation:" not in safe_message
    assert "knowledge://source/" not in safe_message


def test_customer_safe_sources_resolve_shared_knowledge_source_names(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_knowledge_source(
        source_id="ks_myks2",
        name="理赔知识库",
        provider="local_index",
        params={},
        actor="test-user",
    )
    detail = RunDetail(
        run_id="run_citation",
        question="住院理赔需要哪些材料？",
        outcome=ReceiptOutcome.ANSWERED_WITH_CITATIONS,
        created_at="2026-07-05T00:00:00Z",
        updated_at="2026-07-05T00:00:01Z",
        evidence_chunks=(
            {
                "source": "[1]",
                "citation": (
                    "knowledge://source/ks_myks2/document/doc_5750121a/"
                    "revision/rev_5750121a#node=node_1"
                ),
                "status": "accepted",
            },
        ),
    )

    assert _safe_sources(detail, knowledge_source_store=store) == ("理赔知识库",)


def test_customer_conversation_rejects_unknown_agent(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)

    response = client.post(
        "/api/customer/conversations",
        json={"agent_id": "unknown", "customer_id": "CUST-001"},
    )

    assert response.status_code == 404


def test_anonymous_customer_policy_status_requires_authentication(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is my policy status?"},
    )

    assert response.status_code == 200
    message = response.json()["message"].lower()
    assert "sign in" in message or "authenticate" in message


@pytest.mark.parametrize(
    ("customer_id", "question"),
    [
        (None, "What is my policy status?"),
        ("CUST-001", "What is the status of policy POL-001?"),
        ("CUST-001", "What is the status of claim CLM-001?"),
    ],
)
def test_customer_resource_paths_return_persisted_run_id(
    tmp_path: Path,
    customer_id: str | None,
    question: str,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": customer_id},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": question},
    )

    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert run_id
    assert client.get(f"/api/runs/{run_id}").status_code == 200


def test_authenticated_customer_policy_status_uses_authorized_read_tool(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of policy POL-001?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "active" in body["message"].lower()
    assert "approval_state" not in body


@pytest.mark.parametrize(
    ("question", "expected_label", "internal_tool_name"),
    [
        ("What is the status of policy POL-001?", "Policy status record", "policy_status_lookup"),
        ("What is the status of claim CLM-001?", "Claim status record", "claim_status_lookup"),
    ],
)
def test_customer_status_sources_use_customer_safe_labels(
    tmp_path: Path,
    question: str,
    expected_label: str,
    internal_tool_name: str,
) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": question},
    )

    assert response.status_code == 200
    safe_sources = response.json()["safe_sources"]
    assert expected_label in safe_sources
    assert internal_tool_name not in safe_sources
    assert all(not str(source).endswith("_lookup") for source in safe_sources)


def test_chinese_customer_claim_documents_uses_evidence_bound_translation(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "住院理赔需要哪些材料？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert "出院小结" in body["message"]
    assert "费用清单" in body["message"]
    assert "claim-reimbursement-policy.md" in body["safe_sources"]
    assert "No deterministic answer is configured" not in body["message"]


@pytest.mark.parametrize(
    ("question", "expected_terms", "expected_source"),
    [
        (
            "What does deductible mean in inpatient reimbursement coverage?",
            ("deductible", "out of pocket", "before reimbursement"),
            "product-terms.md",
        ),
        (
            "How should I understand the waiting period clause in a health insurance policy?",
            ("waiting period", "policy starts", "benefits"),
            "product-terms.md",
        ),
        (
            "What happens after I submit an inpatient reimbursement claim?",
            ("claim review", "documents", "status"),
            "claim-service-process.md",
        ),
    ],
)
def test_customer_product_terms_and_service_process_are_evidence_backed(
    tmp_path: Path,
    question: str,
    expected_terms: tuple[str, ...],
    expected_source: str,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": question},
    )

    assert response.status_code == 200
    body = response.json()
    message = body["message"].lower()
    for term in expected_terms:
        assert term in message
    assert expected_source in body["safe_sources"]


def test_customer_chinese_product_terms_are_evidence_bound(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "住院医疗险里的免赔额和等待期是什么意思？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert "免赔额" in body["message"]
    assert "等待期" in body["message"]
    assert "product-terms.md" in body["safe_sources"]
    assert "No deterministic answer is configured" not in body["message"]


def test_customer_outcome_optimization_request_is_reframed_to_safe_process_guidance(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents should I prepare to improve my claim approval odds?"},
    )

    assert response.status_code == 200
    body = response.json()
    message = body["message"].lower()
    assert "can't assess or promise approval likelihood" in message
    assert "documents" in message
    assert "review" in message
    assert "will be approved" not in message
    assert body["safe_sources"]


def test_customer_tool_execution_failure_is_temporary_and_trace_linked(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Retry my claim status lookup after the service times out."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"]
    assert body["failure_series_id"]
    assert "temporar" in body["message"].lower()
    assert not body["safe_sources"]

    trace = client.get(f"/api/runs/{body['run_id']}/trace").json()["events"]
    failure = next(
        event for event in trace if event["event_type"] == "customer_tool_execution_failure"
    )
    assert failure["status"] == "error"
    assert failure["payload"]["failure_series_id"] == body["failure_series_id"]
    assert failure["payload"]["tool_name"] == "claim_status_lookup"


def test_personalized_coverage_or_payment_decision_refuses_and_handoffs(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Based on my claim CLM-001, am I covered and how much will I be paid?"},
    )

    assert response.status_code == 200
    body = response.json()
    message = body["message"].lower()
    assert body["run_id"]
    assert "can't determine coverage or payment amount" in message
    assert "will be paid" not in message

    handoffs = client.get("/api/handoffs").json()["data"]
    assert [item["reason"] for item in handoffs] == ["payment_or_coverage_guarantee_request"]


def test_multi_claim_status_request_asks_customer_to_choose_one_resource(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of my claim?"},
    )

    assert response.status_code == 200
    body = response.json()
    message = body["message"]
    assert body["run_id"]
    assert "which claim" in message.lower()
    assert "1. Claim CLM-001" in message
    assert "2. Claim CLM-003" in message
    assert not body["safe_sources"]


def test_claim_disambiguation_ordinal_continuation_resolves_current_mapping(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    first = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of my claim?"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "For the claim options you showed, the first one."},
    )

    assert second.status_code == 200
    body = second.json()
    assert "in_review" in body["message"]
    assert "Claim status record" in body["safe_sources"]


def test_claim_disambiguation_ordinal_without_current_mapping_asks_again(
    tmp_path: Path,
) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "For the claim options you showed, the first one."},
    )

    assert response.status_code == 200
    body = response.json()
    assert "which claim" in body["message"].lower()
    assert not body["safe_sources"]


def test_cross_customer_policy_status_does_not_execute_tool(tmp_path: Path) -> None:
    client = TestClient(
        create_app(
            history_dir=tmp_path / "history",
            runs_dir=tmp_path / "latest",
            conversations_dir=tmp_path / "conversations",
        )
    )
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What is the status of policy POL-002?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert "POL-002" not in body["message"]
    assert "can't access" in body["message"].lower()


def test_customer_response_snapshot_is_stored(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    conversation = client.get(f"/api/customer/conversations/{conversation_id}").json()

    assert conversation["turns"][0]["response_snapshot"]["message"] == run["message"]
    assert conversation["turns"][0]["run_id"] == run["run_id"]


def test_customer_feedback_is_observation_only(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]
    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    ).json()

    feedback = client.post(
        f"/api/customer/conversations/{conversation_id}/turns/{run['turn_id']}/feedback",
        json={"rating": "down", "comment": "Need more detail."},
    )

    assert feedback.status_code == 200
    assert feedback.json()["feedback"]["applies_to_training"] is False


def test_customer_run_admits_same_case_memory_on_follow_up(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    first = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are needed for that reimbursement again?"},
    )

    assert second.status_code == 200
    trace = client.get(f"/api/runs/{second.json()['run_id']}/trace").json()["events"]
    admission = next(event for event in trace if event["event_type"] == "memory_admission")
    assert admission["payload"]["admitted"] is True
    assert admission["payload"]["included_memory_ids"]
    assert "inpatient" in admission["payload"]["summary"].lower()
    context_admissions = [
        event for event in trace if event["event_type"] == "context_admission"
    ]
    for event in context_admissions:
        assert not any(
            turn_id.startswith("mem")
            for turn_id in event["payload"].get("included_turn_ids", [])
        )
    recall = next(event for event in trace if event["event_type"] == "memory_recall_summary")
    assert recall["payload"]["scope"] == "case"
    assert recall["payload"]["included_memory_ids"] == admission["payload"][
        "included_memory_ids"
    ]
    assembly = next(
        event for event in trace if event["event_type"] == "context_assembly_summary"
    )
    assert {
        "source_type": "memory_recall",
        "source_id": admission["payload"]["included_memory_ids"][0],
    } in assembly["payload"]["source_refs"]


def test_customer_run_does_not_admit_memory_from_another_case(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    first_conversation = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    ).json()["conversation_id"]
    second_conversation = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    ).json()["conversation_id"]

    client.post(
        f"/api/customer/conversations/{first_conversation}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )
    response = client.post(
        f"/api/customer/conversations/{second_conversation}/runs",
        json={"question": "What documents are needed for that reimbursement again?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    admission = next(event for event in trace if event["event_type"] == "memory_admission")
    assert admission["payload"]["admitted"] is False
    assert admission["payload"]["included_memory_ids"] == []


def test_customer_run_traces_case_memory_write_decision(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    event_types = [event["event_type"] for event in trace]
    promotion = next(event for event in trace if event["event_type"] == "memory_promotion_decision")
    assert promotion["payload"] == {
        "outcome": "case_memory",
        "source_turn_id": response.json()["turn_id"],
        "target_scope": "case",
        "reasons": ["case_memory_candidate_generated"],
    }
    assert "memory_candidate_generated" in event_types
    assert "memory_write_requested" in event_types
    assert "memory_write_decision" in event_types


def test_customer_run_traces_no_memory_promotion_when_no_candidate(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Hello."},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    promotion = next(event for event in trace if event["event_type"] == "memory_promotion_decision")
    assert promotion["status"] == "blocked"
    assert promotion["payload"] == {
        "outcome": "no_memory",
        "source_turn_id": response.json()["turn_id"],
        "target_scope": None,
        "reasons": ["case_memory_candidate_not_generated"],
    }
    assert "memory_candidate_generated" not in [event["event_type"] for event in trace]


def test_customer_run_can_use_mem0_case_memory_adapter(tmp_path: Path) -> None:
    agent_dir = tmp_path / "insurance_customer_service_mem0"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "  memory:\n    enabled: true\n    provider: local",
            "  memory:\n    enabled: true\n    provider: mem0",
        ),
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_mem0": manifest_path},
        mem0_memory_store=Mem0MemoryStore(client=RecordingMem0Client()),
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_mem0", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )
    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are needed for that reimbursement again?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    admission = next(event for event in trace if event["event_type"] == "memory_admission")
    assert admission["payload"]["admitted"] is True
    assert admission["payload"]["included_memory_ids"] == ["mem0_1"]


def test_customer_case_memory_can_be_deleted_for_conversation(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_customer_service", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    first = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )
    run_id = first.json()["run_id"]
    deleted = client.delete(f"/api/customer/conversations/{conversation_id}/memory")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    assert deleted.json()["audit_run_id"] == run_id
    delete_trace = client.get(f"/api/runs/{run_id}/trace").json()["events"]
    delete_event = next(
        event for event in delete_trace if event["event_type"] == "memory_delete_decision"
    )
    assert delete_event["payload"] == {
        "scope": "case",
        "case_id": conversation_id,
        "agent_id": "insurance_customer_service",
        "provider": "local",
        "deleted_count": 1,
    }

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are needed for that reimbursement again?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    admission = next(event for event in trace if event["event_type"] == "memory_admission")
    assert admission["payload"]["admitted"] is False
    assert admission["payload"]["included_memory_ids"] == []


def test_customer_case_memory_can_be_deleted_for_mem0_provider(tmp_path: Path) -> None:
    agent_dir = tmp_path / "insurance_customer_service_mem0"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "  memory:\n    enabled: true\n    provider: local",
            "  memory:\n    enabled: true\n    provider: mem0",
        ),
        encoding="utf-8",
    )
    mem0_client = RecordingMem0Client()
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_mem0": manifest_path},
        mem0_memory_store=Mem0MemoryStore(client=mem0_client),
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_mem0", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are required for inpatient claim reimbursement?"},
    )
    deleted = client.delete(f"/api/customer/conversations/{conversation_id}/memory")
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    assert mem0_client.delete_all_calls == [
        {
            "run_id": conversation_id,
            "metadata": {
                "proof_agent_agent_id": "insurance_mem0",
                "proof_agent_scope": "case",
            },
        }
    ]

    response = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "What documents are needed for that reimbursement again?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    admission = next(event for event in trace if event["event_type"] == "memory_admission")
    assert admission["payload"]["admitted"] is False
    assert admission["payload"]["included_memory_ids"] == []


def test_customer_persistent_user_memory_is_admitted_across_conversations_with_consent(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "insurance_customer_service_user_memory"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "      user:\n        enabled: false",
            "      user:\n        enabled: true",
        ),
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_user_memory": manifest_path},
    )
    client = TestClient(app)
    first = client.post(
        "/api/customer/conversations",
        json={
            "agent_id": "insurance_user_memory",
            "customer_id": "CUST-001",
            "memory_consent": True,
        },
    )
    first_conversation_id = first.json()["conversation_id"]
    first_run = client.post(
        f"/api/customer/conversations/{first_conversation_id}/runs",
        json={"question": "I usually care about monthly claim reports."},
    )
    assert first_run.status_code == 200
    first_trace = client.get(f"/api/runs/{first_run.json()['run_id']}/trace").json()["events"]
    user_promotion = next(
        event
        for event in first_trace
        if event["event_type"] == "memory_promotion_decision"
        and event["payload"]["outcome"] == "persistent_user_memory"
    )
    assert user_promotion["payload"] == {
        "outcome": "persistent_user_memory",
        "source_turn_id": first_run.json()["turn_id"],
        "target_scope": "user",
        "reasons": ["persistent_user_memory_candidate_generated"],
    }
    second = client.post(
        "/api/customer/conversations",
        json={
            "agent_id": "insurance_user_memory",
            "customer_id": "CUST-001",
            "memory_consent": True,
        },
    )
    second_conversation_id = second.json()["conversation_id"]

    response = client.post(
        f"/api/customer/conversations/{second_conversation_id}/runs",
        json={"question": "Can we use that report view again?"},
    )

    assert response.status_code == 200
    trace = client.get(f"/api/runs/{response.json()['run_id']}/trace").json()["events"]
    user_admission = next(
        event
        for event in trace
        if event["event_type"] == "memory_admission" and event["payload"]["scope"] == "user"
    )
    assert user_admission["payload"]["admitted"] is True
    assert user_admission["payload"]["subject_ref"] == "CUST-001"
    assert user_admission["payload"]["included_memory_ids"]
    assert "claim reports" in user_admission["payload"]["summary"]


def test_customer_persistent_user_memory_can_be_exported_and_deleted(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "insurance_customer_service_user_memory"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "      user:\n        enabled: false",
            "      user:\n        enabled: true",
        ),
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_user_memory": manifest_path},
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={
            "agent_id": "insurance_user_memory",
            "customer_id": "CUST-001",
            "memory_consent": True,
        },
    )
    conversation_id = created.json()["conversation_id"]
    first_run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "I usually care about monthly claim reports."},
    )
    run_id = first_run.json()["run_id"]

    exported = client.get(
        "/api/customer/memory/CUST-001",
        params={"agent_id": "insurance_user_memory"},
    )
    deleted = client.delete(
        "/api/customer/memory/CUST-001",
        params={"agent_id": "insurance_user_memory"},
    )
    exported_after_delete = client.get(
        "/api/customer/memory/CUST-001",
        params={"agent_id": "insurance_user_memory"},
    )

    assert exported.status_code == 200
    assert exported.json()["agent_id"] == "insurance_user_memory"
    assert exported.json()["subject_ref"] == "CUST-001"
    assert exported.json()["audit_run_id"] == run_id
    assert len(exported.json()["memories"]) == 1
    memory = exported.json()["memories"][0]
    assert set(memory) == {
        "memory_id",
        "scope",
        "subject_ref",
        "agent_id",
        "summary",
        "facts",
        "source_run_id",
        "source_turn_id",
        "created_at",
        "expires_at",
        "sensitivity",
        "status",
    }
    assert "claim reports" in memory["summary"]
    assert deleted.status_code == 200
    assert deleted.json()["deleted_count"] == 1
    assert deleted.json()["audit_run_id"] == run_id
    assert exported_after_delete.json()["memories"] == []

    trace = client.get(f"/api/runs/{run_id}/trace").json()["events"]
    export_event = next(event for event in trace if event["event_type"] == "memory_export_decision")
    delete_event = next(
        event
        for event in trace
        if event["event_type"] == "memory_delete_decision" and event["payload"]["scope"] == "user"
    )
    assert export_event["payload"]["exported_count"] == 1
    assert export_event["payload"]["subject_ref"] == "CUST-001"
    assert delete_event["payload"]["deleted_count"] == 1
    assert delete_event["payload"]["subject_ref"] == "CUST-001"


def test_customer_persistent_user_memory_is_not_written_without_consent(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "insurance_customer_service_user_memory"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "      user:\n        enabled: false",
            "      user:\n        enabled: true",
        ),
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_user_memory": manifest_path},
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={"agent_id": "insurance_user_memory", "customer_id": "CUST-001"},
    )
    conversation_id = created.json()["conversation_id"]

    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "I usually care about monthly claim reports."},
    )
    exported = client.get(
        "/api/customer/memory/CUST-001",
        params={"agent_id": "insurance_user_memory"},
    )

    assert run.status_code == 200
    trace = client.get(f"/api/runs/{run.json()['run_id']}/trace").json()["events"]
    user_no_memory = next(
        event
        for event in trace
        if event["event_type"] == "memory_promotion_decision"
        and event["payload"]["outcome"] == "no_memory"
        and event["payload"]["reasons"] == ["user_memory_consent_not_granted"]
    )
    assert user_no_memory["payload"] == {
        "outcome": "no_memory",
        "source_turn_id": run.json()["turn_id"],
        "target_scope": None,
        "reasons": ["user_memory_consent_not_granted"],
    }
    assert exported.status_code == 200
    assert exported.json()["memories"] == []


def test_customer_persistent_user_memory_records_no_memory_when_no_candidate(
    tmp_path: Path,
) -> None:
    agent_dir = tmp_path / "insurance_customer_service_user_memory"
    shutil.copytree(Path("examples/insurance_customer_service"), agent_dir)
    manifest_path = agent_dir / "agent.yaml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "      user:\n        enabled: false",
            "      user:\n        enabled: true",
        ),
        encoding="utf-8",
    )
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        conversations_dir=tmp_path / "conversations",
        published_agents={"insurance_user_memory": manifest_path},
    )
    client = TestClient(app)
    created = client.post(
        "/api/customer/conversations",
        json={
            "agent_id": "insurance_user_memory",
            "customer_id": "CUST-001",
            "memory_consent": True,
        },
    )
    conversation_id = created.json()["conversation_id"]

    run = client.post(
        f"/api/customer/conversations/{conversation_id}/runs",
        json={"question": "Hello."},
    )
    exported = client.get(
        "/api/customer/memory/CUST-001",
        params={"agent_id": "insurance_user_memory"},
    )

    assert run.status_code == 200
    trace = client.get(f"/api/runs/{run.json()['run_id']}/trace").json()["events"]
    user_no_memory = next(
        event
        for event in trace
        if event["event_type"] == "memory_promotion_decision"
        and event["payload"]["outcome"] == "no_memory"
        and event["payload"]["reasons"] == ["persistent_user_memory_candidate_not_generated"]
    )
    assert user_no_memory["payload"] == {
        "outcome": "no_memory",
        "source_turn_id": run.json()["turn_id"],
        "target_scope": None,
        "reasons": ["persistent_user_memory_candidate_not_generated"],
    }
    assert exported.status_code == 200
    assert exported.json()["memories"] == []
