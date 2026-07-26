"""Real online smoke validation for a production Published Agent candidate."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from proof_agent.contracts import (
    InstitutionAuthorizationContext,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.control.production_agent import ProductionAgentValidationError
from proof_agent.control.production_agent_publication import (
    ProductionAgentCandidateValidation,
)
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.observability.storage.run_store import RunStore


class ProductionOnlineAgentCandidateValidator:
    """Execute the exact production path and retain trace/receipt in immutable S3."""

    _MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

    def __init__(
        self,
        *,
        configuration_store: Any,
        hybrid_runtime: Any,
        guarded_http_client: Any,
        secret_provider: Any,
        model_credential_resolver: Any,
        artifact_store: Any,
        work_root: Path,
        institution_authorization: InstitutionAuthorizationContext,
        execute: Callable[..., Any] = execute_published_agent_run,
    ) -> None:
        self._configuration_store = configuration_store
        self._hybrid_runtime = hybrid_runtime
        self._guarded_http_client = guarded_http_client
        self._secret_provider = secret_provider
        self._model_credential_resolver = model_credential_resolver
        self._artifact_store = artifact_store
        self._work_root = work_root.resolve()
        self._work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._institution_authorization = institution_authorization
        self._execute = execute

    def validate(
        self,
        *,
        agent: PublishedAgent,
        version: Any,
        question: str,
    ) -> ProductionAgentCandidateValidation:
        if agent.agent_version_id != version.version_id:
            raise ProductionAgentValidationError(
                "online candidate version does not match its materialized Agent"
            )
        with TemporaryDirectory(
            prefix="agent-candidate-",
            dir=self._work_root,
        ) as directory:
            root = Path(directory)
            store = RunStore(root / "history")
            execution = self._execute(
                dependencies=RunExecutionDependencies(
                    store=store,
                    runs_dir=root / "latest",
                    configuration_store=self._configuration_store,
                    hybrid_runtime=self._hybrid_runtime,
                    guarded_http_client=self._guarded_http_client,
                    secret_provider=self._secret_provider,
                    model_credential_resolver=self._model_credential_resolver,
                ),
                published_agent=agent,
                question=question,
                run_purpose=RunPurpose.VALIDATION,
                institution_authorization=self._institution_authorization,
                run_id=version.validation_run_id,
            )
            detail = execution.detail
            accepted = tuple(
                chunk
                for chunk in detail.evidence_chunks
                if _status(chunk) == "accepted"
            )
            if (
                detail.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
                or not accepted
                or any(not _citation(chunk) for chunk in accepted)
            ):
                raise ProductionAgentValidationError(
                    "online candidate did not produce accepted, formally cited evidence"
                )
            trace = _read_bounded(execution.result.trace_path, self._MAX_ARTIFACT_BYTES)
            receipt = _read_bounded(
                execution.result.receipt_path,
                self._MAX_ARTIFACT_BYTES,
            )
        trace_ref = self._put_verified(
            key=_validation_key(
                version_id=version.version_id,
                run_id=version.validation_run_id,
                kind="trace",
                content=trace,
                suffix="jsonl",
            ),
            content=trace,
            media_type="application/x-ndjson",
        )
        receipt_ref = self._put_verified(
            key=_validation_key(
                version_id=version.version_id,
                run_id=version.validation_run_id,
                kind="receipt",
                content=receipt,
                suffix="md",
            ),
            content=receipt,
            media_type="text/markdown",
        )
        return ProductionAgentCandidateValidation(
            run_id=version.validation_run_id,
            outcome=detail.outcome,
            accepted_citation_count=len(accepted),
            trace_ref=trace_ref,
            receipt_ref=receipt_ref,
        )

    def _put_verified(self, *, key: str, content: bytes, media_type: str) -> Any:
        ref = self._artifact_store.put_immutable(
            key=key,
            content=content,
            media_type=media_type,
        )
        if self._artifact_store.get_exact(ref) != content:
            raise ProductionAgentValidationError(
                "online candidate artifact failed exact S3 read-back"
            )
        return ref


def _read_bounded(path_value: object, limit: int) -> bytes:
    path = Path(path_value)  # type: ignore[arg-type]
    if path.is_symlink() or not path.is_file():
        raise ProductionAgentValidationError(
            "online candidate artifact is not a regular file"
        )
    size = path.stat().st_size
    if not 1 <= size <= limit:
        raise ProductionAgentValidationError(
            "online candidate artifact is outside its size envelope"
        )
    content = path.read_bytes()
    if len(content) != size:
        raise ProductionAgentValidationError(
            "online candidate artifact changed during retention"
        )
    return content


def _status(chunk: object) -> str:
    value = getattr(chunk, "status", "")
    return str(getattr(value, "value", value))


def _citation(chunk: object) -> str:
    value = getattr(chunk, "citation", None)
    return value.strip() if isinstance(value, str) else ""


def _validation_key(
    *,
    version_id: str,
    run_id: str,
    kind: str,
    content: bytes,
    suffix: str,
) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"agent-validation/{version_id}/{run_id}/{kind}-{digest}.{suffix}"


__all__ = ["ProductionOnlineAgentCandidateValidator"]
