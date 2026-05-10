from __future__ import annotations

from pathlib import Path

from proof_agent.compare.result import RagResult
from proof_agent.workflow.orchestrator import run_enterprise_qa


DEFAULT_AGENT_PATH = Path("examples/enterprise_qa/agent.yaml")


def run_harness_rag(question: str, *, agent_yaml: Path = DEFAULT_AGENT_PATH) -> RagResult:
    """Run the governed path used to compare Proof Agent against plain RAG."""

    result = run_enterprise_qa(
        agent_yaml,
        question=question,
        runs_dir=Path("runs/compare"),
    )
    return RagResult(outcome=result.outcome.value, message=result.final_output)
