"""Real online smoke validation for a production Published Agent candidate."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.knowledge_release import (
    require_formal_production_agent_phase_f_record,
)
from proof_agent.contracts import (
    FormalProductionAgentOnlineSmokeRequest,
    FormalProductionAgentOnlineSmokeResult,
    FormalProductionAgentQueryGrantStaging,
    InstitutionAuthorizationContext,
    PublishedAgentRuntimeFacts,
    ReceiptOutcome,
    RunPurpose,
)
from proof_agent.control.formal_production_agent_candidate import (
    require_formal_production_agent_candidate,
)
from proof_agent.control.production_agent import ProductionAgentValidationError
from proof_agent.control.production_agent_publication import (
    ProductionAgentCandidateValidation,
)
from proof_agent.delivery.published_agent_materializer import (
    materialize_agent_contract_bundle,
)
from proof_agent.delivery.published_agents import PublishedAgent
from proof_agent.delivery.run_execution_service import (
    RunExecutionDependencies,
    execute_published_agent_run,
)
from proof_agent.observability.storage.run_store import RunStore


@dataclass(frozen=True)
class _RetainedOnlineSmoke:
    outcome: ReceiptOutcome
    accepted_citation_count: int
    trace_ref: Any
    receipt_ref: Any


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
        artifact_store: Any,
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
            execution = self._execute(
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
            if require_successful_citations and (
                detail.outcome is not ReceiptOutcome.ANSWERED_WITH_CITATIONS
                or not accepted
                or len(cited) != len(accepted)
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
                version_id=version_id,
                run_id=run_id,
                kind="trace",
                content=trace,
                suffix="jsonl",
            ),
            content=trace,
            media_type="application/x-ndjson",
        )
        receipt_ref = self._put_verified(
            key=_validation_key(
                version_id=version_id,
                run_id=run_id,
                kind="receipt",
                content=receipt,
                suffix="md",
            ),
            content=receipt,
            media_type="text/markdown",
        )
        return _RetainedOnlineSmoke(
            outcome=detail.outcome,
            accepted_citation_count=len(cited),
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
        artifact_store: Any,
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
        artifact_store: Any,
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


__all__ = [
    "FormalProductionAgentOnlineSmokeRunner",
    "ProductionOnlineAgentCandidateValidator",
]
