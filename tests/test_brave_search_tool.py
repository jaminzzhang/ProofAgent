from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from proof_agent.capabilities.tools.brave_search import (
    BraveSearchRequest,
    create_brave_untrusted_web_search_handler,
)
from proof_agent.contracts import ToolSource, ToolSourceLifecycleState
from proof_agent.errors import ProofAgentError


def _source(
    *,
    lifecycle_state: ToolSourceLifecycleState = ToolSourceLifecycleState.ACTIVE,
) -> ToolSource:
    return ToolSource(
        source_id="tool_brave_default",
        name="Brave Search Default",
        source_type="search_vendor",
        provider="brave_search",
        lifecycle_state=lifecycle_state,
        tool_contract_ids=("untrusted_web_search",),
        credential_env_ref="BRAVE_SEARCH_API_KEY",
        params={"timeout_seconds": 8, "default_max_results": 3},
        config_revision=2,
        created_at="2026-06-08T00:00:00Z",
        updated_at="2026-06-08T00:00:00Z",
    )


def test_brave_search_handler_normalizes_untrusted_web_results() -> None:
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
                        "age": "Jun 8, 2026",
                    },
                    {
                        "title": "Ignored over max",
                        "url": "https://example.net/articles/2",
                        "description": "Second snippet.",
                    },
                ]
            }
        }

    handler = create_brave_untrusted_web_search_handler(
        _source(),
        env={"BRAVE_SEARCH_API_KEY": "secret-token"},
        transport=transport,
    )

    result = handler({"query": "public renewal discount", "max_results": 1})

    assert seen[0].query == "public renewal discount"
    assert seen[0].count == 1
    assert seen[0].api_key == "secret-token"
    assert seen[0].timeout_seconds == 8
    assert result["provider"] == "brave_search"
    assert result["tool_source_id"] == "tool_brave_default"
    assert result["tool_source_config_revision"] == 2
    assert result["result_count"] == 1
    assert result["results"] == [
        {
            "title": "Brave result",
            "url": "https://example.com/articles/1",
            "snippet": "Public snippet from Brave.",
            "provider": "brave_search",
            "rank": 1,
            "domain": "example.com",
            "published_at": "Jun 8, 2026",
        }
    ]
    assert "secret-token" not in str(result)


def test_brave_search_handler_rejects_missing_env_ref_without_transport_call() -> None:
    called = False

    def transport(request: BraveSearchRequest) -> Mapping[str, Any]:
        nonlocal called
        called = True
        return {}

    handler = create_brave_untrusted_web_search_handler(
        _source(),
        env={},
        transport=transport,
    )

    with pytest.raises(ProofAgentError) as error:
        handler({"query": "public renewal discount", "max_results": 1})

    assert error.value.code == "PA_TOOL_SOURCE_002"
    assert called is False


def test_brave_search_handler_rejects_archived_tool_source() -> None:
    handler = create_brave_untrusted_web_search_handler(
        _source(lifecycle_state=ToolSourceLifecycleState.ARCHIVED),
        env={"BRAVE_SEARCH_API_KEY": "secret-token"},
        transport=lambda request: {},
    )

    with pytest.raises(ProofAgentError, match="archived"):
        handler({"query": "public renewal discount", "max_results": 1})
