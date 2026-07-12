from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any, NoReturn

import click
import typer
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError
from typer.core import TyperCommand

from proof_agent import __version__
from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.importer import build_agent_package_contract_bundle
from proof_agent.contracts import EvaluationReleaseDecisionStatus
from proof_agent.delivery.remote_verify_gateway import VERIFY_REMOTE_CHAT_BASE
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.analyzer import analyze_evaluation
from proof_agent.evaluation.campaigns import run_evaluation_campaign
from proof_agent.evaluation.demo.scenarios import (
    REACT_DEMO_SCENARIOS,
    SUPPORTED_QUESTION,
)
from proof_agent.evaluation.errors import EvaluationInputError
from proof_agent.evaluation.frozen_bundles import (
    freeze_evaluation_subject_bundle,
    verify_evaluation_subject_bundle,
)
from proof_agent.evaluation.suites import load_evaluation_suite
from proof_agent.observability.storage.run_store import RunStore
from proof_agent.release.contracts import ReleaseGateManifest
from proof_agent.release.digests import reject_duplicate_json_keys
from proof_agent.release.verifier import (
    EvidenceRootArtifactReader,
    UnavailableAttestationVerifier,
    VerifierInternalError,
    verify_release_manifest,
)

if TYPE_CHECKING:
    from proof_agent.capabilities.knowledge.ingestion.worker import (
        KnowledgeWorkerResult,
        KnowledgeWorkerTaskOutcome,
    )

app = typer.Typer(no_args_is_help=True)
evaluate_app = typer.Typer(no_args_is_help=True)
campaign_app = typer.Typer(no_args_is_help=True)
release_app = typer.Typer(no_args_is_help=True)
app.add_typer(evaluate_app, name="evaluate")
evaluate_app.add_typer(campaign_app, name="campaign")
app.add_typer(release_app, name="release")

DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
REACT_DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa/agent.yaml")
PUBLIC_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "agent_management_insurance_specialist"
    / "agent.yaml"
)
DEV_PROCESS_POLL_SECONDS = 0.5
SERVER_HISTORY_DIR_ENV = "PROOF_AGENT_SERVER_HISTORY_DIR"
SERVER_CONFIG_DIR_ENV = "PROOF_AGENT_SERVER_CONFIG_DIR"
SERVER_SEED_EXAMPLE_AGENT_ENV = "PROOF_AGENT_SERVER_SEED_EXAMPLE_AGENT"
VERIFY_REMOTE_GATEWAY_PORT = 18080
VERIFY_REMOTE_STOP_MARKERS = (
    "proof_agent",
    "proof-agent",
    "uvicorn",
    "python",
    "node",
    "npm",
    "vite",
    "cloudflared",
)
_STRICT_RFC3339 = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


class ReleaseVerifyCommand(TyperCommand):
    """Scope parser-level JSON errors to the release authority command."""

    def make_context(
        self,
        info_name: str | None,
        args: list[str],
        parent: click.Context | None = None,
        **extra: Any,
    ) -> click.Context:
        try:
            return super().make_context(info_name, args, parent=parent, **extra)
        except click.UsageError as exc:
            _raise_release_cli_error("release_verifier_invalid_input", exc)


