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
