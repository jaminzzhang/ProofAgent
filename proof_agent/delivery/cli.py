from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

import typer

from proof_agent import __version__
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.compare.harness_rag import run_harness_rag
from proof_agent.evaluation.compare.plain_rag import run_plain_rag
from proof_agent.evaluation.demo.scenarios import (
    DEMO_SCENARIOS,
    REACT_DEMO_SCENARIOS,
    SUPPORTED_QUESTION,
)
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.runtime.langgraph_runner import run_with_langgraph

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.worker import (
        KnowledgeWorkerResult,
        KnowledgeWorkerTaskOutcome,
    )

app = typer.Typer(no_args_is_help=True)

DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/enterprise_qa/agent.yaml")
REACT_DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
PUBLIC_EXAMPLE_PATH = Path("examples/insurance_customer_service/agent.yaml")


@app.command()
def demo() -> None:
    """Run the deterministic supported, unsupported, and approval-wait scenarios."""

    typer.echo("Proof Agent demo")
    store = RunStore(Path("runs/history"))
    for scenario in DEMO_SCENARIOS:
        result = run_with_langgraph(
            DEMO_AGENT_PATH,
            question=scenario.question,
            runs_dir=Path("runs/latest"),
            store=store,
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command("react-demo")
def react_demo() -> None:
    """Run deterministic Controlled ReAct Enterprise QA scenarios."""

    typer.echo("Proof Agent ReAct demo")
    store = RunStore(Path("runs/history"))
    for scenario in REACT_DEMO_SCENARIOS:
        result = run_with_langgraph(
            REACT_DEMO_AGENT_PATH,
            question=scenario.question,
            runs_dir=Path("runs/latest"),
            store=store,
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command()
def run(agent_yaml: str, question: str = typer.Option(SUPPORTED_QUESTION, "--question")) -> None:
    """Run one Enterprise QA question through the governed harness."""

    store = RunStore(Path("runs/history"))
    result = run_with_langgraph(
        Path(agent_yaml), question=question, runs_dir=Path("runs/latest"), store=store
    )
    typer.echo(result.final_output)
    typer.echo(f"Outcome: {result.outcome.value}")


@app.command()
def doctor() -> None:
    """Report local readiness for deterministic and remote model provider paths."""

    checks = [
        ("Python", f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        ("Proof Agent", __version__),
        ("runs writable", _writable_status(Path("runs"))),
        (
            "agent.yaml",
            "ok" if PUBLIC_EXAMPLE_PATH.exists() else "missing",
        ),
        (
            "sample knowledge",
            "ok" if (PUBLIC_EXAMPLE_PATH.parent / "knowledge").exists() else "missing",
        ),
        ("Docker", "available" if which("docker") else "not found"),
        ("deterministic provider", "ready"),
        ("openai_compatible env", _optional_env_status(("OPENAI_API_KEY", "OPENAI_BASE_URL"))),
        ("deepseek env", _optional_env_status(("DEEPSEEK_API_KEY",))),
        (
            "azure_openai placeholder env",
            _optional_env_status(("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT")),
        ),
        ("anthropic placeholder env", _optional_env_status(("ANTHROPIC_API_KEY",))),
    ]
    for label, value in checks:
        typer.echo(f"{label}: {value}")


@app.command()
def inspect(path: str) -> None:
    """Summarize a trace JSONL file or Governance Receipt markdown artifact."""

    artifact_path = Path(path)
    if artifact_path.suffix == ".jsonl":
        _inspect_trace(artifact_path)
    else:
        _inspect_receipt(artifact_path)


@app.command()
def compare(agent_yaml: str, question: str = typer.Option(..., "--question")) -> None:
    """Show the behavior gap between plain RAG and the governed harness."""

    plain = run_plain_rag(question)
    harness = run_harness_rag(question, agent_yaml=Path(agent_yaml))
    typer.echo(f"Comparing {agent_yaml}: {question}")
    typer.echo(f"Plain RAG: {plain.outcome} - {plain.message}")
    typer.echo(f"Harness RAG: {harness.outcome} - {harness.message}")


@app.command()
def server(
    port: int = typer.Option(8000, "--port", help="Port to serve the API on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    history_dir: str = typer.Option("runs/history", "--history-dir", help="Run history directory"),
) -> None:
    """Start the Proof Agent API server."""

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # python-dotenv is optional

    try:
        import uvicorn
    except ImportError:
        typer.echo(
            "Dashboard dependencies not installed. Run: uv pip install proof-agent[dashboard]"
        )
        raise typer.Exit(code=1) from None

    from proof_agent.observability.api.app import create_app

    app = create_app(history_dir=Path(history_dir))
    typer.echo(f"Starting Proof Agent API server at http://{host}:{port}")
    typer.echo("To start the frontends in development mode, run:")
    typer.echo("  Dashboard: cd dashboard && npm run dev (port 5173)")
    typer.echo("  Unified Chat: cd chat && npm run dev (port 5174, /operator and /customer)")
    uvicorn.run(app, host=host, port=port)


@app.command("knowledge-worker")
def knowledge_worker(
    config_dir: str = typer.Option("runs/config", "--config-dir"),
    once: bool = typer.Option(False, "--once"),
) -> None:
    """Process at most one persisted Local Index knowledge ingestion task."""

    if not once:
        typer.echo(
            "Continuous knowledge-worker polling is not implemented; pass --once.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        from proof_agent.capabilities.knowledge.ingestion.local_index_builder import (
            LocalIndexRevisionArtifactBuilder,
        )
        from proof_agent.capabilities.knowledge.ingestion.worker import (
            KnowledgeIngestionWorker,
        )
        from proof_agent.configuration.local_store import LocalAgentConfigurationStore

        config_path = Path(config_dir)
        worker = KnowledgeIngestionWorker(
            store=LocalAgentConfigurationStore(config_path),
            artifact_builder=LocalIndexRevisionArtifactBuilder(config_path),
        )
        result = worker.run_once()
    except ImportError:
        typer.echo(
            "Knowledge worker dependencies not installed. Run: "
            "uv run --extra ingestion --extra tree proof-agent knowledge-worker --once",
            err=True,
        )
        raise typer.Exit(code=1) from None
    except ProofAgentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    _echo_knowledge_worker_result(result)


def main() -> None:
    app()


def _writable_status(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".proof_agent_doctor_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError:
        return "not writable"
    return "ok"


def _optional_env_status(names: Iterable[str]) -> str:
    present = [name for name in names if os.environ.get(name)]
    if present:
        return ", ".join(present)
    return "not configured (optional for deterministic demo)"


def _echo_knowledge_worker_result(result: KnowledgeWorkerResult | None) -> None:
    if result is None:
        typer.echo("no queued knowledge tasks")
        return
    for diagnostic in result.diagnostics:
        typer.echo(f"knowledge worker warning: {diagnostic.source_id} ({diagnostic.code})")
    if result.outcome is not None:
        typer.echo(_knowledge_worker_outcome_message(result.outcome))


def _knowledge_worker_outcome_message(outcome: KnowledgeWorkerTaskOutcome) -> str:
    message_by_outcome = {
        ("quarantine_validation", "accepted"): "knowledge upload accepted",
        ("quarantine_validation", "rejected"): "knowledge upload rejected",
        ("artifact_build", "ready"): "knowledge ingestion job ready",
        ("artifact_build", "retry_scheduled"): "knowledge ingestion job retry scheduled",
        ("artifact_build", "deferred"): "knowledge ingestion job deferred",
        ("artifact_build", "failed"): "knowledge ingestion job failed",
    }
    message = f"{message_by_outcome[(outcome.kind, outcome.state)]}: {outcome.task_id}"
    if outcome.error_code is not None:
        return f"{message} ({outcome.error_code})"
    return message


def _inspect_trace(path: Path) -> None:
    events = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    if not events:
        typer.echo("Trace events: 0")
        typer.echo(f"Artifact: {path}")
        return
    redaction_applied = any(event.get("redaction", {}).get("applied") for event in events)
    typer.echo(f"Trace events: {len(events)}")
    typer.echo(f"Run ID: {events[0].get('run_id', 'unknown')}")
    typer.echo(f"First event: {events[0].get('event_type', 'unknown')}")
    typer.echo(f"Last event: {events[-1].get('event_type', 'unknown')}")
    typer.echo(f"Redaction applied: {'yes' if redaction_applied else 'no'}")
    typer.echo(f"Artifact: {path}")


def _inspect_receipt(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    outcome = "unknown"
    for index, line in enumerate(lines):
        if line.strip() == "## Final Outcome":
            for candidate in lines[index + 1 :]:
                if candidate.strip():
                    outcome = candidate.strip()
                    break
            break
    typer.echo(f"Final Outcome: {outcome}")
    typer.echo(f"Artifact: {path}")
