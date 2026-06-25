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
