from __future__ import annotations

from dataclasses import dataclass


SUPPORTED_QUESTION = "What is the reimbursement rule for travel meals?"
UNSUPPORTED_QUESTION = "What discount should we give this customer next year?"
TOOL_REQUIRED_QUESTION = "Look up customer policy status before answering."


@dataclass(frozen=True)
class DemoScenario:
    name: str
    question: str


DEMO_SCENARIOS = (
    DemoScenario("supported", SUPPORTED_QUESTION),
    DemoScenario("unsupported", UNSUPPORTED_QUESTION),
    DemoScenario("tool_required", TOOL_REQUIRED_QUESTION),
)
