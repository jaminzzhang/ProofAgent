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
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: policy_status_lookup
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
