from __future__ import annotations

from proof_agent.compare.result import RagResult
from proof_agent.demo.deterministic_provider import DeterministicProvider
from proof_agent.demo.scenarios import UNSUPPORTED_QUESTION


def run_plain_rag(question: str) -> RagResult:
    """Naive comparison baseline that answers without evidence enforcement."""

    provider = DeterministicProvider()
    if question == UNSUPPORTED_QUESTION:
        # This intentionally loose answer demonstrates the governance gap in compare.
        return RagResult(
            outcome="ANSWERED_LOOSELY",
            message="Suggested discount: 10% next year, based on loose context.",
        )
    return RagResult(outcome="ANSWERED", message=provider.answer(question))
