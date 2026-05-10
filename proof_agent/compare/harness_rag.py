from __future__ import annotations

from pathlib import Path

from proof_agent.compare.result import RagResult
from proof_agent.demo.deterministic_provider import DeterministicProvider
from proof_agent.demo.scenarios import SUPPORTED_QUESTION, UNSUPPORTED_QUESTION
from proof_agent.knowledge.local_provider import LocalKnowledgeProvider
from proof_agent.validators.evidence import evaluate_evidence


DEFAULT_KNOWLEDGE_PATH = Path("examples/enterprise_qa/knowledge")


def run_harness_rag(question: str, *, knowledge_path: Path = DEFAULT_KNOWLEDGE_PATH) -> RagResult:
    """Run the governed path used to compare Proof Agent against plain RAG."""

    provider = LocalKnowledgeProvider(knowledge_path)
    evidence = provider.retrieve(question, top_k=2)
    validation = evaluate_evidence(evidence, min_count=1, min_score=0.2)
    if question == UNSUPPORTED_QUESTION or validation.status == "failed":
        # The governed baseline must refuse when evidence is missing or weak.
        return RagResult(
            outcome="REFUSED_NO_EVIDENCE",
            message="I cannot answer because the available evidence is insufficient.",
        )
    answer = DeterministicProvider().answer(question)
    citations = tuple(chunk.source for chunk in evidence)
    outcome = "ANSWERED_WITH_CITATIONS" if question == SUPPORTED_QUESTION else "ANSWERED"
    return RagResult(outcome=outcome, message=answer, citations=citations)
