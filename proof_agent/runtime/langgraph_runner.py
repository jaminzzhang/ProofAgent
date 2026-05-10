from __future__ import annotations

from pathlib import Path

from proof_agent.contracts import RunResult


def run_with_langgraph(
    agent_yaml: Path,
    *,
    question: str,
    runs_dir: Path,
    approved: bool | None = None,
) -> RunResult:
    """Runtime adapter that keeps LangGraph imports out of the core contracts.

    The MVP orchestrator is plain Python, but this adapter preserves the intended
    runtime boundary for future LangGraph node execution without changing CLI code.
    """

    from proof_agent.workflow.orchestrator import run_enterprise_qa

    return run_enterprise_qa(
        agent_yaml,
        question=question,
        runs_dir=runs_dir,
        approved=approved,
    )
