"""Real online smoke validation for a production Published Agent candidate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.knowledge_release import (
    require_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    ExactArtifactRef,
    FormalProductionAgentCandidate,
    FormalProductionAgentCandidateExternalSmokeResult,
    FormalProductionAgentOnlineSmokeRequest,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentQueryGrantStaging,
    InstitutionAuthorizationContext,
    PublishedAgentRuntimeFacts,
    ReceiptOutcome,
    RunPurpose,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
)
from proof_agent.contracts.artifacts import (
    ArtifactKind,
    ArtifactOwner,
    ArtifactPutRequest,
)
from proof_agent.contracts.ports.artifacts import ArtifactStore
from proof_agent.contracts.ports.knowledge_candidates import (
    KnowledgeCandidateAdmissionError,
    KnowledgeCandidateAdmissionFailureReason,
)
from proof_agent.control.formal_production_agent_candidate import (
    require_formal_production_agent_candidate,
)
from proof_agent.control.production_agent import ProductionAgentValidationError
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration,
)
from proof_agent.control.production_agent_publication import (
    ProductionAgentCandidateValidation,
)
from proof_agent.delivery.published_agent_materializer import (
    PublishedAgentMaterializationError,
    materialize_agent_contract_bundle,
)
from proof_agent.contracts.published_agent import PublishedAgent
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.observability.storage.run_store import RunStore


@dataclass(frozen=True)
class _RetainedOnlineSmoke:
    outcome: ReceiptOutcome
    accepted_citation_count: int
    trace_ref: ExactArtifactRef
    receipt_ref: ExactArtifactRef


_EXTERNAL_SMOKE_DIAGNOSTIC_CODES = frozenset(
    {
        "formal_candidate_external_smoke_kss_failed",
        "formal_candidate_external_smoke_evidence_admission_failed",
        "formal_candidate_external_smoke_model_failed",
        "formal_candidate_external_smoke_citation_validation_failed",
        "formal_candidate_external_smoke_artifact_retention_failed",
    }
)


class FormalCandidateExternalSmokeDiagnosticError(ProductionAgentValidationError):
    """One stable, content-free external-probe stage diagnostic."""

    def __init__(self, code: str, *, reason_code: str | None = None) -> None:
        if code not in _EXTERNAL_SMOKE_DIAGNOSTIC_CODES:
            raise ValueError("external smoke diagnostic code is invalid")
        allowed_reasons = {reason.value for reason in KnowledgeCandidateAdmissionFailureReason}
        if reason_code is not None and (
            code != "formal_candidate_external_smoke_evidence_admission_failed"
            or reason_code not in allowed_reasons
        ):
            raise ValueError("external smoke admission reason code is invalid")
        self.code = code
        self.reason_code = reason_code
        super().__init__(code)


class _GovernedOnlineSmokeRuntime:
    """Run one exact Agent version through governed execution and retain artifacts."""

    _MAX_ARTIFACT_BYTES = 64 * 1024 * 1024

    def __init__(
        self,
        *,
        configuration_store: Any,
        knowledge_candidate_runtime: Any,
        guarded_http_client: Any,
        secret_provider: Any,
        model_credential_resolver: Any,
        artifact_store: ArtifactStore,
        work_root: Path,
        institution_authorization: InstitutionAuthorizationContext,
        execute: Callable[..., Any],
    ) -> None:
        self._configuration_store = configuration_store
        self._knowledge_candidate_runtime = knowledge_candidate_runtime
        self._guarded_http_client = guarded_http_client
        self._secret_provider = secret_provider
        self._model_credential_resolver = model_credential_resolver
        self._artifact_store = artifact_store
        self.work_root = work_root.resolve()
        self.work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._institution_authorization = institution_authorization
        self._execute = execute

    def run(
        self,
        *,
        agent: PublishedAgent,
        version_id: str,
        run_id: str,
        question: str,
        require_successful_citations: bool,
        diagnose_external_failure: bool = False,
    ) -> _RetainedOnlineSmoke:
        if agent.agent_version_id != version_id or agent.validation_run_id != run_id:
            raise ProductionAgentValidationError(
                "online candidate identity does not match its materialized Agent"
            )
        with TemporaryDirectory(
            prefix="agent-candidate-run-",
            dir=self.work_root,
        ) as directory:
            root = Path(directory)
            store = RunStore(root / "history")
            execution = self._execute_with_diagnostics(
                diagnose_external_failure=diagnose_external_failure,
                dependencies=RunExecutionDependencies(
                    store=store,
                    runs_dir=root / "latest",
                    configuration_store=self._configuration_store,
                    knowledge_candidate_runtime=self._knowledge_candidate_runtime,
                    guarded_http_client=self._guarded_http_client,
                    secret_provider=self._secret_provider,
                    model_credential_resolver=self._model_credential_resolver,
                ),
                published_agent=agent,
                question=question,
                run_purpose=RunPurpose.VALIDATION,
                institution_authorization=self._institution_authorization,
                run_id=run_id,
            )
            detail = execution.detail
            accepted = tuple(
                chunk for chunk in detail.evidence_chunks if _status(chunk) == "accepted"
            )
            cited = tuple(chunk for chunk in accepted if _citation(chunk))
            if require_successful_citations and diagnose_external_failure:
                diagnostic_code = _external_smoke_run_failure_code(
                    detail=detail,
                    accepted=accepted,
                    cited=cited,
                )
                if diagnostic_code is not None:
                    raise FormalCandidateExternalSmokeDiagnosticError(
                        diagnostic_code,
                        reason_code=(
                            _external_smoke_admission_reason_code(detail)
                            if diagnostic_code
                            == "formal_candidate_external_smoke_evidence_admission_failed"
                            else None
                        ),
                    )
            if require_successful_citations and (
                detail.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
                or not accepted
                or len(cited) != len(accepted)
            ):
                raise ProductionAgentValidationError(
                    "online candidate did not produce accepted, formally cited evidence"
                )
            source_artifact_failure = False
            try:
                trace = _read_bounded(
                    execution.result.trace_path,
                    self._MAX_ARTIFACT_BYTES,
                )
                receipt = _read_bounded(
                    execution.result.receipt_path,
                    self._MAX_ARTIFACT_BYTES,
                )
            except Exception:
                if not diagnose_external_failure:
                    raise
                source_artifact_failure = True
            if source_artifact_failure:
                raise FormalCandidateExternalSmokeDiagnosticError(
                    "formal_candidate_external_smoke_artifact_retention_failed"
                )
        retained_artifact_failure = False
        try:
            trace_ref = self._put_verified(
                version_id=version_id,
                run_id=run_id,
                artifact_kind=ArtifactKind.RUN_TRACE,
                display_filename=_validation_filename(
                    kind="trace",
                    content=trace,
                    suffix="jsonl",
                ),
                content=trace,
                media_type="application/x-ndjson",
            )
            receipt_ref = self._put_verified(
                version_id=version_id,
                run_id=run_id,
                artifact_kind=ArtifactKind.GOVERNANCE_RECEIPT,
                display_filename=_validation_filename(
                    kind="receipt",
                    content=receipt,
                    suffix="md",
                ),
                content=receipt,
                media_type="text/markdown",
            )
        except Exception:
            if not diagnose_external_failure:
                raise
            retained_artifact_failure = True
        if retained_artifact_failure:
            raise FormalCandidateExternalSmokeDiagnosticError(
                "formal_candidate_external_smoke_artifact_retention_failed"
            )
        return _RetainedOnlineSmoke(
            outcome=detail.outcome,
            accepted_citation_count=len(cited),
            trace_ref=trace_ref,
            receipt_ref=receipt_ref,
        )

    def _execute_with_diagnostics(
        self,
        *,
        diagnose_external_failure: bool,
        **kwargs: Any,
    ) -> Any:
        diagnostic_code: str | None = None
        reason_code: str | None = None
        try:
            return self._execute(**kwargs)
        except Exception as exc:
            diagnostic_code = _external_smoke_execution_failure_code(exc)
            if isinstance(exc, KnowledgeCandidateAdmissionError):
                reason_code = exc.admission_reason_code
            if not diagnose_external_failure or diagnostic_code is None:
                raise
        if diagnostic_code is None:
            raise ProductionAgentValidationError(
                "external smoke diagnostic classification is unavailable"
            )
        raise FormalCandidateExternalSmokeDiagnosticError(
            diagnostic_code,
            reason_code=reason_code,
        )

    def _put_verified(
        self,
        *,
        version_id: str,
        run_id: str,
        artifact_kind: ArtifactKind,
        display_filename: str,
        content: bytes,
        media_type: str,
    ) -> ExactArtifactRef:
        digest = hashlib.sha256(content).hexdigest()
        owner = ArtifactOwner(
            owner_type="agent_validation",
            owner_id=f"{version_id}:{run_id}",
        )
        ref = self._artifact_store.put_immutable(
            ArtifactPutRequest(
                kind=artifact_kind,
                owner=owner,
                content_type=media_type,
                expected_sha256=digest,
                expected_size_bytes=len(content),
                display_filename=display_filename,
            ),
            BytesIO(content),
        )
        if (
            ref.kind is not artifact_kind
            or ref.owner != owner
            or ref.content_type != media_type
            or ref.sha256 != digest
            or ref.size_bytes != len(content)
            or self._artifact_store.head_exact(ref) != ref
        ):
            raise ProductionAgentValidationError(
                "online candidate artifact failed exact S3 read-back"
            )
        with self._artifact_store.open_exact(ref) as stream:
            read_back = stream.read(len(content) + 1)
        if read_back != content:
            raise ProductionAgentValidationError(
                "online candidate artifact failed exact S3 read-back"
            )
        return ExactArtifactRef(
            artifact_uri=self._artifact_store.exact_uri(ref),
            version_id=ref.version_id,
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            media_type=ref.content_type,
        )


class ProductionOnlineAgentCandidateValidator:
    """Execute the exact production path and retain trace/receipt in immutable S3."""

    def __init__(
        self,
        *,
        configuration_store: Any,
        knowledge_candidate_runtime: Any,
        guarded_http_client: Any,
        secret_provider: Any,
        model_credential_resolver: Any,
        artifact_store: ArtifactStore,
        work_root: Path,
        institution_authorization: InstitutionAuthorizationContext,
        execute: Callable[..., Any] = execute_published_agent_run,
    ) -> None:
        self._runtime = _GovernedOnlineSmokeRuntime(
            configuration_store=configuration_store,
            knowledge_candidate_runtime=knowledge_candidate_runtime,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
            artifact_store=artifact_store,
            work_root=work_root,
            institution_authorization=institution_authorization,
            execute=execute,
        )

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
        retained = self._runtime.run(
            agent=agent,
            version_id=version.version_id,
            run_id=version.validation_run_id,
            question=question,
            require_successful_citations=True,
        )
        return ProductionAgentCandidateValidation(
            run_id=version.validation_run_id,
            outcome=retained.outcome,
            accepted_citation_count=retained.accepted_citation_count,
            trace_ref=retained.trace_ref,
            receipt_ref=retained.receipt_ref,
        )


class FormalProductionAgentCandidateExternalSmokeRunner:
    """Probe one exact unpublished Candidate through governed external dependencies."""

    def __init__(
        self,
        *,
        configuration_store: Any,
        knowledge_candidate_runtime: Any,
        guarded_http_client: Any,
        secret_provider: Any,
        model_credential_resolver: Any,
        artifact_store: ArtifactStore,
        work_root: Path,
        institution_authorization: InstitutionAuthorizationContext,
        identifier_factory: Callable[[], str] = lambda: str(uuid4()),
        execute: Callable[..., Any] = execute_published_agent_run,
    ) -> None:
        self._runtime = _GovernedOnlineSmokeRuntime(
            configuration_store=configuration_store,
            knowledge_candidate_runtime=knowledge_candidate_runtime,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
            artifact_store=artifact_store,
            work_root=work_root,
            institution_authorization=institution_authorization,
            execute=execute,
        )
        self._identifier_factory = identifier_factory

    def validate_candidate_external_smoke(
        self,
        candidate: FormalProductionAgentCandidate,
        *,
        question: str,
    ) -> FormalProductionAgentCandidateExternalSmokeResult:
        try:
            validated_candidate = FormalProductionAgentCandidate.model_validate(
                candidate.model_dump(mode="python")
            )
            require_formal_production_agent_candidate(validated_candidate)
            normalized_question = question.strip()
            if not normalized_question or len(normalized_question) > 4_000:
                raise ValueError("external smoke question is invalid")
            validation_run_id = self._identifier_factory().strip()
            version_id = f"formal-candidate-probe-{validated_candidate.formal_candidate_sha256}"
            stage_facts = resolve_workflow_stage_runtime_configuration(
                validated_candidate.contract_bundle.agent_yaml,
                source=WorkflowStageConfigurationRuntimeSource(
                    source_type=(
                        WorkflowStageConfigurationRuntimeSourceType.FORMAL_PRODUCTION_CANDIDATE
                    ),
                    reference=(
                        "external_dependency_probe:"
                        f"{validated_candidate.formal_candidate_sha256}:"
                        f"validation_run:{validation_run_id}"
                    ),
                ),
            )
            if stage_facts is None:
                raise ValueError("external smoke Workflow Stage facts are invalid")

            with TemporaryDirectory(
                prefix="formal-agent-candidate-probe-",
                dir=self._runtime.work_root,
            ) as directory:
                manifest_path = materialize_agent_contract_bundle(
                    validated_candidate.contract_bundle,
                    Path(directory) / "package",
                )
                manifest = load_agent_manifest(
                    manifest_path,
                    require_writable_artifacts=False,
                )
                if manifest.name != validated_candidate.agent_id:
                    raise ValueError("external smoke manifest identity is invalid")
                model_connection_ids = _shared_model_connection_ids(manifest)
                agent = PublishedAgent(
                    agent_id=validated_candidate.agent_id,
                    manifest_path=manifest_path,
                    display_name=validated_candidate.display_name,
                    purpose=validated_candidate.purpose,
                    customer_facing=manifest.customer is not None,
                    agent_version_id=version_id,
                    source_draft_id=validated_candidate.draft_id,
                    validation_run_id=validation_run_id,
                    resolved_knowledge_bindings=(validated_candidate.resolved_knowledge_bindings),
                    runtime_facts=PublishedAgentRuntimeFacts(
                        agent_id=validated_candidate.agent_id,
                        agent_version_id=version_id,
                        workflow_stage_availability=(stage_facts.workflow_stage_availability),
                        effective_stage_configuration=(stage_facts.effective_stage_configuration),
                    ),
                    source="formal_candidate_external_dependency_probe",
                )
                retained = self._runtime.run(
                    agent=agent,
                    version_id=version_id,
                    run_id=validation_run_id,
                    question=normalized_question,
                    require_successful_citations=True,
                    diagnose_external_failure=True,
                )
            return FormalProductionAgentCandidateExternalSmokeResult(
                agent_id=validated_candidate.agent_id,
                draft_id=validated_candidate.draft_id,
                draft_revision=validated_candidate.draft_revision,
                formal_candidate_sha256=(validated_candidate.formal_candidate_sha256),
                knowledge_release_candidate_sha256=(
                    validated_candidate.knowledge_release_candidate_sha256
                ),
                knowledge_base_release_id=(
                    validated_candidate.knowledge_release_candidate.knowledge_base_release_id
                ),
                validation_run_id=validation_run_id,
                model_connection_ids=model_connection_ids,
                outcome=retained.outcome,
                accepted_citation_count=retained.accepted_citation_count,
                trace_ref=retained.trace_ref,
                receipt_ref=retained.receipt_ref,
            )
        except (ProductionAgentValidationError, PublishedAgentMaterializationError):
            raise
        except Exception as exc:
            raise ProductionAgentValidationError(
                "formal candidate external dependency probe failed"
            ) from exc


class FormalProductionAgentOnlineSmokeRunner:
    """Adapt exact formal staging to the governed production Agent run path."""

    def __init__(
        self,
        *,
        configuration_store: Any,
        knowledge_candidate_runtime: Any,
        guarded_http_client: Any,
        secret_provider: Any,
        model_credential_resolver: Any,
        artifact_store: ArtifactStore,
        work_root: Path,
        institution_authorization: InstitutionAuthorizationContext,
        execute: Callable[..., Any] = execute_published_agent_run,
    ) -> None:
        self._runtime = _GovernedOnlineSmokeRuntime(
            configuration_store=configuration_store,
            knowledge_candidate_runtime=knowledge_candidate_runtime,
            guarded_http_client=guarded_http_client,
            secret_provider=secret_provider,
            model_credential_resolver=model_credential_resolver,
            artifact_store=artifact_store,
            work_root=work_root,
            institution_authorization=institution_authorization,
            execute=execute,
        )

    def validate_online_smoke(
        self,
        request: FormalProductionAgentOnlineSmokeRequest,
        *,
        query_grant_staging: FormalProductionAgentQueryGrantStaging,
    ) -> FormalProductionAgentOnlineSmokeResult:
        validated_request, validated_staging = _require_formal_smoke_input(
            request=request,
            query_grant_staging=query_grant_staging,
        )
        provisional = validated_staging.reference_staging.preparation.provisional_version
        try:
            with TemporaryDirectory(
                prefix="formal-agent-candidate-",
                dir=self._runtime.work_root,
            ) as directory:
                manifest_path = materialize_agent_contract_bundle(
                    provisional.contract_bundle,
                    Path(directory) / "package",
                )
                manifest = load_agent_manifest(
                    manifest_path,
                    require_writable_artifacts=False,
                )
                if manifest.name != validated_request.agent_id:
                    raise ProductionAgentValidationError(
                        "formal online smoke manifest identity is invalid"
                    )
                agent = PublishedAgent(
                    agent_id=provisional.agent_id,
                    manifest_path=manifest_path,
                    display_name=provisional.display_name,
                    purpose=provisional.purpose,
                    customer_facing=manifest.customer is not None,
                    agent_version_id=provisional.version_id,
                    source_draft_id=provisional.source_draft_id,
                    validation_run_id=provisional.validation_run_id,
                    resolved_knowledge_bindings=provisional.resolved_knowledge_bindings,
                    runtime_facts=PublishedAgentRuntimeFacts(
                        agent_id=provisional.agent_id,
                        agent_version_id=provisional.version_id,
                        workflow_stage_availability=(provisional.workflow_stage_availability),
                        effective_stage_configuration=(
                            provisional.effective_workflow_stage_configuration
                        ),
                    ),
                    source="formal_production_smoke_candidate",
                )
                retained = self._runtime.run(
                    agent=agent,
                    version_id=validated_request.provisional_version_id,
                    run_id=validated_request.validation_run_id,
                    question=validated_request.smoke_question,
                    require_successful_citations=False,
                )
            return FormalProductionAgentOnlineSmokeResult(
                agent_id=validated_request.agent_id,
                provisional_version_id=validated_request.provisional_version_id,
                validation_run_id=validated_request.validation_run_id,
                release_reference_id=validated_request.release_reference_id,
                outcome=retained.outcome,
                accepted_citation_count=retained.accepted_citation_count,
                trace_ref=retained.trace_ref,
                receipt_ref=retained.receipt_ref,
            )
        except ProductionAgentValidationError:
            raise
        except Exception as exc:
            raise ProductionAgentValidationError("formal online smoke execution failed") from exc


def _require_formal_smoke_input(
    *,
    request: FormalProductionAgentOnlineSmokeRequest,
    query_grant_staging: FormalProductionAgentQueryGrantStaging,
) -> tuple[FormalProductionAgentOnlineSmokeRequest, FormalProductionAgentQueryGrantStaging]:
    try:
        validated_request = FormalProductionAgentOnlineSmokeRequest.model_validate(
            request.model_dump(mode="python")
        )
        validated_staging = FormalProductionAgentQueryGrantStaging.model_validate(
            query_grant_staging.model_dump(mode="python")
        )
        reference_staging = validated_staging.reference_staging
        preparation = reference_staging.preparation
        candidate = preparation.candidate
        provisional = preparation.provisional_version
        release = candidate.knowledge_release_candidate
        reference = reference_staging.release_reference
        require_formal_production_agent_candidate(candidate)
        require_formal_production_agent_phase_f_record(
            record=provisional.phase_f_record,
            candidate=candidate,
        )
        if (
            validated_request.agent_id != candidate.agent_id
            or validated_request.provisional_version_id != provisional.version_id
            or validated_request.validation_run_id != provisional.validation_run_id
            or validated_request.formal_candidate_sha256 != candidate.formal_candidate_sha256
            or validated_request.knowledge_release_candidate_sha256
            != candidate.knowledge_release_candidate_sha256
            or validated_request.knowledge_space_id != release.knowledge_space_id
            or validated_request.knowledge_base_id != release.knowledge_base_id
            or validated_request.knowledge_base_release_id != release.knowledge_base_release_id
            or validated_request.release_reference_id != reference.release_reference_id
        ):
            raise ValueError("formal online smoke input identities must match")
        return validated_request, validated_staging
    except Exception as exc:
        raise ProductionAgentValidationError(
            "formal online smoke input integrity is invalid"
        ) from exc


def _read_bounded(path_value: object, limit: int) -> bytes:
    path = Path(path_value)  # type: ignore[arg-type]
    if path.is_symlink() or not path.is_file():
        raise ProductionAgentValidationError("online candidate artifact is not a regular file")
    size = path.stat().st_size
    if not 1 <= size <= limit:
        raise ProductionAgentValidationError(
            "online candidate artifact is outside its size envelope"
        )
    content = path.read_bytes()
    if len(content) != size:
        raise ProductionAgentValidationError("online candidate artifact changed during retention")
    return content


def _status(chunk: object) -> str:
    value = getattr(chunk, "status", "")
    return str(getattr(value, "value", value))


def _citation(chunk: object) -> str:
    value = getattr(chunk, "citation", None)
    return value.strip() if isinstance(value, str) else ""


def _external_smoke_execution_failure_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if code == "PA_KNOWLEDGE_002":
        return "formal_candidate_external_smoke_kss_failed"
    if code == "PA_KNOWLEDGE_001":
        return "formal_candidate_external_smoke_evidence_admission_failed"
    if isinstance(code, str) and code.startswith("PA_MODEL_"):
        return "formal_candidate_external_smoke_model_failed"
    return None


def _external_smoke_run_failure_code(
    *,
    detail: object,
    accepted: tuple[object, ...],
    cited: tuple[object, ...],
) -> str | None:
    outcome = getattr(detail, "outcome", None)
    if outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS:
        trace_code = _external_smoke_trace_failure_code(getattr(detail, "trace_events", ()))
        if trace_code is not None:
            return trace_code
    if not accepted:
        return "formal_candidate_external_smoke_evidence_admission_failed"
    if len(cited) != len(accepted):
        return "formal_candidate_external_smoke_citation_validation_failed"
    return None


def _external_smoke_admission_reason_code(detail: object) -> str | None:
    mapping = {
        "zero_knowledge_candidates": (
            KnowledgeCandidateAdmissionFailureReason.CANDIDATE_SET_EMPTY.value
        ),
        "knowledge_candidate_admission_pending": (
            KnowledgeCandidateAdmissionFailureReason.SCORE_MISSING.value
        ),
        "knowledge_candidate_threshold_not_met": (
            KnowledgeCandidateAdmissionFailureReason.THRESHOLD_NOT_MET.value
        ),
        "retrieval_policy_denied": (KnowledgeCandidateAdmissionFailureReason.POLICY_DENIED.value),
    }
    events = getattr(detail, "trace_events", ())
    if not isinstance(events, tuple | list):
        return None
    for event in reversed(events):
        if not isinstance(event, Mapping) or event.get("event_type") != "evidence_evaluation":
            continue
        payload = event.get("payload")
        metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
        reason = metadata.get("no_evidence_reason_code") if isinstance(metadata, Mapping) else None
        if isinstance(reason, str) and reason in mapping:
            return mapping[reason]
    return None


def _external_smoke_trace_failure_code(events: object) -> str | None:
    if not isinstance(events, tuple | list):
        return None
    for event in reversed(events):
        if not isinstance(event, Mapping):
            continue
        event_type = event.get("event_type")
        if event_type == "model_error":
            return "formal_candidate_external_smoke_model_failed"
        if event_type != "final_answer_validation_failed":
            continue
        payload = event.get("payload")
        error_code = payload.get("error_code") if isinstance(payload, Mapping) else None
        if error_code == "citation_binding_failed":
            return "formal_candidate_external_smoke_citation_validation_failed"
        return "formal_candidate_external_smoke_model_failed"
    return None


def _shared_model_connection_ids(manifest: object) -> tuple[str, ...]:
    model = getattr(manifest, "model", None)
    react = getattr(manifest, "react", None)
    review = getattr(manifest, "review", None)
    retrieval = getattr(manifest, "retrieval", None)
    roles = [model, getattr(react, "planner", None)]
    roles.extend(
        (
            getattr(retrieval, "planner_model", None),
            getattr(retrieval, "evaluator_model", None),
            getattr(review, "subagent", None),
        )
    )
    connection_ids: set[str] = set()
    for role in roles:
        if role is None:
            continue
        connection_id = getattr(role, "connection_id", None)
        if (
            getattr(role, "model_source", None) != "shared"
            or not isinstance(connection_id, str)
            or not connection_id.strip()
        ):
            raise ProductionAgentValidationError(
                "formal candidate external smoke requires Shared Model Connections"
            )
        connection_ids.add(connection_id.strip())
    if not connection_ids:
        raise ProductionAgentValidationError(
            "formal candidate external smoke requires a Model Connection"
        )
    return tuple(sorted(connection_ids))


def _validation_filename(
    *,
    kind: str,
    content: bytes,
    suffix: str,
) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{kind}-{digest}.{suffix}"


__all__ = [
    "FormalCandidateExternalSmokeDiagnosticError",
    "FormalProductionAgentCandidateExternalSmokeRunner",
    "FormalProductionAgentOnlineSmokeRunner",
    "ProductionOnlineAgentCandidateValidator",
]
