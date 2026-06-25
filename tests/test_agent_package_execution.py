import json
from pathlib import Path

from proof_agent.contracts import ReceiptOutcome
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)


def test_execute_agent_package_run_executes_v3_with_controlled_react(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    assert result.workflow_template_execution_result is not None
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "run_started"
        and event["payload"]["runtime"] == "controlled_react_orchestrator"
        for event in events
    )


def test_execute_agent_package_run_projects_v3_answer_governance_trace(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
            question="What is the reimbursement rule for travel meals?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.ANSWERED_WITH_CITATIONS
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(event["event_type"] == "policy_decision" for event in events)
    evidence_events = [
        event for event in events if event["event_type"] == "evidence_evaluation"
    ]
    assert evidence_events
    assert "customer-support-policy" in evidence_events[-1]["payload"]["source_refs"]
    assert "customer-support-policy" in evidence_events[-1]["payload"]["accepted_sources"]


def test_execute_agent_package_run_returns_v3_clarification_need(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
            question="Can this customer claim it?",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_USER_CLARIFICATION
    assert result.workflow_template_execution_result is not None
    need = result.workflow_template_execution_result.clarification_need
    assert need is not None
    assert need.missing_fields == ("customer_id", "policy_id", "claim_type")
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "clarification_requested"
        and event["payload"]["missing_fields"] == [
            "customer_id",
            "policy_id",
            "claim_type",
        ]
        for event in events
    )


def test_execute_agent_package_run_projects_v3_tool_approval_payload(
    tmp_path: Path,
) -> None:
    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml"),
            question="Look up customer policy status before answering.",
            runs_dir=tmp_path / "run",
        )
    )

    assert result.outcome is ReceiptOutcome.WAITING_FOR_APPROVAL
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
    ]
    pending = next(
        event for event in events if event["event_type"] == "pending_approval_created"
    )
    payload = pending["payload"]
    assert payload["run_id"] == pending["run_id"]
    assert payload["thread_id"] == pending["run_id"]
    assert payload["action_id"] == "act_tool_1"
    assert payload["tool_name"] == "customer_lookup"
    assert payload["parameters"] == {
        "customer_id": "CUST-001",
        "policy_id": "POL-001",
    }
    assert payload["policy_decision"] == "require_approval"
    assert payload["checkpoint_ref"]
    assert payload["checkpoint_id"] == payload["checkpoint_ref"]
