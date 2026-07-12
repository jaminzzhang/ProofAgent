from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any
from collections.abc import Mapping

import pytest

from proof_agent.capabilities.tools.brave_search import BraveSearchRequest
from proof_agent.contracts import ApprovalStatus
from proof_agent.capabilities.tools.gateway import ToolGateway
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.errors import ProofAgentError


def test_local_python_tool_handler_is_rejected(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: unsafe_local_tool
    handler: ./tools.py:run
    risk_level: low
    requires_approval: false
    read_only: true
    allowed_parameters: []
    denied_parameters: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "local Python tool handlers are not supported" in exc.value.message


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


def test_mcp_tool_contract_snapshot_metadata_loads_without_runtime_handler(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id, customer_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id, customer_id]
    result_schema:
      type: object
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    gateway = ToolGateway.from_file(tools_yaml, configuration_store=store)

    config = gateway.tools["claim_status_lookup"]
    assert config.source == "mcp"
    assert config.tool_source_id == "tool_mcp_claims_http"
    assert config.mcp_tool_name == "claim.status.lookup"
    assert config.mcp_contract_snapshot["digest"] == "sha256:contract"
    assert config.input_schema["required"] == ("claim_id", "customer_id")
    assert config.result_schema["required"] == ("claim_id", "status")
    assert config.summary_fields == ("claim_id", "status")
    assert config.result_authority == "authoritative_read"


def test_mcp_read_tool_executes_through_gateway_runtime_transport(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    seen_requests: list[Any] = []

    def transport(request: Any) -> Mapping[str, Any]:
        seen_requests.append(request)
        return {
            "claim_id": request.arguments["claim_id"],
            "status": "open",
            "internal_note": "raw MCP payload must not reach planner summary",
        }

    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(
        tools_yaml,
        configuration_store=store,
        tool_source_env={"CLAIMS_MCP_TOKEN": "secret-token"},
        mcp_tool_transport=transport,
    )

    result = gateway.request_tool(
        tool_name="claim_status_lookup",
        parameters={"claim_id": "CLM-001"},
        approved=False,
    )

    assert result.executed is True
    assert result.approval_state.state == ApprovalStatus.GRANTED
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.mcp_tool_name == "claim.status.lookup"
    assert request.arguments == {"claim_id": "CLM-001"}
    assert request.connection.trace_safe_metadata["endpoint_host"] == "mcp.example.internal"
    assert request.connection.http_headers == {"Authorization": "Bearer secret-token"}
    assert result.result is not None
    assert result.result["provider"] == "mcp"
    assert result.result["tool_source_id"] == "tool_mcp_claims_http"
    assert result.result["tool_contract_id"] == "claim_status_lookup"
    assert result.result["mcp_tool_name"] == "claim.status.lookup"
    assert result.result["contract_snapshot_digest"] == "sha256:contract"
    assert result.result["result_schema_validation"] == "passed"
    assert result.result["result_classification"] == "authorized_tool_result"
    assert result.result["summary_fields"] == ("claim_id", "status")
    assert result.result["summary"] == {"claim_id": "CLM-001", "status": "open"}
    assert "internal_note" not in str(result.result)
    assert "secret-token" not in str(result.result)


def test_mcp_tool_result_schema_type_mismatch_fails_closed(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )

    def transport(_request: Any) -> Mapping[str, Any]:
        return {"claim_id": "CLM-001", "status": 7}

    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      properties:
        claim_id:
          type: string
        status:
          type: string
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(
        tools_yaml,
        configuration_store=store,
        tool_source_env={"CLAIMS_MCP_TOKEN": "secret-token"},
        mcp_tool_transport=transport,
    )

    with pytest.raises(ProofAgentError) as exc:
        gateway.request_tool(
            tool_name="claim_status_lookup",
            parameters={"claim_id": "CLM-001"},
            approved=False,
        )

    assert exc.value.code == "PA_TOOL_SOURCE_002"
    assert "result_schema validation" in exc.value.message


def test_mcp_tool_input_schema_required_parameter_missing_fails_before_call(
    tmp_path: Path,
) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_http",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref="CLAIMS_MCP_TOKEN",
        params={
            "transport": "http",
            "server_label": "claims_mcp",
            "endpoint": "https://mcp.example.internal",
            "auth": {"type": "bearer_env", "env": "CLAIMS_MCP_TOKEN"},
        },
        actor="operator",
    )
    seen_requests: list[Any] = []

    def transport(request: Any) -> Mapping[str, Any]:
        seen_requests.append(request)
        return {"claim_id": "CLM-001", "status": "open"}

    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id, customer_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id, customer_id]
    result_schema:
      type: object
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(
        tools_yaml,
        configuration_store=store,
        tool_source_env={"CLAIMS_MCP_TOKEN": "secret-token"},
        mcp_tool_transport=transport,
    )

    with pytest.raises(ProofAgentError) as exc:
        gateway.request_tool(
            tool_name="claim_status_lookup",
            parameters={"claim_id": "CLM-001"},
            approved=False,
        )

    assert exc.value.code == "PA_TOOL_001"
    assert "missing required parameter(s): customer_id" in exc.value.message
    assert seen_requests == []


