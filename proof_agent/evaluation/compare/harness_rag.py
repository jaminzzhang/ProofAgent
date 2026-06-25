from __future__ import annotations

from pathlib import Path

from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)
from proof_agent.evaluation.compare.result import RagResult


DEFAULT_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")


def run_harness_rag(question: str, *, agent_yaml: Path = DEFAULT_AGENT_PATH) -> RagResult:
    """Run the governed path used to compare Proof Agent against plain RAG."""

    result = execute_agent_package_run(
        AgentPackageRunRequest(
            agent_yaml=agent_yaml,
            question=question,
            runs_dir=Path("runs/compare"),
        )
    )
    return RagResult(outcome=result.outcome.value, message=result.final_output)
