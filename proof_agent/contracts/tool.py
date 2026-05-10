from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import field_validator

from proof_agent.contracts._base import FrozenModel, freeze_value


class ToolRequest(FrozenModel):
    """Tool call intent before execution, including approval and risk metadata."""

    tool_name: str
    action: str
    parameters: Mapping[str, Any]
    risk_level: str
    requested_by_node: str
    requires_approval: bool

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(cls, value: Any) -> Any:
        return freeze_value(value)
