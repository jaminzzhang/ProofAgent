"""One-shot Local Index knowledge ingestion worker orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import sleep as _sleep
from typing import Literal, Protocol

from proof_agent.capabilities.knowledge.ingestion.configuration import (
    ingestion_model_config_from_build_spec,
)
from proof_agent.capabilities.knowledge.ingestion.contracts import (
    KnowledgeWorkerDiagnostic,
    KnowledgeWorkerTaskClaim,
    ParsedKnowledgeDocument,
)
from proof_agent.capabilities.knowledge.ingestion.parsers import parse_quarantined_upload
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.bootstrap.model_resolution import resolve_model_role_config
from proof_agent.contracts import (
    KnowledgeArtifactBuildSpec,
    KnowledgeIngestionJob,
    ModelCallRole,
    ModelConfig,
)
from proof_agent.errors import ProofAgentError

_LOST_OWNERSHIP_ERROR_CODE = "PA_INGESTION_004"
_BUILD_ERROR_CODE = "PA_INGESTION_003"


@dataclass(frozen=True)
class KnowledgeRevisionArtifactBuildResult:
    """Reusable artifact builder outcome for one immutable document revision."""

    state: Literal["ready", "deferred"]
    artifact_path: str | None = None


class KnowledgeRevisionArtifactBuilder(Protocol):
    """Build or reuse one compatible immutable Local Index artifact."""

    def purge_stale_temporary_artifacts(self) -> None: ...

    def build_or_reuse(
        self,
        *,
        build_spec: KnowledgeArtifactBuildSpec,
        ingestion_model: ModelConfig,
        parsed_text_path: Path,
        ingestion_config_fingerprint: str,
        progress_callback: Callable[[], None],
    ) -> KnowledgeRevisionArtifactBuildResult: ...


class RecoverableKnowledgeArtifactBuildError(Exception):
    """Known temporary builder failure that may be retried with persisted backoff."""


class HybridClaimedTaskHandler(Protocol):
    """Provider-specific handler for a task already claimed by the unified queue."""

    def __call__(self, task: KnowledgeWorkerTaskClaim) -> KnowledgeWorkerTaskOutcome: ...


@dataclass(frozen=True)
class KnowledgeWorkerTaskOutcome:
    """Value-safe result for the single task processed by one worker invocation."""

    kind: Literal["quarantine_validation", "artifact_build"]
    task_id: str
    source_id: str
    state: Literal["accepted", "rejected", "ready", "deferred", "retry_scheduled", "failed"]
    error_code: str | None = None
    error_message: str | None = None
    artifact_path: str | None = None


@dataclass(frozen=True)
class KnowledgeWorkerResult:
    """One-shot worker result with an optional task outcome and diagnostics."""

    outcome: KnowledgeWorkerTaskOutcome | None
    diagnostics: tuple[KnowledgeWorkerDiagnostic, ...] = ()


class KnowledgeIngestionWorker:
    """Perform housekeeping, then process at most one persisted ingestion task."""

    def __init__(
        self,
        *,
        store: LocalAgentConfigurationStore,
        artifact_builder: KnowledgeRevisionArtifactBuilder,
        parser: Callable[..., ParsedKnowledgeDocument] = parse_quarantined_upload,
        hybrid_task_handler: HybridClaimedTaskHandler | None = None,
        lease_seconds: int = 300,
    ) -> None:
        self._store = store
        self._artifact_builder = artifact_builder
        self._parser = parser
        self._hybrid_task_handler = hybrid_task_handler
        self._lease_seconds = lease_seconds

    def run_once(self) -> KnowledgeWorkerResult | None:
        """Run bounded housekeeping and process no more than one claimed task."""

        self._store.purge_expired_quarantined_upload_bytes()
        self._artifact_builder.purge_stale_temporary_artifacts()
        selection = self._store.claim_next_knowledge_worker_task(
            lease_seconds=self._lease_seconds,
        )
        if selection.task is None:
            if not selection.diagnostics:
                return None
            return KnowledgeWorkerResult(outcome=None, diagnostics=selection.diagnostics)

        source_id = _claimed_task_source_id(selection.task)
        source = self._store.get_knowledge_source(source_id)
        if source is None:
            raise _lost_ownership("Claimed knowledge task Source projection is missing.")
        outcome = dispatch_claimed_knowledge_task(
            provider=source.provider,
            task=selection.task,
            local_handler=self._process_local_task,
            hybrid_handler=self._hybrid_task_handler,
        )
        return KnowledgeWorkerResult(outcome=outcome, diagnostics=selection.diagnostics)

    def _process_local_task(
        self,
        task: KnowledgeWorkerTaskClaim,
    ) -> KnowledgeWorkerTaskOutcome:
        if task.kind == "quarantine_validation":
            return self._process_quarantine_validation(task)
        return self._process_artifact_build(task)

    def run_continuously(
        self,
        *,
        poll_interval_seconds: float = 5.0,
        report_result: Callable[[KnowledgeWorkerResult | None], None] | None = None,
        sleep: Callable[[float], None] = _sleep,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> None:
        """Keep processing queued work until an explicit stop boundary is reached."""

        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive.")
        while not stop_requested():
            result = self.run_once()
            if report_result is not None:
                report_result(result)
            if result is not None and result.outcome is not None:
                continue
            if stop_requested():
                break
            sleep(poll_interval_seconds)

    def _process_quarantine_validation(
        self,
        task: KnowledgeWorkerTaskClaim,
    ) -> KnowledgeWorkerTaskOutcome:
        upload = task.upload
        if upload is None or upload.claim_token is None:
            raise _lost_ownership("Claimed quarantine-validation task is incomplete.")
        self._renew_upload_claim(upload.source_id, upload.upload_id, upload.claim_token)
        try:
            parsed_document = self._parser(
                self._store.quarantined_knowledge_upload_bytes_path(upload),
                filename=upload.filename,
                content_type=upload.content_type,
            )
        except ProofAgentError as exc:
            if exc.code == _LOST_OWNERSHIP_ERROR_CODE:
                raise
            return self._reject_upload(
                task,
                error_code=exc.code,
                error_message=_short_message(
                    exc.message, fallback="Knowledge upload validation failed."
                ),
            )
        except Exception:
            return self._reject_upload(
                task,
                error_code="PA_INGESTION_002",
                error_message="Knowledge upload validation failed.",
            )
        self._renew_upload_claim(upload.source_id, upload.upload_id, upload.claim_token)
        self._store.accept_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            parsed_document=parsed_document,
            claim_token=upload.claim_token,
        )
        return KnowledgeWorkerTaskOutcome(
            kind=task.kind,
            task_id=upload.upload_id,
            source_id=upload.source_id,
            state="accepted",
        )

    def _process_artifact_build(
        self,
        task: KnowledgeWorkerTaskClaim,
    ) -> KnowledgeWorkerTaskOutcome:
        job = task.ingestion_job
        if job is None or job.claim_token is None:
            raise _lost_ownership("Claimed artifact-build task is incomplete.")
        try:
            self._renew_job_claim(job)
            ingestion_model = ingestion_model_config_from_build_spec(job.artifact_build_spec)
            resolved_ingestion_model = resolve_model_role_config(
                ingestion_model,
                role=ModelCallRole.INGESTION,
                configuration_store=self._store,
                require_runtime_credentials=True,
            ).model_config
            document = self._store.get_knowledge_document(
                source_id=job.source_id,
                document_id=job.document_id,
            )
            if document is None:
                raise ProofAgentError(
                    "PA_INGESTION_003",
                    "Local Index artifact build document projection is missing.",
                    "Retry after restoring the managed document revision.",
                )
            parsed_text_path = self._store.knowledge_document_original_path(document).parent / (
                "parsed-text.txt"
            )
            self._renew_job_claim(job)
            build_result = self._artifact_builder.build_or_reuse(
                build_spec=job.artifact_build_spec,
                ingestion_model=resolved_ingestion_model,
                parsed_text_path=parsed_text_path,
                ingestion_config_fingerprint=job.ingestion_config_fingerprint,
                progress_callback=lambda: self._renew_job_claim(job),
            )
            self._renew_job_claim(job)
        except ProofAgentError as exc:
            if exc.code == _LOST_OWNERSHIP_ERROR_CODE:
                raise
            if exc.code in {"PA_MODEL_002", "PA_MODEL_004"}:
                return self._reschedule_job(job, message=exc.message)
            error_code = (
                "PA_INGESTION_001"
                if exc.code
                in {
                    "PA_INGESTION_001",
                    "PA_MODEL_003",
                    "PA_MODEL_CONNECTION_001",
                    "PA_MODEL_CONNECTION_002",
                }
                else _BUILD_ERROR_CODE
            )
            return self._fail_job(job, error_code=error_code, message=exc.message)
        except (RecoverableKnowledgeArtifactBuildError, TimeoutError, ConnectionError) as exc:
            return self._reschedule_job(job, message=str(exc))
        except Exception:
            return self._fail_job(
                job,
                error_code=_BUILD_ERROR_CODE,
                message="Local Index artifact build failed.",
            )
        if build_result.state == "deferred":
            deferred = self._store.defer_knowledge_ingestion_job(
                source_id=job.source_id,
                job_id=job.job_id,
                claim_token=job.claim_token,
            )
            return _job_outcome(deferred, state="deferred")
        if not build_result.artifact_path:
            return self._fail_job(
                job,
                error_code=_BUILD_ERROR_CODE,
                message="Local Index artifact builder returned no reusable artifact path.",
            )
        completed = self._store.complete_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=job.claim_token,
            artifact_path=build_result.artifact_path,
        )
        return _job_outcome(completed, state="ready")

    def _reject_upload(
        self,
        task: KnowledgeWorkerTaskClaim,
        *,
        error_code: str,
        error_message: str,
    ) -> KnowledgeWorkerTaskOutcome:
        upload = task.upload
        if upload is None or upload.claim_token is None:
            raise _lost_ownership("Claimed quarantine-validation task is incomplete.")
        rejected = self._store.reject_quarantined_knowledge_upload(
            source_id=upload.source_id,
            upload_id=upload.upload_id,
            claim_token=upload.claim_token,
            error_code=error_code,
            error_message=error_message,
        )
        return KnowledgeWorkerTaskOutcome(
            kind=task.kind,
            task_id=upload.upload_id,
            source_id=upload.source_id,
            state="rejected",
            error_code=rejected.error_code,
            error_message=rejected.error_message,
        )

    def _renew_upload_claim(self, source_id: str, upload_id: str, claim_token: str) -> None:
        self._store.renew_quarantined_knowledge_upload_claim(
            source_id=source_id,
            upload_id=upload_id,
            claim_token=claim_token,
            lease_seconds=self._lease_seconds,
        )

    def _renew_job_claim(self, job: KnowledgeIngestionJob) -> None:
        if job.claim_token is None:
            raise _lost_ownership("Claimed artifact-build task has no claim token.")
        self._store.renew_knowledge_ingestion_job_claim(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=job.claim_token,
            lease_seconds=self._lease_seconds,
        )

    def _reschedule_job(
        self,
        job: KnowledgeIngestionJob,
        *,
        message: str,
    ) -> KnowledgeWorkerTaskOutcome:
        if job.claim_token is None:
            raise _lost_ownership("Claimed artifact-build task has no claim token.")
        rescheduled = self._store.reschedule_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=job.claim_token,
            error_code=_BUILD_ERROR_CODE,
            error_message=_short_message(
                message, fallback="Temporary Local Index artifact build failure."
            ),
        )
        return _job_outcome(
            rescheduled,
            state="failed" if rescheduled.state == "failed" else "retry_scheduled",
        )

    def _fail_job(
        self,
        job: KnowledgeIngestionJob,
        *,
        error_code: str,
        message: str,
    ) -> KnowledgeWorkerTaskOutcome:
        if job.claim_token is None:
            raise _lost_ownership("Claimed artifact-build task has no claim token.")
        failed = self._store.fail_knowledge_ingestion_job(
            source_id=job.source_id,
            job_id=job.job_id,
            claim_token=job.claim_token,
            error_code=error_code,
            error_message=_short_message(message, fallback="Local Index artifact build failed."),
        )
        return _job_outcome(failed, state="failed")


def _job_outcome(
    job: KnowledgeIngestionJob,
    *,
    state: Literal["ready", "deferred", "retry_scheduled", "failed"],
) -> KnowledgeWorkerTaskOutcome:
    error_code = job.error_code
    error_message = job.error_message
    if state in {"retry_scheduled", "failed"}:
        error_code = error_code or job.last_error_code
        error_message = error_message or job.last_error_message
    return KnowledgeWorkerTaskOutcome(
        kind="artifact_build",
        task_id=job.job_id,
        source_id=job.source_id,
        state=state,
        error_code=error_code,
        error_message=error_message,
        artifact_path=job.artifact_path,
    )


def dispatch_claimed_knowledge_task(
    *,
    provider: str,
    task: KnowledgeWorkerTaskClaim,
    local_handler: Callable[[KnowledgeWorkerTaskClaim], KnowledgeWorkerTaskOutcome],
    hybrid_handler: HybridClaimedTaskHandler | None,
) -> KnowledgeWorkerTaskOutcome:
    """Dispatch one already-owned task without importing Hybrid code on Local jobs."""

    if provider == "local_index":
        return local_handler(task)
    if provider == "hybrid_index":
        if hybrid_handler is None:
            raise ProofAgentError(
                "PA_HYBRID_WORKER_001",
                "Hybrid Index worker handler is not configured.",
                "Configure the private Hybrid parser worker before processing this Source.",
            )
        return hybrid_handler(task)
    raise ProofAgentError(
        "PA_INGESTION_001",
        "Claimed Knowledge Source provider is not supported by the ingestion worker.",
        "Use a supported provider-specific worker handler.",
    )


def _claimed_task_source_id(task: KnowledgeWorkerTaskClaim) -> str:
    if task.upload is not None and task.ingestion_job is None:
        return task.upload.source_id
    if task.ingestion_job is not None and task.upload is None:
        return task.ingestion_job.source_id
    raise _lost_ownership("Claimed knowledge task payload is incomplete or ambiguous.")


def _short_message(message: str, *, fallback: str) -> str:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    if not first_line or first_line.startswith("Traceback"):
        return fallback
    return first_line[:500]


def _lost_ownership(message: str) -> ProofAgentError:
    return ProofAgentError(
        "PA_INGESTION_004",
        message,
        "Retry after refreshing the persisted knowledge ingestion state.",
    )
