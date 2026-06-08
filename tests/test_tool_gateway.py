from pathlib import Path
from typing import Any
from collections.abc import Mapping

import pytest

from proof_agent.capabilities.tools.brave_search import BraveSearchRequest
from proof_agent.contracts import ApprovalStatus
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


def test_customer_lookup_requires_approval_before_execution() -> None:
    gateway = ToolGateway.from_file("proof_agent/evaluation/demo/fixtures/enterprise_qa/tools.yaml")
    result = gateway.request_tool(
        tool_name="customer_lookup",
        parameters={"customer_id": "CUST-001", "policy_id": "POL-001"},
        approved=False,
    )
    assert result.approval_state.state == ApprovalStatus.REQUESTED
    assert result.executed is False


def test_approved_customer_lookup_executes_mock_tool() -> None:
    gateway = ToolGateway.from_file("proof_agent/evaluation/demo/fixtures/enterprise_qa/tools.yaml")
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


def test_untrusted_web_search_tool_receives_sanitized_query(tmp_path: Path) -> None:
    handler_path = tmp_path / "tool_handlers.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def untrusted_web_search(parameters: Mapping[str, Any]) -> dict[str, object]:
    return {
        "query_seen_by_handler": parameters["query"],
        "max_results_seen_by_handler": parameters["max_results"],
    }
""",
        encoding="utf-8",
    )
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        f"""
tools:
  - name: untrusted_web_search
    handler: {handler_path.name}:untrusted_web_search
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [query, max_results]
    denied_parameters: [api_key, access_token]
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(tools_yaml)

    result = gateway.request_tool(
        tool_name="untrusted_web_search",
        parameters={"query": "Search CUST-12345 travel policy", "max_results": 3},
        approved=False,
    )

    assert result.executed is True
    assert result.result is not None
    assert result.result["query_seen_by_handler"] == "Search [CUSTOMER_ID] travel policy"
    assert result.result["sanitized_query"] == "Search [CUSTOMER_ID] travel policy"
    assert result.result["sanitization_applied"] is True
    assert result.result["sanitization_categories"] == ("customer_id",)


def test_untrusted_web_search_can_bind_dashboard_tool_source(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_brave_default",
        name="Brave Search Default",
        source_type="search_vendor",
        provider="brave_search",
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_API_KEY",
        params={"timeout_seconds": 8, "default_max_results": 3},
        actor="operator",
    )
    seen: list[BraveSearchRequest] = []

    def transport(request: BraveSearchRequest) -> Mapping[str, Any]:
        seen.append(request)
        return {
            "web": {
                "results": [
                    {
                        "title": "Brave result",
                        "url": "https://example.com/articles/1",
                        "description": "Public snippet from Brave.",
                    }
                ]
            }
        }

    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: untrusted_web_search
    tool_source_id: tool_brave_default
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [query, max_results]
    denied_parameters: [api_key, access_token]
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(
        tools_yaml,
        configuration_store=store,
        tool_source_env={"BRAVE_SEARCH_API_KEY": "secret-token"},
        brave_search_transport=transport,
    )

    result = gateway.request_tool(
        tool_name="untrusted_web_search",
        parameters={"query": "Search CUST-12345 travel policy", "max_results": 1},
        approved=False,
    )

    assert result.executed is True
    assert result.result is not None
    assert seen[0].query == "Search [CUSTOMER_ID] travel policy"
    assert result.result["tool_source_id"] == "tool_brave_default"
    assert result.result["results"][0]["provider"] == "brave_search"
    assert result.result["sanitization_applied"] is True
    assert "secret-token" not in str(result.result)


def test_untrusted_web_search_tool_rejects_unsearchable_sanitized_query(tmp_path: Path) -> None:
    handler_path = tmp_path / "tool_handlers.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def untrusted_web_search(parameters: Mapping[str, Any]) -> dict[str, object]:
    raise AssertionError("handler should not execute")
""",
        encoding="utf-8",
    )
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        f"""
tools:
  - name: untrusted_web_search
    handler: {handler_path.name}:untrusted_web_search
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [query, max_results]
    denied_parameters: [api_key, access_token]
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(tools_yaml)

    with pytest.raises(ProofAgentError, match="not safe to search"):
        gateway.request_tool(
            tool_name="untrusted_web_search",
            parameters={"query": "CUST-12345 CLM-98765", "max_results": 3},
            approved=False,
        )
