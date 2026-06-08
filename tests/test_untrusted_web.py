from proof_agent.contracts import (
    ReActActionProposal,
    ReActActionType,
    ReasoningSummary,
    UntrustedWebContext,
    UntrustedWebResult,
)
from proof_agent.control.tools.untrusted_web import sanitize_web_search_query
from proof_agent.runtime.langgraph_runner import run_with_langgraph

from pathlib import Path
import json
import shutil

import yaml


ENTERPRISE_AGENT = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
REACT_AGENT = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")


def test_web_search_query_sanitization_replaces_sensitive_values() -> None:
    result = sanitize_web_search_query(
        "Search CUST-12345 claim CLM-98765 for jia@example.com, "
        "+1 415-555-0199, and https://internal.example.local/cases/42"
    )

    assert result.sanitized_query == (
        "Search [CUSTOMER_ID] claim [RESOURCE_ID] for [CONTACT], "
        "[CONTACT], and [INTERNAL_URL]"
    )
    assert result.sanitization_applied is True
    assert result.sanitization_categories == (
        "contact",
        "customer_id",
        "internal_url",
        "resource_id",
    )
    assert result.searchable is True


def test_web_search_query_sanitization_marks_placeholder_only_query_unsearchable() -> None:
    result = sanitize_web_search_query("CUST-12345 CLM-98765")

    assert result.sanitized_query == "[CUSTOMER_ID] [RESOURCE_ID]"
    assert result.searchable is False


def test_untrusted_web_contracts_are_public_and_distinct_from_evidence() -> None:
    result = UntrustedWebResult(
        title="Public update",
        url="https://example.com/update",
        snippet="A public search result summary.",
        provider="fixture",
        rank=1,
        domain="example.com",
    )
    context = UntrustedWebContext(
        sanitized_query="public update",
        sanitization_applied=False,
        results=(result,),
    )

    assert context.results[0].url.unicode_string() == "https://example.com/update"


