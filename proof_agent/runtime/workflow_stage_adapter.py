from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.contracts import WorkflowStageResult


class WorkflowStageResultRuntimeAdapter:
    """Convert Workflow Stage Result envelopes into scheduler state updates."""

    def to_state_delta(self, result: WorkflowStageResult) -> dict[str, Any]:
        delta = thaw_state_value(result.continuation)
        public_result = result.model_copy(update={"continuation": {}})
        delta["stage_results"] = [public_result.model_dump(mode="json")]
        return delta


def thaw_state_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_state_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [thaw_state_value(item) for item in value]
    return value
