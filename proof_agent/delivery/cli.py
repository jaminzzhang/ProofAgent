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
from typing import Any, NoReturn

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
from proof_agent.release.contracts import (
    GateFacts,
    GateResult,
    ProductionCandidateBinding,
    ReleaseGateManifest,
)
from proof_agent.release.assembler import assemble_release_manifest
from proof_agent.release.digests import digest_ref, reject_duplicate_json_keys
from proof_agent.release.gate_engine import evaluate_gate
from proof_agent.release.profile import initial_private_pilot_profile_bytes
from proof_agent.release.verifier import (
    AttestationVerifier,
    EvidenceRootArtifactReader,
    UnavailableAttestationVerifier,
    VerifierInternalError,
    verify_release_manifest,
)

app = typer.Typer(no_args_is_help=True)
evaluate_app = typer.Typer(no_args_is_help=True)
campaign_app = typer.Typer(no_args_is_help=True)
release_app = typer.Typer(no_args_is_help=True)
database_app = typer.Typer(no_args_is_help=True)
artifacts_app = typer.Typer(no_args_is_help=True)
recovery_app = typer.Typer(no_args_is_help=True)
deployment_app = typer.Typer(no_args_is_help=True)
app.add_typer(evaluate_app, name="evaluate")
evaluate_app.add_typer(campaign_app, name="campaign")
app.add_typer(release_app, name="release")
app.add_typer(database_app, name="database")
app.add_typer(artifacts_app, name="artifacts")
app.add_typer(recovery_app, name="recovery")
app.add_typer(deployment_app, name="deployment")

DEMO_AGENT_PATH = Path("proof_agent/evaluation/demo/fixtures/react_enterprise_qa_v3/agent.yaml")
REACT_DEMO_AGENT_PATH = DEMO_AGENT_PATH
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
)
_STRICT_RFC3339 = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\Z"
)