def test_mcp_stdio_read_tool_executes_with_default_sdk_transport(
    tmp_path: Path,
) -> None:
    server_path = Path("proof_agent/evaluation/demo/fixtures/mcp_servers/claims_mcp_server.py")
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_mcp_claims_stdio",
        name="Claims MCP",
        source_type="mcp_server",
        provider="mcp",
        tool_contract_ids=("claim_status_lookup",),
        credential_env_ref=None,
        params={
            "transport": "stdio",
            "server_label": "claims_mcp_stdio",
            "command": sys.executable,
            "args": [str(server_path), "--transport", "stdio"],
        },
        actor="operator",
    )
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_stdio
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      properties:
        claim_id:
          type: string
        status:
          type: string
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )
    gateway = ToolGateway.from_file(tools_yaml, configuration_store=store)

    result = gateway.request_tool(
        tool_name="claim_status_lookup",
        parameters={"claim_id": "CLM-001"},
        approved=False,
    )

    assert result.executed is True
    assert result.result is not None
    assert result.result["provider"] == "mcp"
    assert result.result["summary"] == {"claim_id": "CLM-001", "status": "open"}


def test_mcp_http_read_tool_executes_with_default_sdk_transport(
    tmp_path: Path,
) -> None:
    server_path = Path("proof_agent/evaluation/demo/fixtures/mcp_servers/claims_mcp_server.py")
    port = _unused_tcp_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(server_path),
            "--transport",
            "streamable-http",
            "--port",
            str(port),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_tcp_port("127.0.0.1", port, process)
        store = LocalAgentConfigurationStore(tmp_path / "config")
        store.create_tool_source(
            source_id="tool_mcp_claims_http",
            name="Claims MCP",
            source_type="mcp_server",
            provider="mcp",
            tool_contract_ids=("claim_status_lookup",),
            credential_env_ref=None,
            params={
                "transport": "http",
                "server_label": "claims_mcp_http",
                "endpoint": f"http://127.0.0.1:{port}/mcp",
            },
            actor="operator",
        )
        tools_yaml = tmp_path / "tools.yaml"
        tools_yaml.write_text(
            """
tools:
  - name: claim_status_lookup
    source: mcp
    tool_source_id: tool_mcp_claims_http
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
      imported_at: "2026-06-20T00:00:00Z"
      input_schema_digest: sha256:input
      result_schema_digest: sha256:result
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      properties:
        claim_id:
          type: string
        status:
          type: string
      required: [claim_id, status]
    summary_fields: [claim_id, status]
    result_authority: authoritative_read
""",
            encoding="utf-8",
        )
        gateway = ToolGateway.from_file(tools_yaml, configuration_store=store)

        result = gateway.request_tool(
            tool_name="claim_status_lookup",
            parameters={"claim_id": "CLM-HTTP-001"},
            approved=False,
        )
    finally:
        _stop_process(process)

    assert result.executed is True
    assert result.result is not None
    assert result.result["provider"] == "mcp"
    assert result.result["summary"] == {
        "claim_id": "CLM-HTTP-001",
        "status": "open",
    }


