from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from proof_agent.observability.api.app import create_app


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
    assert [item["reason"] for item in handoffs] == [
        "payment_or_coverage_guarantee_request"
    ]


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
    assert "memory_candidate_generated" in event_types
    assert "memory_write_requested" in event_types
    assert "memory_write_decision" in event_types
