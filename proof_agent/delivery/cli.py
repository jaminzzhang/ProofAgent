from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any

import typer

from proof_agent import __version__
from proof_agent.contracts import EvaluationReleaseDecisionStatus
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.demo.scenarios import (
    REACT_DEMO_SCENARIOS,
    SUPPORTED_QUESTION,
)
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.frozen_bundles import (
    freeze_evaluation_subject_bundle,
    verify_evaluation_subject_bundle,
)
from proof_agent.observability.storage.run_store import RunStore

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.worker import (
        KnowledgeWorkerResult,
        KnowledgeWorkerTaskOutcome,
    )

app = typer.Typer(no_args_is_help=True)
evaluate_app = typer.Typer(no_args_is_help=True)
campaign_app = typer.Typer(no_args_is_help=True)
app.add_typer(evaluate_app, name="evaluate")
evaluate_app.add_typer(campaign_app, name="campaign")

DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
REACT_DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
PUBLIC_EXAMPLE_PATH = Path("examples/insurance_customer_service/agent.yaml")
DEV_PROCESS_POLL_SECONDS = 0.5


def run_with_langgraph(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so evaluation CLI commands do not import runtime execution paths."""

    from proof_agent.runtime.langgraph_runner import run_with_langgraph as _run_with_langgraph

    return _run_with_langgraph(*args, **kwargs)


def run_harness_rag(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-compare CLI commands do not import runtime execution paths."""

    from proof_agent.evaluation.compare.harness_rag import run_harness_rag as _run_harness_rag

    return _run_harness_rag(*args, **kwargs)


def run_plain_rag(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-compare CLI commands do not import compare helpers."""

    from proof_agent.evaluation.compare.plain_rag import run_plain_rag as _run_plain_rag

    return _run_plain_rag(*args, **kwargs)


@app.callback()
def load_environment() -> None:
    """Load local environment variables before running any CLI command."""

    _load_local_dotenv()


@app.command()
def dev(
    port: int = typer.Option(8000, "--port", help="Port to serve the API on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the API to"),
    history_dir: str = typer.Option("runs/history", "--history-dir", help="Run history directory"),
    config_dir: str = typer.Option("runs/config", "--config-dir", help="Local configuration store"),
    worker_poll_interval_seconds: float = typer.Option(
        2.0,
        "--worker-poll-interval",
        min=0.01,
        help="Seconds to wait after an idle knowledge worker poll.",
    ),
    no_worker: bool = typer.Option(
        False,
        "--no-worker",
        help="Start only the API server. Intended for targeted debugging.",
    ),
) -> None:
    """Start local backend development services."""

    specs = _dev_process_specs(
        host=host,
        port=port,
        history_dir=history_dir,
        config_dir=config_dir,
        worker_poll_interval_seconds=worker_poll_interval_seconds,
        no_worker=no_worker,
    )
    typer.echo("Starting Proof Agent local backend dev services")
    typer.echo("Loaded local .env before spawning dev services.")
    _run_dev_processes(specs)


@app.command()
def demo() -> None:
    """Run the deterministic supported, unsupported, and approval-wait scenarios."""

    typer.echo("Proof Agent demo")
    store = RunStore(Path("runs/history"))
    for scenario in REACT_DEMO_SCENARIOS:
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


@evaluate_app.command("analyze")
def evaluate_analyze(
    suite: str = typer.Option(..., "--suite", help="Evaluation Suite YAML path"),
    subjects: str = typer.Option(..., "--subjects", help="Evaluation Subject Manifest YAML path"),
    output_dir: str = typer.Option(
        "runs/evaluations",
        "--output-dir",
        help="Directory for Evaluation Analysis artifacts",
    ),
) -> None:
    """Analyze completed governed run artifacts without creating Agent runs."""

    try:
        summary = analyze_evaluation(
            suite_path=Path(suite),
            subjects_path=Path(subjects),
            output_dir=Path(output_dir),
        )
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if summary.artifact_dir is not None:
        typer.echo(f"Report: {summary.artifact_dir / 'evaluation_report.md'}")
        typer.echo(f"Results: {summary.artifact_dir / 'evaluation_results.jsonl'}")
        typer.echo(f"Receipt: {summary.artifact_dir / 'evaluation_analysis_receipt.md'}")
    typer.echo(
        "Governed Resolution Rate: "
        f"{summary.passed_required_cases}/{summary.total_required_cases} "
        f"({summary.governed_resolution_rate:.3f})"
    )
    typer.echo(f"Release Decision: {summary.release_decision.status.value}")
    if summary.release_decision.blocking_reasons:
        typer.echo(
            "Release Blocking Reasons: "
            + ", ".join(summary.release_decision.blocking_reasons)
        )
    if summary.release_decision.status == EvaluationReleaseDecisionStatus.BLOCKED:
        raise typer.Exit(code=1)


@campaign_app.command("run")
def evaluate_campaign_run(
    campaign: str = typer.Option(..., "--campaign", help="Evaluation Campaign YAML path"),
    output_dir: str = typer.Option(
        "runs/evaluation_campaigns",
        "--output-dir",
        help="Directory for Evaluation Campaign artifacts",
    ),
) -> None:
    """Run a manifest-driven Evaluation Campaign over declared subjects."""

    try:
        summary = run_evaluation_campaign(
            campaign_path=Path(campaign),
            output_dir=Path(output_dir),
        )
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Campaign: {summary.campaign_id}")
    typer.echo(f"Readiness: {summary.readiness_status.value}")
    typer.echo(f"Artifacts: {summary.artifact_dir}")
    typer.echo(f"Governed Resolution Rate: {summary.governed_resolution_rate:.3f}")
    if summary.blocking_reasons:
        typer.echo("Blocking Reasons: " + ", ".join(summary.blocking_reasons))
    if summary.readiness_status.value == "blocked":
        raise typer.Exit(code=1)


@evaluate_app.command("freeze-bundle")
def evaluate_freeze_bundle(
    suite: str = typer.Option(..., "--suite", help="Evaluation Suite YAML path"),
    subjects: str = typer.Option(..., "--subjects", help="Evaluation Subject Manifest YAML path"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for frozen bundles"),
    bundle_id: str = typer.Option(..., "--bundle-id", help="Frozen bundle id"),
    version: str = typer.Option(..., "--version", help="Frozen bundle version"),
) -> None:
    """Freeze evaluation inputs into a portable post-run subject bundle."""

    try:
        bundle = freeze_evaluation_subject_bundle(
            suite_path=Path(suite),
            subjects_path=Path(subjects),
            output_dir=Path(output_dir),
            bundle_id=bundle_id,
            version=version,
        )
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Bundle: {bundle.bundle_dir}")
    typer.echo(f"Suite: {bundle.suite_path}")
    typer.echo(f"Subjects: {bundle.subject_manifest_path}")
    typer.echo(f"Manifest: {bundle.bundle_manifest_path}")
    typer.echo(f"Artifacts: {bundle.artifact_count}")


@evaluate_app.command("verify-bundle")
def evaluate_verify_bundle(
    bundle_dir: str = typer.Argument(..., help="Frozen Evaluation Subject Bundle directory"),
) -> None:
    """Verify hashes for a frozen post-run subject bundle."""

    try:
        verification = verify_evaluation_subject_bundle(Path(bundle_dir))
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Bundle Integrity: {verification.status}")
    typer.echo(f"Checked Artifacts: {verification.checked_artifact_count}")
    if verification.missing_artifacts:
        typer.echo("Missing Artifacts: " + ", ".join(verification.missing_artifacts))
    if verification.mismatched_artifacts:
        typer.echo("Mismatched Artifacts: " + ", ".join(verification.mismatched_artifacts))
    if verification.status == "failed":
        raise typer.Exit(code=1)


@app.command("config-reset")
def config_reset(
    scope: str | None = typer.Option(None, "--scope"),
    config_dir: str = typer.Option("runs/config", "--config-dir"),
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Clear generated local Configuration Store state."""

    if scope != "local-store":
        typer.echo("Supported reset scope: local-store", err=True)
        raise typer.Exit(code=2)
    if not yes:
        typer.echo("Pass --yes to clear the local Configuration Store.", err=True)
        raise typer.Exit(code=2)

    path = Path(config_dir)
    if path.exists():
        import shutil

        shutil.rmtree(path)
    typer.echo(f"cleared local configuration store: {path}")


@app.command()
def server(
    port: int = typer.Option(8000, "--port", help="Port to serve the API on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    history_dir: str = typer.Option("runs/history", "--history-dir", help="Run history directory"),
    config_dir: str = typer.Option("runs/config", "--config-dir", help="Local configuration store"),
    seed_example_agent: bool = typer.Option(
        True,
        "--seed-example-agent/--no-seed-example-agent",
        help="Import and publish the canonical Insurance Customer Service Agent when absent.",
    ),
) -> None:
    """Start the Proof Agent API server."""

    try:
        import uvicorn
    except ImportError:
        typer.echo(
            "Dashboard dependencies not installed. Run: uv pip install proof-agent[dashboard]"
        )
        raise typer.Exit(code=1) from None

    from proof_agent.observability.api.app import create_app
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore

    configuration_store = LocalAgentConfigurationStore(Path(config_dir))
    if seed_example_agent and _seed_default_dev_agent(configuration_store):
        typer.echo("Seeded local configuration with insurance_customer_service.")

    app = create_app(
        history_dir=Path(history_dir),
        agent_configuration_store=configuration_store,
        agent_configuration_dir=Path(config_dir),
    )
    typer.echo(f"Starting Proof Agent API server at http://{host}:{port}")
    typer.echo("To start the frontends in development mode, run:")
    typer.echo("  Dashboard: cd dashboard && npm run dev (port 5173)")
    typer.echo("  Unified Chat: cd chat && npm run dev (port 5174, /operator and /customer)")
    uvicorn.run(app, host=host, port=port)


@app.command("knowledge-worker")
def knowledge_worker(
    config_dir: str = typer.Option("runs/config", "--config-dir"),
    once: bool = typer.Option(False, "--once"),
    poll_interval_seconds: float = typer.Option(
        5.0,
        "--poll-interval",
        min=0.01,
        help="Seconds to wait after an idle continuous worker poll.",
    ),
) -> None:
    """Process persisted Local Index knowledge ingestion tasks."""

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
        if once:
            result = worker.run_once()
        else:
            typer.echo("knowledge worker started")
            try:
                worker.run_continuously(
                    poll_interval_seconds=poll_interval_seconds,
                    report_result=_echo_continuous_knowledge_worker_result,
                )
            except KeyboardInterrupt:
                pass
            typer.echo("knowledge worker stopped")
            return
    except ImportError:
        typer.echo(
            "Knowledge worker dependencies not installed. Run: "
            "uv run --extra ingestion --extra tree proof-agent knowledge-worker",
            err=True,
        )
        raise typer.Exit(code=1) from None
    except ProofAgentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    _echo_knowledge_worker_result(result)


def main() -> None:
    app()


def _load_local_dotenv() -> None:
    try:
        from dotenv import find_dotenv
        from dotenv import load_dotenv
    except ImportError:
        return
    dotenv_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path if dotenv_path else None)


def _dev_process_specs(
    *,
    host: str,
    port: int,
    history_dir: str,
    config_dir: str,
    worker_poll_interval_seconds: float,
    no_worker: bool,
) -> list[tuple[str, list[str]]]:
    command_prefix = [sys.executable, "-m", "proof_agent.delivery.cli"]
    specs = [
        (
            "api",
            [
                *command_prefix,
                "server",
                "--host",
                host,
                "--port",
                str(port),
                "--history-dir",
                history_dir,
                "--config-dir",
                config_dir,
            ],
        )
    ]
    if not no_worker:
        specs.append(
            (
                "knowledge-worker",
                [
                    *command_prefix,
                    "knowledge-worker",
                    "--config-dir",
                    config_dir,
                    "--poll-interval",
                    str(worker_poll_interval_seconds),
                ],
            )
        )
    return specs


def _run_dev_processes(specs: list[tuple[str, list[str]]]) -> None:
    processes: list[tuple[str, subprocess.Popen[bytes]]] = []
    try:
        for name, command in specs:
            typer.echo(f"starting {name}: {' '.join(command)}")
            processes.append((name, subprocess.Popen(command, env=os.environ.copy())))
        while True:
            for name, process in processes:
                exit_code = process.poll()
                if exit_code is not None:
                    typer.echo(f"{name} exited with code {exit_code}", err=exit_code != 0)
                    _terminate_dev_processes(
                        [
                            (other_name, other_process)
                            for other_name, other_process in processes
                            if other_process is not process
                        ]
                    )
                    raise typer.Exit(code=exit_code)
            time.sleep(DEV_PROCESS_POLL_SECONDS)
    except KeyboardInterrupt:
        typer.echo("stopping Proof Agent local backend dev services")
        _terminate_dev_processes(processes)
        raise typer.Exit(code=0) from None
    except Exception:
        _terminate_dev_processes(processes)
        raise


def _seed_default_dev_agent(store: Any) -> bool:
    """Publish the canonical customer-facing example into an empty local workspace."""

    agent_id = "insurance_customer_service"
    if store.get_active_version(agent_id) is not None:
        return False
    if not PUBLIC_EXAMPLE_PATH.exists():
        return False

    from proof_agent.configuration.importer import import_agent_package

    draft = import_agent_package(PUBLIC_EXAMPLE_PATH, store=store, actor="proof-agent-dev")
    store.publish_version(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="local_dev_seed",
        actor="proof-agent-dev",
    )
    return True


def _terminate_dev_processes(processes: list[tuple[str, subprocess.Popen[bytes]]]) -> None:
    for _name, process in processes:
        if process.poll() is None:
            process.terminate()
    for name, process in processes:
        if process.poll() is not None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            typer.echo(f"forcing {name} to stop", err=True)
            process.kill()
            process.wait()


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


def _echo_continuous_knowledge_worker_result(result: KnowledgeWorkerResult | None) -> None:
    if result is not None:
        _echo_knowledge_worker_result(result)


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


if __name__ == "__main__":
    main()