def test_mcp_action_tool_is_rejected_from_initial_release(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: create_service_ticket
    source: mcp
    mcp_tool_name: ticket.create
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: high
    requires_approval: true
    read_only: false
    allowed_parameters: [subject, idempotency_key]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [subject, idempotency_key]
    result_schema:
      type: object
      required: [ticket_id]
    summary_fields: [ticket_id]
    side_effect_class: create_ticket
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "only read-only MCP tools are supported" in exc.value.message


def test_mcp_tool_contract_requires_import_snapshot(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP tools require mcp_contract_snapshot" in exc.value.message


def test_mcp_tool_contract_snapshot_requires_digest(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      imported_at: "2026-06-20T00:00:00Z"
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP contract snapshot requires digest" in exc.value.message


def test_mcp_tool_contract_requires_summary_fields(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP tools require summary_fields" in exc.value.message


def test_mcp_tool_contract_requires_summary_fields_list(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: claim_id
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "summary_fields must be a list" in exc.value.message


def test_mcp_tool_contract_requires_result_schema(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP tools require result_schema" in exc.value.message


def test_mcp_tool_contract_requires_input_schema(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP tools require input_schema" in exc.value.message


def test_mcp_tool_contract_requires_mcp_tool_name(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
    result_authority: authoritative_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP tools require mcp_tool_name" in exc.value.message


def test_mcp_read_tool_contract_requires_result_authority(tmp_path: Path) -> None:
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: claim_status_lookup
    source: mcp
    mcp_tool_name: claim.status.lookup
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [claim_id]
    denied_parameters: [access_token]
    input_schema:
      type: object
      required: [claim_id]
    result_schema:
      type: object
      required: [claim_id]
    summary_fields: [claim_id]
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(tools_yaml)

    assert exc.value.code == "PA_TOOL_001"
    assert "MCP read tools require result_authority" in exc.value.message


def test_mcp_tool_contract_rejects_non_mcp_tool_source(tmp_path: Path) -> None:
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
    tools_yaml = tmp_path / "tools.yaml"
    tools_yaml.write_text(
        """
tools:
  - name: untrusted_web_search
    source: mcp
    tool_source_id: tool_brave_default
    mcp_tool_name: search.query
    mcp_contract_snapshot:
      digest: sha256:contract
    risk_level: medium
    requires_approval: false
    read_only: true
    allowed_parameters: [query, max_results]
    denied_parameters: [api_key, access_token]
    input_schema:
      type: object
      required: [query]
    result_schema:
      type: object
      required: [results]
    summary_fields: [results]
    result_authority: advisory_read
""",
        encoding="utf-8",
    )

    with pytest.raises(ProofAgentError) as exc:
        ToolGateway.from_file(
            tools_yaml,
            configuration_store=store,
            tool_source_env={"BRAVE_SEARCH_API_KEY": "secret-token"},
        )

    assert exc.value.code == "PA_TOOL_SOURCE_001"
    assert "MCP tools require an MCP Tool Source" in exc.value.message


def test_untrusted_web_search_tool_rejects_unsearchable_sanitized_query(tmp_path: Path) -> None:
    store = LocalAgentConfigurationStore(tmp_path / "config")
    store.create_tool_source(
        source_id="tool_brave_default",
        name="Brave Search Default",
        source_type="search_vendor",
        provider="brave_search",
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_API_KEY",
        params={},
        actor="operator",
    )
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

    def forbidden_transport(request: BraveSearchRequest) -> Mapping[str, Any]:
        raise AssertionError(f"unsafe query reached transport: {request.query}")

    gateway = ToolGateway.from_file(
        tools_yaml,
        configuration_store=store,
        tool_source_env={"BRAVE_SEARCH_API_KEY": "secret-token"},
        brave_search_transport=forbidden_transport,
    )

    with pytest.raises(ProofAgentError, match="not safe to search"):
        gateway.request_tool(
            tool_name="untrusted_web_search",
            parameters={"query": "CUST-12345 CLM-98765", "max_results": 3},
            approved=False,
        )


def _unused_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_tcp_port(
    host: str,
    port: int,
    process: subprocess.Popen[str],
    *,
    timeout_seconds: float = 10.0,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            _, stderr = process.communicate(timeout=1)
            raise AssertionError(f"MCP server exited early: {stderr}")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.05)
    _stop_process(process)
    raise AssertionError(f"MCP server did not listen on {host}:{port}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate(timeout=5)
