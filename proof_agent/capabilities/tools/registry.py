from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from proof_agent.capabilities.tools.insurance_read import claim_status_lookup, policy_status_lookup
from proof_agent.capabilities.tools.mcp_mock import customer_lookup


ToolCallable = Callable[[Mapping[str, Any]], dict[str, Any]]


TOOL_REGISTRY: dict[str, ToolCallable] = {
    "claim_status_lookup": claim_status_lookup,
    "customer_lookup": customer_lookup,
    "policy_status_lookup": policy_status_lookup,
}


def get_tool_callable(tool_name: str) -> ToolCallable:
    """Resolve a configured tool name to the local callable implementation."""

    return TOOL_REGISTRY[tool_name]