def test_untrusted_web_supplement_does_not_change_governed_refusal_outcome(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "enterprise_qa"
    shutil.copytree(ENTERPRISE_AGENT.parent, example_dir)
    handler_path = example_dir / "web_tools.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def untrusted_web_search(parameters: Mapping[str, Any]) -> dict[str, object]:
    return {
        "provider": "fixture",
        "result_count": 1,
        "results": [
            {
                "title": "Public discount benchmark",
                "url": "https://example.com/discounts",
                "snippet": "Public websites mention renewal discounts, but this is not verified.",
                "provider": "fixture",
                "rank": 1,
                "domain": "example.com",
            }
        ],
    }
""",
        encoding="utf-8",
    )
    tools_yaml_path = example_dir / "tools.yaml"
    tools_yaml = yaml.safe_load(tools_yaml_path.read_text(encoding="utf-8"))
    tools_yaml["tools"].append(
        {
            "name": "untrusted_web_search",
            "handler": "./web_tools.py:untrusted_web_search",
            "risk_level": "medium",
            "requires_approval": False,
            "read_only": True,
            "allowed_parameters": ["query", "max_results"],
            "denied_parameters": ["api_key", "access_token"],
        }
    )
    tools_yaml_path.write_text(yaml.safe_dump(tools_yaml, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        example_dir / "agent.yaml",
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path / "runs",
        allow_untrusted_web_supplement=True,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "Network supplement" in result.final_output
    assert "not verified by controlled knowledge" in result.final_output
    assert "Public discount benchmark" in result.final_output
    events = [
        json.loads(line)
        for line in result.trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(
        event["event_type"] == "tool_result"
        and event["payload"].get("tool_name") == "untrusted_web_search"
        for event in events
    )
    assert any(
        event["event_type"] == "final_output_disclosure"
        and event["payload"].get("used_untrusted_web_context") is True
        for event in events
    )


def test_react_untrusted_web_supplement_does_not_change_governed_refusal_outcome(
    tmp_path: Path,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    handler_path = example_dir / "web_tools.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def untrusted_web_search(parameters: Mapping[str, Any]) -> dict[str, object]:
    return {
        "provider": "fixture",
        "result_count": 1,
        "results": [
            {
                "title": "Public discount benchmark",
                "url": "https://example.com/discounts",
                "snippet": "Public websites mention renewal discounts, but this is not verified.",
                "provider": "fixture",
                "rank": 1,
                "domain": "example.com",
            }
        ],
    }
""",
        encoding="utf-8",
    )
    tools_yaml_path = example_dir / "tools.yaml"
    tools_yaml = yaml.safe_load(tools_yaml_path.read_text(encoding="utf-8"))
    tools_yaml["tools"].append(
        {
            "name": "untrusted_web_search",
            "handler": "./web_tools.py:untrusted_web_search",
            "risk_level": "medium",
            "requires_approval": False,
            "read_only": True,
            "allowed_parameters": ["query", "max_results"],
            "denied_parameters": ["api_key", "access_token"],
        }
    )
    tools_yaml_path.write_text(yaml.safe_dump(tools_yaml, sort_keys=False), encoding="utf-8")

    result = run_with_langgraph(
        example_dir / "agent.yaml",
        question="What discount should we give this customer next year?",
        runs_dir=tmp_path / "react_runs",
        allow_untrusted_web_supplement=True,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "Network supplement" in result.final_output
    assert "Public discount benchmark" in result.final_output


def test_react_planner_proposed_untrusted_web_search_remains_untrusted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    example_dir = tmp_path / "react_enterprise_qa_tool"
    shutil.copytree(REACT_AGENT.parent, example_dir)
    handler_path = example_dir / "web_tools.py"
    handler_path.write_text(
        """
from collections.abc import Mapping
from typing import Any


def untrusted_web_search(parameters: Mapping[str, Any]) -> dict[str, object]:
    return {
        "provider": "fixture",
        "result_count": 1,
        "results": [
            {
                "title": "Public renewal discount note",
                "url": "https://example.com/renewals",
                "snippet": "Public snippets discuss renewal discounts.",
                "provider": "fixture",
                "rank": 1,
                "domain": "example.com",
            }
        ],
    }
""",
        encoding="utf-8",
    )
    tools_yaml_path = example_dir / "tools.yaml"
    tools_yaml = yaml.safe_load(tools_yaml_path.read_text(encoding="utf-8"))
    tools_yaml["tools"].append(
        {
            "name": "untrusted_web_search",
            "handler": "./web_tools.py:untrusted_web_search",
            "risk_level": "medium",
            "requires_approval": False,
            "read_only": True,
            "allowed_parameters": ["query", "max_results"],
            "denied_parameters": ["api_key", "access_token"],
        }
    )
    tools_yaml_path.write_text(yaml.safe_dump(tools_yaml, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        "proof_agent.bootstrap.composition.resolve_react_planner",
        lambda _config: _WebSearchPlanner(),
    )

    result = run_with_langgraph(
        example_dir / "agent.yaml",
        question="Search the web for renewal discounts.",
        runs_dir=tmp_path / "react_tool_runs",
        approved=True,
    )

    assert result.outcome == "REFUSED_NO_EVIDENCE"
    assert "Network supplement" in result.final_output
    assert "Public renewal discount note" in result.final_output


class _WebSearchPlanner:
    def plan(self, **_: object) -> ReActActionProposal:
        return ReActActionProposal(
            action_id="act_web_search",
            action_type=ReActActionType.PROPOSE_TOOL_CALL,
            reasoning_summary=ReasoningSummary(
                goal="Provide untrusted public web supplement.",
                observations=("The user explicitly asked for web search.",),
                candidate_actions=(ReActActionType.PROPOSE_TOOL_CALL,),
                selected_action=ReActActionType.PROPOSE_TOOL_CALL,
                rationale_summary="The request is for public web context.",
                risk_flags=("untrusted_web_context",),
                required_evidence=(),
            ),
            parameters={"query": "renewal discounts", "max_results": "3"},
            target_tool_name="untrusted_web_search",
            risk_level="medium",
        )
