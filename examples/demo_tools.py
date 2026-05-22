from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def customer_lookup(parameters: Mapping[str, Any]) -> dict[str, str]:
    """Deterministic stand-in for the reference Agents' governed lookup tool."""

    return {
        "customer_id": str(parameters["customer_id"]),
        "policy_id": str(parameters["policy_id"]),
        "status": "active",
        "source": "mcp_mock",
    }
