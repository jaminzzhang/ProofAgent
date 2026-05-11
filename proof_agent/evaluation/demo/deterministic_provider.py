from __future__ import annotations

from proof_agent.evaluation.demo.scenarios import (
    SUPPORTED_QUESTION,
    TOOL_REQUIRED_QUESTION,
    UNSUPPORTED_QUESTION,
)


class DeterministicProvider:
    def answer(self, question: str) -> str:
        if question == SUPPORTED_QUESTION:
            return "Travel meals are reimbursed up to 50 USD per day with receipts."
        if question == TOOL_REQUIRED_QUESTION:
            return "Customer policy status requires the approved customer_lookup tool."
        if question == UNSUPPORTED_QUESTION:
            return "A loose RAG answer might guess a discount, but the harness must refuse."
        return "No deterministic answer is configured for this question."
