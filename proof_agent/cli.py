import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from shutil import which

import typer

from proof_agent import __version__
from proof_agent.compare.harness_rag import run_harness_rag
from proof_agent.compare.plain_rag import run_plain_rag
from proof_agent.demo.scenarios import DEMO_SCENARIOS, SUPPORTED_QUESTION
from proof_agent.workflow.orchestrator import run_enterprise_qa

app = typer.Typer(no_args_is_help=True)


@app.command()
def demo() -> None:
    """Run the deterministic supported, unsupported, and approval-wait scenarios."""

    typer.echo("Proof Agent demo")
    for scenario in DEMO_SCENARIOS:
        result = run_enterprise_qa(
            Path("examples/enterprise_qa/agent.yaml"),
            question=scenario.question,
            runs_dir=Path("runs/latest"),
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command()
def run(agent_yaml: str, question: str = typer.Option(SUPPORTED_QUESTION, "--question")) -> None:
    """Run one Enterprise QA question through the governed harness."""

    result = run_enterprise_qa(Path(agent_yaml), question=question, runs_dir=Path("runs/latest"))
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
            "ok" if Path("examples/enterprise_qa/agent.yaml").exists() else "missing",
        ),
        (
            "sample knowledge",
            "ok" if Path("examples/enterprise_qa/knowledge").exists() else "missing",
        ),
        ("Docker", "available" if which("docker") else "not found"),
        ("deterministic provider", "ready"),
        ("openai_compatible env", _optional_env_status(("OPENAI_API_KEY", "OPENAI_BASE_URL"))),
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
    harness = run_harness_rag(question)
    typer.echo(f"Comparing {agent_yaml}: {question}")
    typer.echo(f"Plain RAG: {plain.outcome} - {plain.message}")
    typer.echo(f"Harness RAG: {harness.outcome} - {harness.message}")


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


def _inspect_trace(path: Path) -> None:
    events = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
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
