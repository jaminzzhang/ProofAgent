from pathlib import Path

from proof_agent.contracts import ApprovalStatus
from proof_agent.capabilities.tools.gateway import ToolGateway


def test_customer_lookup_requires_approval_before_execution() -> None:
    gateway = ToolGateway.from_file("examples/enterprise_qa/tools.yaml")
    result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=False,
    )
    assert result.approval_state.state == ApprovalStatus.REQUESTED
    assert result.executed is False


def test_approved_customer_lookup_executes_mock_tool() -> None:
    gateway = ToolGateway.from_file("examples/enterprise_qa/tools.yaml")
    result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=True,
    )
    assert result.approval_state.state == ApprovalStatus.GRANTED
    assert result.executed is True


def test_policy_authorized_read_tool_executes_without_human_approval(tmp_path: Path) -> None:
    handler_path = tmp_path / "tool_handlers.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def policy_status_lookup(parameters: Mapping[str, Any]) -> dict[str, object]:
    return {
        "customer_id": str(parameters["customer_id"]),
        "policy_id": str(parameters["policy_id"]),
        "status": "active",
        "source": "local_fixture",
    }
""",
        encoding="utf-8",
    )
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        f"""
tools:
  - name: policy_status_lookup
    handler: {handler_path.name}:policy_status_lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [customer_id, policy_id]
    denied_parameters: [access_token]
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(tools_yaml)

    result = gateway.request_tool(
        tool_name="policy_status_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=False,
    )

    assert result.executed is True
    assert result.approval_state.state == ApprovalStatus.GRANTED
    assert result.result is not None
    assert result.result["status"] == "active"
