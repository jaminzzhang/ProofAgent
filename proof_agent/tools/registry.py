from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from proof_agent.tools.mcp_mock import customer_lookup


ToolCallable = Callable[[Mapping[str, Any]], dict[str, Any]]


TOOL_REGISTRY: dict[str, ToolCallable] = {
    "customer_lookup": customer_lookup,
}


def get_tool_callable(tool_name: str) -> ToolCallable:
    """Resolve a configured tool name to the local callable implementation."""

    return TOOL_REGISTRY[tool_name]
