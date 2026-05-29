from pathlib import Path

from fastapi.testclient import TestClient

from proof_agent.contracts import ReceiptOutcome
from proof_agent.observability.api.app import create_app
from proof_agent.runtime.langgraph_runner import run_with_langgraph
from published_agent_support import publish_agent_package


INSURANCE_AGENT = Path("examples/insurance_service_qa/agent.yaml")


def test_insurance_service_supported_question_answers_with_evidence(tmp_path: Path) -> None:
    result = run_with_langgraph(
        INSURANCE_AGENT,
        question="What documents are required for inpatient claim reimbursement?",
        runs_dir=tmp_path,
    )

    assert result.outcome == ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert "Inpatient claim reimbursement requires" in result.final_output


def test_insurance_service_unsupported_question_refuses(tmp_path: Path) -> None:
    result = run_with_langgraph(
        INSURANCE_AGENT,
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path,
    )

    assert result.outcome == ReceiptOutcome.REFUSED_NO_EVIDENCE


def test_insurance_service_tool_question_waits_for_approval(tmp_path: Path) -> None:
    result = run_with_langgraph(
        INSURANCE_AGENT,
        question="Look up customer policy status before answering.",
        runs_dir=tmp_path,
    )

    assert result.outcome == ReceiptOutcome.WAITING_FOR_APPROVAL


def test_insurance_service_template_is_not_default_published_agent(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "insurance_service_qa",
            "question": "What documents are required for inpatient claim reimbursement?",
        },
    )

    assert response.status_code == 404


def test_published_insurance_service_runs_via_chat_api(tmp_path: Path) -> None:
    app = create_app(
        history_dir=tmp_path / "history",
        runs_dir=tmp_path / "latest",
        published_agents={},
        agent_configuration_store=publish_agent_package(tmp_path, INSURANCE_AGENT),
    )
    client = TestClient(app)

    response = client.post(
        "/api/chat/runs",
        json={
            "agent_id": "insurance_service_qa",
            "question": "What documents are required for inpatient claim reimbursement?",
        },
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "ANSWERED_WITH_CITATIONS"