@database_app.command("current")
def database_current(
    dsn: str = typer.Option(
        ...,
        "--dsn",
        envvar="PROOF_AGENT_POSTGRES_DSN",
        help="PostgreSQL DSN; may also be supplied through PROOF_AGENT_POSTGRES_DSN.",
    ),
) -> None:
    """Print the installed Alembic revision without changing the database."""

    from proof_agent.capabilities.persistence.postgres.database import (
        create_postgres_engine,
        current_revision,
    )

    engine = create_postgres_engine(dsn)
    try:
        revision = current_revision(engine)
    except Exception as exc:
        typer.echo(json.dumps({"error": str(exc)}, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()
    typer.echo(json.dumps({"revision": revision}, sort_keys=True))


@database_app.command("check")
def database_check(
    dsn: str = typer.Option(
        ...,
        "--dsn",
        envvar="PROOF_AGENT_POSTGRES_DSN",
        help="PostgreSQL DSN; may also be supplied through PROOF_AGENT_POSTGRES_DSN.",
    ),
) -> None:
    """Fail unless the database is exactly compatible with this application build."""

    from proof_agent.capabilities.persistence.postgres.database import check_database

    try:
        result = check_database(dsn)
    except Exception as exc:
        typer.echo(json.dumps({"error": str(exc)}, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "current_revision": result.current_revision,
                "head_revision": result.head_revision,
                "status": "compatible",
            },
            sort_keys=True,
        )
    )


@database_app.command("upgrade")
def database_upgrade(
    dsn: str = typer.Option(
        ...,
        "--dsn",
        envvar="PROOF_AGENT_POSTGRES_DSN",
        help="PostgreSQL DSN; may also be supplied through PROOF_AGENT_POSTGRES_DSN.",
    ),
    lock_timeout_seconds: float = typer.Option(
        30.0,
        "--lock-timeout-seconds",
        min=0.001,
        help="Maximum wait for the global PostgreSQL migration lock.",
    ),
    locked: bool = typer.Option(
        False,
        "--locked",
        help="Acknowledge that this one-shot job must own the global migration lock.",
    ),
    expand_only: bool = typer.Option(
        False,
        "--expand-only",
        help="Reject any migration revision not declared safe for the rollback window.",
    ),
    target: str | None = typer.Option(
        None,
        "--target",
        help="Exact candidate schema revision; production requires the packaged head.",
    ),
) -> None:
    """Run the explicit locked expand-only migration path."""

    from proof_agent.capabilities.persistence.postgres.database import (
        head_revision,
        upgrade_database,
    )

    if os.environ.get("PROOF_AGENT_MODE", "development").strip() == "production" and (
        not locked or not expand_only or target is None
    ):
        typer.echo(
            json.dumps(
                {
                    "error": (
                        "production migration requires --locked --expand-only "
                        "--target RELEASE_SCHEMA"
                    )
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        revision = upgrade_database(
            dsn,
            lock_timeout_seconds=lock_timeout_seconds,
            target_revision=target or head_revision(),
            expand_only=expand_only,
        )
    except Exception as exc:
        typer.echo(json.dumps({"error": str(exc)}, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps({"revision": revision, "status": "upgraded"}, sort_keys=True))


@database_app.command("cutover-metadata-v2")
def database_cutover_metadata_v2(
    dsn: str = typer.Option(
        ...,
        "--dsn",
        envvar="PROOF_AGENT_POSTGRES_DSN",
        help="PostgreSQL DSN; may also be supplied through PROOF_AGENT_POSTGRES_DSN.",
    ),
    lock_timeout_seconds: float = typer.Option(
        30.0,
        "--lock-timeout-seconds",
        min=0.001,
        help="Maximum wait for the global PostgreSQL migration lock.",
    ),
    locked: bool = typer.Option(False, "--locked"),
    maintenance_window_authorized: bool = typer.Option(
        False,
        "--maintenance-window-authorized",
    ),
    application_writes_stopped: bool = typer.Option(
        False,
        "--application-writes-stopped",
    ),
    workers_stopped: bool = typer.Option(False, "--workers-stopped"),
    backup_evidence: Path | None = typer.Option(None, "--backup-evidence"),
    backup_evidence_sha256: str | None = typer.Option(
        None,
        "--backup-evidence-sha256",
    ),
    target: str = typer.Option(
        ...,
        "--target",
        help="Exact candidate schema revision; must be the packaged head.",
    ),
) -> None:
    """Run the explicit stopped-stack Metadata V2 direct-cutover migration."""

    acknowledgements = {
        "--locked": locked,
        "--maintenance-window-authorized": maintenance_window_authorized,
        "--application-writes-stopped": application_writes_stopped,
        "--workers-stopped": workers_stopped,
        "--backup-evidence": backup_evidence is not None,
        "--backup-evidence-sha256": backup_evidence_sha256 is not None,
    }
    missing = tuple(key for key, supplied in acknowledgements.items() if not supplied)
    if missing:
        typer.echo(
            json.dumps(
                {
                    "error": (
                        "Metadata V2 direct cutover requires " + " ".join(missing)
                    )
                },
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=2)

    assert backup_evidence is not None
    assert backup_evidence_sha256 is not None
    try:
        if re.fullmatch(r"[0-9a-f]{64}", backup_evidence_sha256) is None:
            raise ValueError("backup evidence SHA-256 must be lowercase hexadecimal")
        metadata = backup_evidence.stat()
        if not backup_evidence.is_file() or not 1 <= metadata.st_size <= 16 * 1024 * 1024:
            raise ValueError("backup evidence must be a non-empty regular file")
        actual_backup_evidence_sha256 = _sha256(backup_evidence)
        if actual_backup_evidence_sha256 != backup_evidence_sha256:
            raise ValueError("backup evidence SHA-256 does not match")

        from proof_agent.capabilities.persistence.postgres.database import (
            upgrade_database,
        )

        revision = upgrade_database(
            dsn,
            lock_timeout_seconds=lock_timeout_seconds,
            target_revision=target,
            expand_only=False,
            metadata_v2_cutover=True,
        )
    except (OSError, ValueError) as exc:
        typer.echo(json.dumps({"error": str(exc)}, sort_keys=True), err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.echo(json.dumps({"error": str(exc)}, sort_keys=True), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "backup_evidence_sha256": actual_backup_evidence_sha256,
                "revision": revision,
                "status": "metadata_v2_cutover_completed",
            },
            sort_keys=True,
        )
    )


@artifacts_app.command("expire")
def artifacts_expire(
    dsn: str = typer.Option(..., "--dsn", envvar="PROOF_AGENT_POSTGRES_DSN"),
    at: str | None = typer.Option(None, "--at"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    """Preview or apply logical artifact expiry; ordinary visibility ends immediately."""

    from datetime import UTC

    from proof_agent.capabilities.persistence.postgres.bundle import (
        PostgresPersistenceBundle,
    )

    checked_at = datetime.now(UTC) if at is None else _parse_release_checked_at(at)
    bundle = PostgresPersistenceBundle.create(dsn)
    try:
        bound = bundle.artifacts.list_bound_manifests()
        due = sum(
            1
            for item in bound
            if any(
                ref.expires_at is not None and ref.expires_at <= checked_at
                for ref in (
                    item.binding.manifest,
                    *(member.artifact for member in item.manifest.members),
                )
            )
            and item.binding.result_available
        )
        expired = bundle.artifacts.expire_due(now=checked_at) if apply else 0
    finally:
        bundle.close()
    typer.echo(
        json.dumps(
            {
                "apply": apply,
                "checked_at": checked_at.isoformat(),
                "expired": expired,
                "would_expire": due,
            },
            sort_keys=True,
        )
    )


@artifacts_app.command("gc")
def artifacts_gc(
    dsn: str = typer.Option(..., "--dsn", envvar="PROOF_AGENT_POSTGRES_DSN"),
    at: str | None = typer.Option(None, "--at"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    """Preview or collect unreferenced exact versions older than the 24-hour grace."""

    from datetime import UTC

    from proof_agent.observability.artifact_gc import ArtifactGarbageCollector

    checked_at = datetime.now(UTC) if at is None else _parse_release_checked_at(at)
    bundle, store = _production_artifact_authority(dsn)
    try:
        report = ArtifactGarbageCollector(
            store=store,
            repository=bundle.artifacts,
        ).collect(now=checked_at, dry_run=not apply)
    finally:
        store.close()
        bundle.close()
    typer.echo(
        json.dumps(
            {
                "deleted": report.deleted,
                "dry_run": report.dry_run,
                "failed": report.failed,
                "oldest_orphan_age_seconds": report.oldest_orphan_age_seconds,
                "referenced": report.referenced,
                "release_healthy": report.release_healthy,
                "scanned": report.scanned,
            },
            sort_keys=True,
        )
    )
    if not report.release_healthy:
        raise typer.Exit(code=1)


@artifacts_app.command("verify-references")
def artifacts_verify_references(
    dsn: str = typer.Option(..., "--dsn", envvar="PROOF_AGENT_POSTGRES_DSN"),
    at: str = typer.Option(..., "--at"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    """Verify every PostgreSQL-bound exact S3 version and SHA-256."""

    _run_artifact_recovery_verify(dsn=dsn, at=at, apply=apply)


@recovery_app.command("verify")
def recovery_verify(
    dsn: str = typer.Option(..., "--dsn", envvar="PROOF_AGENT_POSTGRES_DSN"),
    at: str = typer.Option(..., "--at"),
    apply: bool = typer.Option(False, "--apply"),
) -> None:
    """Reapply retention when requested and verify combined PostgreSQL/S3 authority."""

    _run_artifact_recovery_verify(dsn=dsn, at=at, apply=apply)


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

    if ctx.invoked_subcommand not in {"release", "deployment"}:
        _load_local_dotenv()


@deployment_app.command("validate-compatibility")
def deployment_validate_compatibility(
    manifest: Path = typer.Option(
        ...,
        "--manifest",
        help="Deployment Compatibility Manifest JSON file.",
    ),
    at: str = typer.Option(
        ...,
        "--at",
        help="Explicit RFC3339 validation time used for the 72-hour evidence limit.",
    ),
) -> None:
    """Validate and hash one concrete production dependency binding."""

    from proof_agent.deployment.compatibility import (
        deployment_compatibility_sha256,
        load_deployment_compatibility_manifest,
    )

    try:
        checked_at = _parse_release_checked_at(at)
        compatibility = load_deployment_compatibility_manifest(
            manifest,
            checked_at=checked_at,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        typer.echo(
            json.dumps(
                {
                    "error_code": "deployment_compatibility_invalid",
                    "status": "invalid",
                },
                sort_keys=True,
            )
        )
        raise typer.Exit(code=2) from None
    typer.echo(
        json.dumps(
            {
                "component_ids": [
                    component.component_id for component in compatibility.components
                ],
                "manifest_sha256": deployment_compatibility_sha256(compatibility),
                "status": "valid",
                "tool_mode": compatibility.tool_mode,
            },
            sort_keys=True,
        )
    )


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
    attestation_root: Path | None = typer.Option(
        None,
        "--attestation-root",
        help="Directory containing detached Evidence attestations",
        show_default=False,
    ),
    trust_policy: Path | None = typer.Option(
        None,
        "--trust-policy",
        help="Deployment-owned Evidence public trust policy JSON file",
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
        if (attestation_root is None) != (trust_policy is None):
            raise ValueError("--attestation-root and --trust-policy must be supplied together")
        attestation_verifier: AttestationVerifier
        if attestation_root is None or trust_policy is None:
            attestation_verifier = UnavailableAttestationVerifier()
        else:
            from proof_agent.release.attestation import (
                load_evidence_attestation_verifier,
            )

            if not attestation_root.is_dir() or not os.access(attestation_root, os.R_OK):
                raise ValueError("--attestation-root must be a readable directory")
            if not trust_policy.is_file() or not os.access(trust_policy, os.R_OK):
                raise ValueError("--trust-policy must be a readable file")
            attestation_verifier = load_evidence_attestation_verifier(
                trust_policy=trust_policy.read_bytes(),
                attestation_root=attestation_root,
                evidence=tuple(
                    evidence
                    for result in release_manifest.results
                    for evidence in result.evidence
                ),
            )
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        _raise_release_cli_error("release_verifier_invalid_input", exc)

    try:
        decision = verify_release_manifest(
            release_manifest,
            checked_at=checked_at,
            artifact_reader=artifact_reader,
            attestation_verifier=attestation_verifier,
        )
    except VerifierInternalError as exc:
        _raise_release_cli_error("release_verifier_internal_error", exc)
    typer.echo(decision.model_dump_json())
    if decision.decision == "NO-GO":
        raise typer.Exit(code=1)


@release_app.command("evaluate-gate")
def release_evaluate_gate(
    candidate: Path = typer.Option(..., "--candidate", help="Candidate Binding JSON file"),
    facts: Path = typer.Option(..., "--facts", help="Raw Gate Facts JSON file"),
    at: str = typer.Option(..., "--at", help="Explicit RFC3339 evaluation time"),
) -> None:
    """Compute one Gate Result from raw facts and the candidate-bound profile."""

    try:
        candidate_raw = candidate.read_bytes()
        facts_raw = facts.read_bytes()
        reject_duplicate_json_keys(candidate_raw)
        reject_duplicate_json_keys(facts_raw)
        bound_candidate = ProductionCandidateBinding.model_validate_json(candidate_raw)
        raw_facts = GateFacts.model_validate_json(facts_raw)
        result = evaluate_gate(
            candidate=bound_candidate,
            gate_id=raw_facts.gate_id,
            evidence=raw_facts.evidence,
            metrics=raw_facts.metrics,
            evaluated_at=_parse_release_checked_at(at),
        )
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        _raise_release_cli_error("release_gate_invalid_input", exc)
    typer.echo(result.model_dump_json())


@release_app.command("bind-candidate")
def release_bind_candidate(
    inventory: Path = typer.Option(
        ...,
        "--inventory",
        help="Immutable build inventory JSON file without policy-controlled fields",
    ),
) -> None:
    """Bind immutable build outputs to the packaged Gate Profile."""

    try:
        raw = inventory.read_bytes()
        reject_duplicate_json_keys(raw)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("build inventory must be a JSON object")
        if "schema_version" in payload or "gate_profile" in payload:
            raise ValueError("build inventory contains policy-controlled fields")
        candidate = ProductionCandidateBinding.model_validate(
            {
                **payload,
                "schema_version": "proofagent.candidate-binding.v2",
                "gate_profile": digest_ref(
                    initial_private_pilot_profile_bytes()
                ).model_dump(mode="json"),
            }
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        _raise_release_cli_error("release_candidate_invalid_input", exc)
    typer.echo(candidate.model_dump_json())


@release_app.command("assemble-manifest")
def release_assemble_manifest(
    candidate: Path = typer.Option(..., "--candidate", help="Candidate Binding JSON file"),
    results: list[Path] = typer.Option(
        ...,
        "--result",
        help="Gate Result JSON file; repeat for each completed Gate",
    ),
    at: str = typer.Option(..., "--at", help="Explicit RFC3339 manifest time"),
) -> None:
    """Assemble a complete fail-closed manifest from partial Gate Results."""

    try:
        candidate_raw = candidate.read_bytes()
        reject_duplicate_json_keys(candidate_raw)
        bound_candidate = ProductionCandidateBinding.model_validate_json(candidate_raw)
        gate_results: list[GateResult] = []
        for result_path in results:
            result_raw = result_path.read_bytes()
            reject_duplicate_json_keys(result_raw)
            gate_results.append(GateResult.model_validate_json(result_raw))
        manifest = assemble_release_manifest(
            candidate=bound_candidate,
            results=gate_results,
            generated_at=_parse_release_checked_at(at),
        )
    except (OSError, UnicodeError, ValidationError, ValueError) as exc:
        _raise_release_cli_error("release_manifest_invalid_input", exc)
    typer.echo(manifest.model_dump_json())


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
) -> None:
    """Start local backend development services."""

    specs = _dev_process_specs(
        host=host,
        port=port,
        history_dir=history_dir,
        config_dir=config_dir,
        reload=reload,
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
    reload: bool = typer.Option(
        False,
        "--reload",
        help="Reload the backend API server when Python source files change.",
    ),
    cleanup: bool = typer.Option(
        True,
        "--cleanup/--no-cleanup",
        help="Stop Proof Agent development processes on verification ports before starting.",
    ),
) -> None:
    """Start a restartable local verification session."""

    npm_path = which("npm")
    if npm_path is None:
        typer.echo("npm not found. Install Node.js/npm before starting frontends.", err=True)
        raise typer.Exit(code=1)

    if cleanup:
        messages = _stop_verify_remote_processes(
            ports=(backend_port, dashboard_port, chat_port, gateway_port),
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
            backend_port=backend_port,
            dashboard_port=dashboard_port,
            chat_port=chat_port,
            gateway_port=gateway_port,
            history_dir=history_dir,
            config_dir=config_dir,
            reload=reload,
        )

        typer.echo("Starting Proof Agent remote verification session")
        typer.echo(f"Local gateway: http://127.0.0.1:{gateway_port}")
        typer.echo(f"Dashboard: http://127.0.0.1:{gateway_port}/")
        typer.echo(f"Operator chat: http://127.0.0.1:{gateway_port}/operator")
        _run_dev_processes(specs)
    finally:
        _restore_optional_env("VITE_CHAT_URL", previous_chat_url)
        _restore_optional_env("VITE_DASHBOARD_URL", previous_dashboard_url)


@app.command()
def demo() -> None:
    """Run the deterministic supported and unsupported scenarios."""

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


@app.command("production-publish-agent")
def production_publish_agent(
    agent: str = typer.Option(..., "--agent", help="Production Agent package YAML path"),
    release_evidence: str = typer.Option(
        ...,
        "--release-evidence",
        help="Exact four-reference Phase F evidence JSON",
    ),
    smoke_question: str = typer.Option(
        ...,
        "--smoke-question",
        help="Bounded online KSS retrieval and cited-answer smoke question",
    ),
) -> None:
    """Verify Phase F, run the exact online path, then atomically activate in PostgreSQL."""

    from proof_agent.bootstrap.production_roles import (
        compose_production_agent_publisher,
    )
    from proof_agent.contracts import AuditActorFacts, KnowledgeReleaseEvidenceSet

    evidence_path = Path(release_evidence)
    composition = None
    try:
        if evidence_path.is_symlink() or not evidence_path.is_file():
            raise ValueError("release evidence must be a regular file")
        content = evidence_path.read_bytes()
        if not 1 <= len(content) <= 1024 * 1024:
            raise ValueError("release evidence is outside its size envelope")
        evidence = KnowledgeReleaseEvidenceSet.model_validate_json(content)
        actor = AuditActorFacts(
            subject=_required_cli_environment("PROOF_AGENT_RELEASE_ACTOR_SUBJECT"),
            identity_provider=_required_cli_environment(
                "PROOF_AGENT_RELEASE_ACTOR_IDENTITY_PROVIDER"
            ),
            session_id=_required_cli_environment("PROOF_AGENT_RELEASE_ACTOR_SESSION_ID"),
        )
        composition = compose_production_agent_publisher()
        publication = composition.publisher.publish(
            agent_manifest_path=Path(agent),
            evidence=evidence,
            smoke_question=smoke_question,
            actor=actor,
        )
    except Exception as exc:
        typer.echo(f"Production Agent publication failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if composition is not None:
            composition.close()
    typer.echo(
        json.dumps(
            {
                "agent_id": publication.version.agent_id,
                "agent_version_id": publication.version.version_id,
                "knowledge_release_record_id": (
                    publication.version.knowledge_release_record.record_id
                    if publication.version.knowledge_release_record is not None
                    else None
                ),
                "validation_run_id": publication.version.validation_run_id,
                "status": "published",
            },
            sort_keys=True,
        )
    )


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

    if os.environ.get("PROOF_AGENT_MODE", "development").strip() == "production":
        if reload:
            typer.echo("production API forbids source reload", err=True)
            raise typer.Exit(code=2)
        from proof_agent.bootstrap.production_roles import (
            create_production_api_application,
        )

        production_app = create_production_api_application()
        typer.echo(f"Starting production Proof Agent API at http://{host}:{port}")
        uvicorn.run(production_app, host=host, port=port)
        return

    from proof_agent.observability.api.app import create_app
    from proof_agent.configuration.local_store import LocalAgentConfigurationStore

    configuration_store = LocalAgentConfigurationStore(
        Path(config_dir),
    )
    if seed_example_agent and _seed_default_dev_agent_or_exit(configuration_store):
        typer.echo("Seeded local configuration with agent_management_insurance_specialist.")

    typer.echo(f"Starting Proof Agent API server at http://{host}:{port}")
    typer.echo("To start the frontends in development mode, run:")
    typer.echo("  Dashboard: cd dashboard && npm run dev (port 5173)")
    typer.echo("  Operator Chat: cd chat && npm run dev (port 5174, /operator)")
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
    configuration_store = LocalAgentConfigurationStore(
        config_dir,
    )
    if seed_example_agent:
        _seed_default_dev_agent_or_exit(configuration_store)

    return create_app(
        history_dir=history_dir,
        agent_configuration_store=configuration_store,
        agent_configuration_dir=config_dir,
    )


@app.command("run-executor")
def run_executor(
    once: bool = typer.Option(
        False,
        "--once",
        help="Process the bounded queue until idle, then exit.",
    ),
    slot: int = typer.Option(1, "--slot", min=1, max=2),
    concurrency: int = typer.Option(5, "--concurrency", min=1, max=5),
    poll_interval_seconds: float = typer.Option(
        0.2,
        "--poll-interval",
        min=0.05,
        max=5.0,
    ),
    health_host: str = typer.Option("127.0.0.1", "--health-host"),
    health_port: int = typer.Option(8001, "--health-port", min=1, max=65535),
) -> None:
    """Run the same-image PostgreSQL-queued production Executor role."""

    from proof_agent.bootstrap.production_roles import compose_production_run_executor

    composition = compose_production_run_executor(
        slot=slot,
        concurrency=concurrency,
        poll_interval_seconds=poll_interval_seconds,
    )
    executor = composition.executor
    role_controller = getattr(composition, "role_controller", None)
    readiness = getattr(composition, "readiness", None)
    health_server = None
    activation_state = _production_activation_state()
    stop_requested = False
    previous_handlers: dict[int, Any] = {}

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True
        if role_controller is not None:
            role_controller.begin_draining()
        executor.stop()

    try:
        if role_controller is not None:
            role_controller.start(background=not once)
        if once:
            if activation_state != "active":
                typer.echo(
                    json.dumps(
                        {
                            "activation_state": activation_state.upper(),
                            "completed_runs": 0,
                        },
                        sort_keys=True,
                    )
                )
                return
            completed = executor.run_until_idle()
            typer.echo(json.dumps({"completed_runs": completed}, sort_keys=True))
            return
        if readiness is not None:
            from proof_agent.delivery.worker_health import WorkerHealthServer

            health_server = WorkerHealthServer(
                readiness=readiness,
                host=health_host,
                port=health_port,
            )
            health_server.start()
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        if role_controller is not None:
            from proof_agent.delivery.worker_health import (
                install_worker_role_deployment_signals,
            )

            previous_handlers.update(
                install_worker_role_deployment_signals(role_controller)
            )
        if activation_state != "active":
            typer.echo(
                json.dumps(
                    {"activation_state": activation_state.upper(), "status": "ready"},
                    sort_keys=True,
                )
            )
            while not stop_requested:
                time.sleep(min(poll_interval_seconds, 1.0))
            return
        activation = executor.activate()
        typer.echo(
            json.dumps(
                {
                    "executor_id": activation.executor_id,
                    "slot": activation.slot,
                    "activation_epoch": activation.activation_epoch,
                    "status": "active",
                },
                sort_keys=True,
            )
        )
        executor.serve()
    finally:
        if health_server is not None:
            health_server.close()
        for restore_signum, previous in previous_handlers.items():
            signal.signal(restore_signum, previous)
        composition.close()


@app.command("serve-static")
def serve_static(
    surface: str = typer.Option(..., "--surface"),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(..., "--port", min=1, max=65535),
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Override the image-owned asset root for verification only.",
    ),
) -> None:
    """Serve one immutable browser surface from the production image."""

    if surface not in {"dashboard", "operator-chat"}:
        typer.echo("--surface must be dashboard or operator-chat", err=True)
        raise typer.Exit(code=2)
    try:
        import uvicorn

        from proof_agent.delivery.static_server import create_static_application

        static_application = create_static_application(
            surface=surface,  # type: ignore[arg-type]
            root=root,
        )
    except (ImportError, OSError, ValueError) as exc:
        typer.echo(f"static server configuration failed: {exc}", err=True)
        raise typer.Exit(code=2) from None
    uvicorn.run(static_application, host=host, port=port)


def _production_activation_state() -> str:
    from proof_agent.contracts import RoleActivationState

    value = os.environ.get("PROOF_AGENT_ACTIVATION_STATE", "").strip().lower()
    try:
        return RoleActivationState(value).value
    except ValueError as exc:
        raise ValueError(
            "PROOF_AGENT_ACTIVATION_STATE must be standby, active or draining"
        ) from exc


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


def _production_artifact_authority(dsn: str) -> tuple[Any, Any]:
    from proof_agent.capabilities.artifacts.s3 import S3ArtifactStore
    from proof_agent.capabilities.persistence.postgres.bundle import (
        PostgresPersistenceBundle,
    )

    bucket = os.environ.get("PROOF_AGENT_ARTIFACT_S3_BUCKET", "").strip()
    if not bucket:
        raise ValueError("PROOF_AGENT_ARTIFACT_S3_BUCKET is required")
    bundle = PostgresPersistenceBundle.create(dsn)
    try:
        store = S3ArtifactStore.from_environment(
            bucket=bucket,
            key_prefix=os.environ.get("PROOF_AGENT_ARTIFACT_S3_KEY_PREFIX", "").strip(),
            endpoint_url=(
                os.environ.get("PROOF_AGENT_ARTIFACT_S3_ENDPOINT", "").strip() or None
            ),
            region_name=(
                os.environ.get("PROOF_AGENT_ARTIFACT_S3_REGION", "").strip() or None
            ),
        )
    except BaseException:
        bundle.close()
        raise
    return bundle, store


def _run_artifact_recovery_verify(*, dsn: str, at: str, apply: bool) -> None:
    from proof_agent.observability.recovery import ArtifactRecoveryVerifier

    checked_at = _parse_release_checked_at(at)
    bundle, store = _production_artifact_authority(dsn)
    try:
        report = ArtifactRecoveryVerifier(
            store=store,
            repository=bundle.artifacts,
        ).verify(now=checked_at, apply=apply)
    finally:
        store.close()
        bundle.close()
    typer.echo(
        json.dumps(
            {
                "apply": apply,
                "checked_at": report.checked_at.isoformat(),
                "corrupt_owner_ids": report.corrupt_owner_ids,
                "expired_owner_count": report.expired_owner_count,
                "owner_count": report.owner_count,
                "reference_count": report.reference_count,
                "valid": report.valid,
                "verified_reference_count": report.verified_reference_count,
            },
            sort_keys=True,
        )
    )
    if not report.valid:
        raise typer.Exit(code=1)


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
    return [
        (
            "api",
            api_command,
        )
    ]


def _verify_remote_process_specs(
    *,
    npm_path: str,
    backend_port: int,
    dashboard_port: int,
    chat_port: int,
    gateway_port: int,
    history_dir: str,
    config_dir: str,
    reload: bool,
) -> list[tuple[str, list[str]]]:
    specs = _dev_process_specs(
        host="127.0.0.1",
        port=backend_port,
        history_dir=history_dir,
        config_dir=config_dir,
        reload=reload,
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


def _stop_verify_remote_processes(*, ports: Iterable[int]) -> list[str]:
    messages: list[str] = []
    seen_pids: set[int] = set()
    candidates = _find_verify_remote_port_listeners(ports)
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
        and manifest.workflow.template == "react_enterprise_qa_v3"
        and manifest.workflow.template_descriptor_version == "react_enterprise_qa.v3"
        and manifest.workflow.stages == ()
        and manifest.react is not None
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


def _required_cli_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


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