def agent_package_run_request(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-run CLI commands do not import runtime execution paths."""

    from proof_agent.delivery.agent_package_execution import AgentPackageRunRequest

    return AgentPackageRunRequest(*args, **kwargs)


def execute_agent_package_run(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-run CLI commands do not import runtime execution paths."""

    from proof_agent.delivery.agent_package_execution import (
        execute_agent_package_run as _execute_agent_package_run,
    )

    return _execute_agent_package_run(*args, **kwargs)


def run_harness_rag(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-compare CLI commands do not import runtime execution paths."""

    from proof_agent.evaluation.compare.harness_rag import run_harness_rag as _run_harness_rag

    return _run_harness_rag(*args, **kwargs)


def run_plain_rag(*args: Any, **kwargs: Any) -> Any:
    """Lazy wrapper so non-compare CLI commands do not import compare helpers."""

    from proof_agent.evaluation.compare.plain_rag import run_plain_rag as _run_plain_rag

    return _run_plain_rag(*args, **kwargs)


@app.callback()
def load_environment(ctx: typer.Context) -> None:
    """Load local environment variables before running any CLI command."""

    if ctx.invoked_subcommand != "release":
        _load_local_dotenv()


@release_app.command("verify", cls=ReleaseVerifyCommand)
def release_verify(
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help="Required. Release Gate Manifest JSON file",
        show_default=False,
    ),
    evidence_root: Path | None = typer.Option(
        None,
        "--evidence-root",
        help="Required. Directory containing content-addressed Evidence artifacts",
        show_default=False,
    ),
    at: str | None = typer.Option(
        None,
        "--at",
        help="Required. Explicit RFC3339 verification time",
        show_default=False,
    ),
) -> None:
    """Verify an Initial Private Pilot release manifest offline."""

    try:
        if manifest is None or evidence_root is None or at is None:
            raise ValueError("--manifest, --evidence-root, and --at are required")
        if not manifest.exists() or not manifest.is_file() or not os.access(manifest, os.R_OK):
            raise ValueError("--manifest must be a readable file")
        if (
            not evidence_root.exists()
            or not evidence_root.is_dir()
            or not os.access(evidence_root, os.R_OK)
        ):
            raise ValueError("--evidence-root must be a readable directory")
        checked_at = _parse_release_checked_at(at)
        raw_manifest = manifest.read_text(encoding="utf-8")
        reject_duplicate_json_keys(raw_manifest)
        release_manifest = ReleaseGateManifest.model_validate_json(raw_manifest)
        artifact_reader = EvidenceRootArtifactReader(evidence_root)
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        _raise_release_cli_error("release_verifier_invalid_input", exc)

    try:
        decision = verify_release_manifest(
            release_manifest,
            checked_at=checked_at,
            artifact_reader=artifact_reader,
            attestation_verifier=UnavailableAttestationVerifier(),
        )
    except VerifierInternalError as exc:
        _raise_release_cli_error("release_verifier_internal_error", exc)
    typer.echo(decision.model_dump_json())
    if decision.decision == "NO-GO":
        raise typer.Exit(code=1)


@app.command()
def dev(
    port: int = typer.Option(8000, "--port", help="Port to serve the API on"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind the API to"),
    history_dir: str = typer.Option("runs/history", "--history-dir", help="Run history directory"),
    config_dir: str = typer.Option("runs/config", "--config-dir", help="Local configuration store"),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Reload the backend API server when Python source files change.",
    ),
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
        reload=reload,
        worker_poll_interval_seconds=worker_poll_interval_seconds,
        no_worker=no_worker,
    )
    typer.echo("Starting Proof Agent local backend dev services")
    typer.echo("Loaded local .env before spawning dev services.")
    _run_dev_processes(specs)


@app.command("verify-remote")
def verify_remote(
    backend_port: int = typer.Option(8000, "--backend-port", help="Backend API port"),
    dashboard_port: int = typer.Option(5173, "--dashboard-port", help="Dashboard Vite port"),
    chat_port: int = typer.Option(5174, "--chat-port", help="Unified Chat Vite port"),
    gateway_port: int = typer.Option(
        VERIFY_REMOTE_GATEWAY_PORT,
        "--gateway-port",
        help="Single-entry local verification gateway port",
    ),
    history_dir: str = typer.Option("runs/history", "--history-dir", help="Run history directory"),
    config_dir: str = typer.Option("runs/config", "--config-dir", help="Local configuration store"),
    worker_poll_interval_seconds: float = typer.Option(
        2.0,
        "--worker-poll-interval",
        min=0.01,
        help="Seconds to wait after an idle knowledge worker poll.",
    ),
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Reload the backend API server when Python source files change.",
    ),
    no_worker: bool = typer.Option(
        False,
        "--no-worker",
        help="Start only the API server for targeted backend debugging.",
    ),
    local_only: bool = typer.Option(
        False,
        "--local-only",
        help="Skip the public cloudflared tunnel and expose only the local gateway.",
    ),
    cleanup: bool = typer.Option(
        True,
        "--cleanup/--no-cleanup",
        help="Stop Python/Node/Vite/cloudflared processes on verification ports before starting.",
    ),
) -> None:
    """Start a restartable local and public remote verification session."""

    npm_path = which("npm")
    if npm_path is None:
        typer.echo("npm not found. Install Node.js/npm before starting frontends.", err=True)
        raise typer.Exit(code=1)

    cloudflared_path = None if local_only else which("cloudflared")
    if not local_only and cloudflared_path is None:
        typer.echo(
            "cloudflared not found. Install cloudflared or pass --local-only.",
            err=True,
        )
        raise typer.Exit(code=1)

    if cleanup:
        messages = _stop_verify_remote_processes(
            ports=(backend_port, dashboard_port, chat_port, gateway_port),
            gateway_port=gateway_port,
        )
        for message in messages:
            typer.echo(message)

    previous_chat_url = os.environ.get("VITE_CHAT_URL")
    previous_dashboard_url = os.environ.get("VITE_DASHBOARD_URL")
    os.environ["VITE_CHAT_URL"] = ""
    os.environ["VITE_DASHBOARD_URL"] = ""
    try:
        _build_verify_remote_frontends(npm_path=npm_path)
        specs = _verify_remote_process_specs(
            npm_path=npm_path,
            cloudflared_path=cloudflared_path,
            backend_port=backend_port,
            dashboard_port=dashboard_port,
            chat_port=chat_port,
            gateway_port=gateway_port,
            history_dir=history_dir,
            config_dir=config_dir,
            worker_poll_interval_seconds=worker_poll_interval_seconds,
            reload=reload,
            no_worker=no_worker,
        )

        typer.echo("Starting Proof Agent remote verification session")
        typer.echo(f"Local gateway: http://127.0.0.1:{gateway_port}")
        typer.echo(f"Dashboard: http://127.0.0.1:{gateway_port}/")
        typer.echo(f"Operator chat: http://127.0.0.1:{gateway_port}/operator")
        typer.echo(f"Customer chat: http://127.0.0.1:{gateway_port}/customer")
        if cloudflared_path is not None:
            typer.echo("Public tunnel: waiting for cloudflared to print the quick tunnel URL")
        _run_dev_processes(specs)
    finally:
        _restore_optional_env("VITE_CHAT_URL", previous_chat_url)
        _restore_optional_env("VITE_DASHBOARD_URL", previous_dashboard_url)


@app.command()
def demo() -> None:
    """Run the deterministic supported, unsupported, and approval-wait scenarios."""

    typer.echo("Proof Agent demo")
    store = RunStore(Path("runs/history"))
    for scenario in REACT_DEMO_SCENARIOS:
        result = execute_agent_package_run(
            agent_package_run_request(
                agent_yaml=DEMO_AGENT_PATH,
                question=scenario.question,
                runs_dir=Path("runs/latest"),
                store=store,
            )
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command("react-demo")
def react_demo() -> None:
    """Run deterministic Controlled ReAct Enterprise QA scenarios."""

    typer.echo("Proof Agent ReAct demo")
    store = RunStore(Path("runs/history"))
    for scenario in REACT_DEMO_SCENARIOS:
        result = execute_agent_package_run(
            agent_package_run_request(
                agent_yaml=REACT_DEMO_AGENT_PATH,
                question=scenario.question,
                runs_dir=Path("runs/latest"),
                store=store,
            )
        )
        typer.echo(f"{scenario.name}: {result.outcome.value}")


@app.command()
def run(agent_yaml: str, question: str = typer.Option(SUPPORTED_QUESTION, "--question")) -> None:
    """Run one Enterprise QA question through the governed harness."""

    store = RunStore(Path("runs/history"))
    result = execute_agent_package_run(
        agent_package_run_request(
            agent_yaml=Path(agent_yaml),
            question=question,
            runs_dir=Path("runs/latest"),
            store=store,
        )
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
            "canonical specialist agent.yaml",
            "ok" if PUBLIC_EXAMPLE_PATH.exists() else "missing",
        ),
        (
            "specialist sample knowledge",
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
            "Release Blocking Reasons: " + ", ".join(summary.release_decision.blocking_reasons)
        )
    if summary.release_decision.status == EvaluationReleaseDecisionStatus.BLOCKED:
        raise typer.Exit(code=1)


@evaluate_app.command("run-suite")
def evaluate_run_suite(
    suite: str = typer.Option(..., "--suite", help="Evaluation Suite YAML path or builtin id"),
    agent: str = typer.Option(..., "--agent", help="Agent YAML path to run for each case"),
    output_dir: str = typer.Option(
        "runs/evaluations",
        "--output-dir",
        help="Directory for generated subjects and Evaluation Analysis artifacts",
    ),
) -> None:
    """Run an Evaluation Suite against an Agent and analyze the generated subjects."""

    try:
        loaded_suite = load_evaluation_suite(suite)
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    output_root = Path(output_dir)
    suite_output_dir = output_root / _safe_path_segment(loaded_suite.suite_id)
    artifacts_dir = suite_output_dir / "artifacts"
    subjects_path = suite_output_dir / "evaluation_subjects.yaml"
    agent_path = Path(agent)
    store = RunStore(suite_output_dir / "run_history")
    subject_entries: list[dict[str, Any]] = []

    for case in loaded_suite.cases:
        case_dir_name = _safe_path_segment(case.case_id)
        case_dir = artifacts_dir / case_dir_name
        case_dir.mkdir(parents=True, exist_ok=True)
        result = execute_agent_package_run(
            agent_package_run_request(
                agent_yaml=agent_path,
                question=case.question,
                runs_dir=case_dir,
                store=store,
            )
        )
        response_path = case_dir / "evaluated_response.txt"
        response_path.write_text(str(result.final_output), encoding="utf-8")
        subject_entries.append(
            {
                "case_ref": {"case_id": case.case_id},
                "artifacts": {
                    "trace_ref": _relative_posix(result.trace_path, suite_output_dir),
                    "trace_sha256": _sha256(result.trace_path),
                    "receipt_ref": _relative_posix(result.receipt_path, suite_output_dir),
                    "receipt_sha256": _sha256(result.receipt_path),
                },
                "projections": {
                    "evaluated_response": {
                        "audience": "operator",
                        "ref": _relative_posix(response_path, suite_output_dir),
                        "sha256": _sha256(response_path),
                    }
                },
            }
        )

    suite_output_dir.mkdir(parents=True, exist_ok=True)
    subjects_payload = {
        "manifest_id": f"{loaded_suite.suite_id}_run_subjects",
        "version": loaded_suite.version,
        "suite_id": loaded_suite.suite_id,
        "agent": {"agent_yaml": str(agent_path)},
        "subjects": subject_entries,
    }
    subjects_path.write_text(
        yaml.safe_dump(subjects_payload, sort_keys=False),
        encoding="utf-8",
    )

    try:
        summary = analyze_evaluation(
            suite_path=suite,
            subjects_path=subjects_path,
            output_dir=output_root,
        )
    except EvaluationInputError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    typer.echo(f"Subjects: {subjects_path}")
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
            "Release Blocking Reasons: " + ", ".join(summary.release_decision.blocking_reasons)
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
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Reload the API server when Python source files change.",
    ),
    seed_example_agent: bool = typer.Option(
        True,
        "--seed-example-agent/--no-seed-example-agent",
        help=(
            "Import and publish the canonical Agent Management Insurance Specialist "
            "when absent; reject a stale local version."
        ),
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
    if seed_example_agent and _seed_default_dev_agent_or_exit(configuration_store):
        typer.echo("Seeded local configuration with agent_management_insurance_specialist.")

    typer.echo(f"Starting Proof Agent API server at http://{host}:{port}")
    typer.echo("To start the frontends in development mode, run:")
    typer.echo("  Dashboard: cd dashboard && npm run dev (port 5173)")
    typer.echo("  Unified Chat: cd chat && npm run dev (port 5174, /operator and /customer)")
    if reload:
        os.environ[SERVER_HISTORY_DIR_ENV] = history_dir
        os.environ[SERVER_CONFIG_DIR_ENV] = config_dir
        os.environ[SERVER_SEED_EXAMPLE_AGENT_ENV] = "1" if seed_example_agent else "0"
        reload_dir = Path.cwd() / "proof_agent"
        uvicorn.run(
            "proof_agent.delivery.cli:_create_server_app_from_env",
            factory=True,
            host=host,
            port=port,
            reload=True,
            reload_dirs=[str(reload_dir)] if reload_dir.exists() else None,
        )
        return

    app = create_app(
        history_dir=Path(history_dir),
        agent_configuration_store=configuration_store,
        agent_configuration_dir=Path(config_dir),
    )
    uvicorn.run(app, host=host, port=port)


def _create_server_app_from_env() -> Any:
    """Create the API app for Uvicorn reload subprocesses."""

    from proof_agent.configuration.local_store import LocalAgentConfigurationStore
    from proof_agent.observability.api.app import create_app

    history_dir = Path(os.environ.get(SERVER_HISTORY_DIR_ENV, "runs/history"))
    config_dir = Path(os.environ.get(SERVER_CONFIG_DIR_ENV, "runs/config"))
    seed_example_agent = os.environ.get(SERVER_SEED_EXAMPLE_AGENT_ENV, "1") != "0"
    configuration_store = LocalAgentConfigurationStore(config_dir)
    if seed_example_agent:
        _seed_default_dev_agent_or_exit(configuration_store)

    return create_app(
        history_dir=history_dir,
        agent_configuration_store=configuration_store,
        agent_configuration_dir=config_dir,
    )


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


def _parse_release_checked_at(value: str) -> datetime:
    if _STRICT_RFC3339.fullmatch(value) is None:
        raise ValueError("--at must be a complete timezone-aware RFC3339 datetime")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--at must be timezone-aware")
    return parsed


def _raise_release_cli_error(error: str, cause: Exception) -> NoReturn:
    typer.echo(json.dumps({"error": error}, separators=(",", ":")), err=True)
    raise typer.Exit(code=2) from cause


def _load_local_dotenv() -> None:
    try:
        from dotenv import find_dotenv
        from dotenv import load_dotenv
    except ImportError:
        return
    dotenv_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path if dotenv_path else None)


def _restore_optional_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
        return
    os.environ[name] = value


def _dev_process_specs(
    *,
    host: str,
    port: int,
    history_dir: str,
    config_dir: str,
    reload: bool,
    worker_poll_interval_seconds: float,
    no_worker: bool,
) -> list[tuple[str, list[str]]]:
    command_prefix = [sys.executable, "-m", "proof_agent.delivery.cli"]
    api_command = [
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
    ]
    if reload:
        api_command.append("--reload")
    specs = [
        (
            "api",
            api_command,
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


def _verify_remote_process_specs(
    *,
    npm_path: str,
    cloudflared_path: str | None,
    backend_port: int,
    dashboard_port: int,
    chat_port: int,
    gateway_port: int,
    history_dir: str,
    config_dir: str,
    worker_poll_interval_seconds: float,
    reload: bool,
    no_worker: bool,
) -> list[tuple[str, list[str]]]:
    specs = _dev_process_specs(
        host="127.0.0.1",
        port=backend_port,
        history_dir=history_dir,
        config_dir=config_dir,
        reload=reload,
        worker_poll_interval_seconds=worker_poll_interval_seconds,
        no_worker=no_worker,
    )
    specs.extend(
        [
            (
                "dashboard",
                [
                    npm_path,
                    "run",
                    "preview",
                    "-w",
                    "proof-agent-dashboard",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(dashboard_port),
                ],
            ),
            (
                "chat",
                [
                    npm_path,
                    "run",
                    "preview",
                    "-w",
                    "proof-agent-chat",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(chat_port),
                    "--base",
                    VERIFY_REMOTE_CHAT_BASE,
                ],
            ),
            (
                "verify-gateway",
                [
                    sys.executable,
                    "-m",
                    "proof_agent.delivery.remote_verify_gateway",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(gateway_port),
                    "--backend-origin",
                    f"http://127.0.0.1:{backend_port}",
                    "--dashboard-origin",
                    f"http://127.0.0.1:{dashboard_port}",
                    "--chat-origin",
                    f"http://127.0.0.1:{chat_port}",
                    "--chat-base",
                    VERIFY_REMOTE_CHAT_BASE,
                ],
            ),
        ]
    )
    if cloudflared_path is not None:
        specs.append(
            (
                "cloudflared",
                [
                    cloudflared_path,
                    "tunnel",
                    "--url",
                    f"http://127.0.0.1:{gateway_port}",
                ],
            )
        )
    return specs


def _build_verify_remote_frontends(*, npm_path: str) -> None:
    commands = [
        (
            "dashboard",
            [npm_path, "run", "build", "-w", "proof-agent-dashboard"],
        ),
        (
            "chat",
            [
                npm_path,
                "run",
                "build",
                "-w",
                "proof-agent-chat",
                "--",
                "--base",
                VERIFY_REMOTE_CHAT_BASE,
            ],
        ),
    ]
    for name, command in commands:
        typer.echo(f"building {name}: {' '.join(command)}")
        try:
            subprocess.run(command, env=os.environ.copy(), check=True)
        except subprocess.CalledProcessError as exc:
            typer.echo(f"{name} build exited with code {exc.returncode}", err=True)
            raise typer.Exit(code=exc.returncode) from exc


def _stop_verify_remote_processes(*, ports: Iterable[int], gateway_port: int) -> list[str]:
    messages: list[str] = []
    seen_pids: set[int] = set()
    candidates = [
        *_find_verify_remote_port_listeners(ports),
        *_find_verify_remote_cloudflared_processes(gateway_port),
    ]
    for pid, label, command in candidates:
        if pid in seen_pids:
            continue
        seen_pids.add(pid)
        if pid == os.getpid():
            continue
        if not _verify_remote_process_is_safe_to_stop(command):
            messages.append(f"leaving {label} listener pid {pid}: {command}")
            continue
        if _terminate_verify_remote_process(pid):
            messages.append(f"stopped {label} pid {pid}: {command}")
        else:
            messages.append(f"could not stop {label} pid {pid}: {command}")
    return messages


def _find_verify_remote_port_listeners(ports: Iterable[int]) -> list[tuple[int, str, str]]:
    listeners: list[tuple[int, str, str]] = []
    for port in ports:
        try:
            result = subprocess.run(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fp"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return listeners
        if result.returncode not in (0, 1):
            continue
        pids = {
            int(line[1:])
            for line in result.stdout.splitlines()
            if line.startswith("p") and line[1:].isdigit()
        }
        for pid in sorted(pids):
            listeners.append((pid, f"port {port}", _process_command(pid)))
    return listeners


def _find_verify_remote_cloudflared_processes(gateway_port: int) -> list[tuple[int, str, str]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return []
    if result.returncode != 0:
        return []

    gateway_target = f":{gateway_port}"
    processes: list[tuple[int, str, str]] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        pid_text, separator, command = stripped.partition(" ")
        if not separator or not pid_text.isdigit():
            continue
        lowered = command.lower()
        if (
            "cloudflared" in lowered
            and "tunnel" in lowered
            and "--url" in lowered
            and gateway_target in lowered
        ):
            processes.append((int(pid_text), "cloudflared tunnel", command))
    return processes


def _process_command(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _verify_remote_process_is_safe_to_stop(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in VERIFY_REMOTE_STOP_MARKERS)


def _terminate_verify_remote_process(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return not _process_exists(pid)


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    """Publish the canonical V3 operator Agent or reject stale local state."""

    agent_id = "agent_management_insurance_specialist"
    if not PUBLIC_EXAMPLE_PATH.exists():
        raise ProofAgentError(
            "PA_CONFIG_001",
            f"canonical development Agent package is missing: {PUBLIC_EXAMPLE_PATH}",
            "Install a distribution containing the canonical Agent package or restore it.",
            artifact_path=PUBLIC_EXAMPLE_PATH,
        )
    active_agent_ids = store.list_active_agent_ids()
    if active_agent_ids:
        active = store.get_active_version(agent_id)
        if (
            active_agent_ids == (agent_id,)
            and active is not None
            and _active_dev_seed_is_current(
                store,
                agent_id=agent_id,
                expected_active_version_id=active.version_id,
            )
        ):
            if store.ensure_canonical_seed_authority(
                agent_id=agent_id,
                expected_active_version_id=active.version_id,
            ):
                return False
        _raise_noncanonical_dev_seed_state()

    from proof_agent.configuration.importer import import_agent_package

    draft = import_agent_package(PUBLIC_EXAMPLE_PATH, store=store, actor="proof-agent-dev")
    version = store.publish_canonical_seed_version_if_store_empty(
        agent_id=draft.agent_id,
        draft_id=draft.draft_id,
        validation_run_id="local_dev_seed",
        actor="proof-agent-dev",
    )
    if version is not None:
        return True
    active_agent_ids = store.list_active_agent_ids()
    active = store.get_active_version(agent_id)
    if (
        active_agent_ids == (agent_id,)
        and active is not None
        and _active_dev_seed_is_current(
            store,
            agent_id=agent_id,
            expected_active_version_id=active.version_id,
        )
    ):
        if store.ensure_canonical_seed_authority(
            agent_id=agent_id,
            expected_active_version_id=active.version_id,
        ):
            return False
    _raise_noncanonical_dev_seed_state()


def _seed_default_dev_agent_or_exit(store: Any) -> bool:
    """Render canonical seed failures at a Typer/Uvicorn CLI boundary."""

    try:
        return _seed_default_dev_agent(store)
    except ProofAgentError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None


def _raise_noncanonical_dev_seed_state() -> NoReturn:
    raise ProofAgentError(
        "PA_CONFIG_002",
        (
            "local Agent Configuration Store contains active state outside the "
            "canonical Controlled ReAct V3 development seed"
        ),
        (
            "Run `proof-agent config-reset --scope local-store --yes`, then restart "
            "the local development server so the canonical Agent can be seeded."
        ),
    )


def _active_dev_seed_is_current(
    store: Any,
    *,
    agent_id: str,
    expected_active_version_id: str | None = None,
) -> bool:
    active = store.get_active_version(agent_id)
    if active is None or (
        expected_active_version_id is not None and active.version_id != expected_active_version_id
    ):
        return False
    manifest_path = (
        store.root_dir / "agents" / agent_id / "versions" / active.version_id / "agent.yaml"
    )
    try:
        manifest = load_agent_manifest(manifest_path)
    except ProofAgentError:
        return False
    version = store.get_version(agent_id, active.version_id)
    if version is None:
        return False
    canonical_bundle = build_agent_package_contract_bundle(PUBLIC_EXAMPLE_PATH)
    review_provider = (
        manifest.review.subagent.provider
        if manifest.review is not None and manifest.review.subagent is not None
        else None
    )
    return bool(
        manifest.name == agent_id
        and manifest.workflow.runtime == "controlled_react"
        and manifest.workflow.template == "react_enterprise_qa_v3"
        and manifest.workflow.template_descriptor_version == "react_enterprise_qa.v3"
        and manifest.workflow.checkpointer is None
        and manifest.workflow.stages == ()
        and manifest.react is not None
        and manifest.react.max_plan_rounds == manifest.react.max_steps
        and manifest.react.max_tool_calls == 0
        and manifest.react.planner.provider == "deterministic"
        and review_provider == "deterministic"
        and manifest.model.provider == "deterministic"
        and not manifest.capabilities.tools.enabled
        and manifest.capabilities.tools.file is None
        and manifest.customer is None
        and version.contract_bundle == canonical_bundle
    )


def _safe_path_segment(value: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in value)
    return cleaned.strip("_") or "item"


def _relative_posix(path: Path, base_dir: Path) -> str:
    return path.resolve().relative_to(base_dir.resolve()).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
