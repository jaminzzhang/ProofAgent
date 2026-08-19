"""Local execution adapter for Agent Configuration Workspace validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from proof_agent.bootstrap.loader import load_agent_manifest
from proof_agent.configuration.compiler import compile_draft_agent
from proof_agent.configuration.local_store import LocalAgentConfigurationStore
from proof_agent.contracts import (
    AuditActorFacts,
    DraftAgent,
    RunPurpose,
    SensitiveValidationCaptureArtifact,
    ValidationCaptureExclusionSummary,
    ValidationCaptureResultSummary,
    ValidationCaptureSourceReference,
    ValidationCaptureV2Payload,
    WorkflowStageContextApplicationProjection,
    WorkflowStageContextConfigurationCapture,
    WorkflowStageFailureDiagnosticProjection,
    WorkflowStageLlmInteractionCapture,
    WorkflowStagePromptValueCapture,
    WorkflowStageResultVerificationProjection,
    WorkflowTemplateExecutionInput,
    WorkflowTemplateExecutionResult,
)
from proof_agent.control.agent_configuration_workspace import (
    AgentConfigurationValidationCaptureError,
    AgentConfigurationValidationExecution,
)
from proof_agent.delivery.agent_package_execution import (
    AgentPackageRunRequest,
    execute_agent_package_run,
)
from proof_agent.observability.storage.run_store import RunStore


class LocalAgentConfigurationValidationAdapter:
    """Compile and execute one development Draft behind the Workspace seam."""

    def __init__(
        self,
        *,
        configuration_store: LocalAgentConfigurationStore,
        run_store: RunStore,
    ) -> None:
        self._configuration_store = configuration_store
        self._run_store = run_store

    def validate(
        self,
        *,
        draft: DraftAgent,
        question: str,
        full_capture: bool,
        retain_for_audit: bool,
        actor: AuditActorFacts,
    ) -> AgentConfigurationValidationExecution:
        package_dir = compile_draft_agent(
            draft,
            self._configuration_store.root_dir / "compiled",
        )
        manifest = load_agent_manifest(package_dir / "agent.yaml")
        run_id = f"run_{uuid4().hex[:8]}"
        run_artifact_dir = self._run_store.create_run_dir(run_id)
        result = execute_agent_package_run(
            AgentPackageRunRequest(
                agent_yaml=package_dir / "agent.yaml",
                question=question,
                runs_dir=run_artifact_dir,
                run_id=run_id,
                store=self._run_store,
                manifest=manifest,
                resolved_knowledge_bindings=None,
                configuration_store=self._configuration_store,
                run_purpose=RunPurpose.VALIDATION,
                agent_id=draft.agent_id,
                draft_id=draft.draft_id,
            )
        )
        detail = self._run_store.get_run_detail(run_id)
        if detail is None:
            raise RuntimeError("Validation run artifacts were not persisted.")
        validation_capture: SensitiveValidationCaptureArtifact | None = None
        capture_error: AgentConfigurationValidationCaptureError | None = None
        if full_capture:
            try:
                artifact = (
                    self._configuration_store.record_sensitive_validation_capture_artifact(
                        run_id=run_id,
                        draft_id=draft.draft_id,
                        payload=_validation_capture_payload(
                            detail=detail,
                            execution_input=result.workflow_template_execution_input,
                            execution_result=result.workflow_template_execution_result,
                        ),
                        actor=actor.subject,
                        retain_for_audit=retain_for_audit,
                    )
                )
                if not self._run_store.attach_validation_capture(
                    run_id,
                    artifact.capture_id,
                ):
                    raise RuntimeError(
                        "Validation capture artifact was not attached to the run."
                    )
                detail = self._run_store.get_run_detail(run_id)
                if detail is None:
                    raise RuntimeError(
                        "Validation run artifacts disappeared after capture attachment."
                    )
                validation_capture = artifact
            except (ValueError, ValidationError):
                capture_error = _validation_capture_failure_projection()
        if detail is None:
            raise RuntimeError("Validation run artifacts were not persisted.")
        return AgentConfigurationValidationExecution(
            run_id=detail.run_id,
            outcome=detail.outcome.value,
            run_purpose=detail.run_purpose.value,
            agent_id=detail.agent_id or draft.agent_id,
            draft_id=detail.draft_id or draft.draft_id,
            summary=result.final_output,
            trace_events=detail.trace_events,
            validation_capture=validation_capture,
            capture_error=capture_error,
            resolved_knowledge_bindings=None,
        )


def _validation_capture_payload(
    *,
    detail: Any,
    execution_input: WorkflowTemplateExecutionInput | None,
    execution_result: WorkflowTemplateExecutionResult | None,
) -> dict[str, Any]:
    if execution_input is None or execution_result is None:
        raise ValueError("validation capture requires workflow execution input and result")
    stage_labels = {
        stage.id: stage.label
        for stage in execution_input.effective_stage_configuration.stages
    }
    payload = ValidationCaptureV2Payload(
        source=_validation_capture_source(detail, execution_input),
        stage_prompt_values=tuple(
            _workflow_stage_prompt_value_capture(stage)
            for stage in execution_input.effective_stage_configuration.stages
        ),
        context_configuration=tuple(
            _workflow_stage_context_configuration_capture(stage)
            for stage in execution_input.effective_stage_configuration.stages
        ),
        context_applications=tuple(
            _workflow_stage_context_application_projection(
                item,
                stage_labels=stage_labels,
            )
            for item in execution_result.stage_context_applications
        ),
        stage_results=tuple(
            WorkflowStageResultVerificationProjection(
                stage_id=stage_result.stage_id,
                stage_label=stage_labels.get(stage_result.stage_id),
                status=stage_result.status,
                outcome=stage_result.outcome,
                summary=stage_result.summary,
                produced_fact_refs=stage_result.produced_fact_refs,
            )
            for stage_result in execution_result.stage_results
        ),
        failure_diagnostics=tuple(
            WorkflowStageFailureDiagnosticProjection(
                stage_id=diagnostic.stage_id,
                stage_label=(
                    diagnostic.stage_label or stage_labels.get(diagnostic.stage_id)
                ),
                event_type=diagnostic.event_type,
                status=diagnostic.status,
                error_code=diagnostic.error_code,
                role=diagnostic.role,
                raw_content_length=diagnostic.raw_content_length,
                related_event_id=diagnostic.related_event_id,
                contract_name=diagnostic.contract_name,
                violation_codes=diagnostic.violation_codes,
                field_paths=diagnostic.field_paths,
                violation_count=diagnostic.violation_count,
            )
            for diagnostic in execution_result.stage_failure_diagnostics
        ),
        llm_interactions=tuple(
            WorkflowStageLlmInteractionCapture(
                stage_id=interaction.stage_id,
                stage_label=(
                    interaction.stage_label or stage_labels.get(interaction.stage_id)
                ),
                role=interaction.role,
                provider=interaction.provider,
                model=interaction.model,
                request_json=interaction.request_json,
                response_json=interaction.response_json,
                response_content_length=interaction.response_content_length,
                response_json_parse_error_code=(
                    interaction.response_json_parse_error_code
                ),
            )
            for interaction in execution_result.stage_llm_interactions
        ),
        result_summary=ValidationCaptureResultSummary(
            outcome=execution_result.outcome,
            final_output=execution_result.final_output,
            final_output_length=len(execution_result.final_output),
            fact_refs=_execution_result_fact_refs(execution_result),
            approval_pause=(
                execution_result.approval_pause.model_dump(mode="json")
                if execution_result.approval_pause is not None
                else None
            ),
            clarification_need=(
                execution_result.clarification_need.model_dump(mode="json")
                if execution_result.clarification_need is not None
                else None
            ),
        ),
        exclusions=ValidationCaptureExclusionSummary(
            excluded_categories=(
                "raw_prompt",
                "raw_context",
                "raw_evidence",
                "tool_payload",
                "complete_provider_response",
                "runtime_state",
                "chain_of_thought",
            ),
            sanitizer_version="validation_capture.v2",
            redacted_secret_count=0,
            dropped_unsafe_key_count=0,
            redaction_applied=False,
        ),
    )
    return payload.model_dump(mode="json")


def _validation_capture_source(
    detail: Any,
    execution_input: WorkflowTemplateExecutionInput,
) -> ValidationCaptureSourceReference:
    source = execution_input.stage_configuration_source
    return ValidationCaptureSourceReference(
        run_id=detail.run_id,
        run_purpose=detail.run_purpose.value,
        agent_id=execution_input.agent_id or detail.agent_id,
        agent_version_id=execution_input.agent_version_id or detail.agent_version_id,
        draft_id=execution_input.draft_id or detail.draft_id,
        template_name=execution_input.template_name,
        template_descriptor_version=execution_input.template_descriptor_version,
        stage_configuration_source_type=source.source_type.value,
        stage_configuration_source_reference=source.reference,
        effective_stage_configuration_ref=(
            execution_input.effective_stage_configuration_ref
        ),
    )


def _workflow_stage_prompt_value_capture(stage: Any) -> WorkflowStagePromptValueCapture:
    prompt_values = dict(stage.prompt)
    return WorkflowStagePromptValueCapture(
        stage_id=stage.id,
        stage_label=stage.label,
        prompt_values=prompt_values,
        prompt_field_names=tuple(str(key) for key in prompt_values),
        prompt_character_count=_prompt_character_count(prompt_values),
        redaction_applied=False,
        source="run_start_workflow_template_execution_input",
    )


def _workflow_stage_context_configuration_capture(
    stage: Any,
) -> WorkflowStageContextConfigurationCapture:
    return WorkflowStageContextConfigurationCapture(
        stage_id=stage.id,
        stage_label=stage.label,
        selected_context_options=tuple(
            str(key) for key, enabled in stage.context.items() if enabled
        ),
        available_context_options=tuple(
            str(key) for key in stage.available_context_options
        ),
    )


def _workflow_stage_context_application_projection(
    item: Mapping[str, Any],
    *,
    stage_labels: Mapping[str, str],
) -> WorkflowStageContextApplicationProjection:
    stage_id = str(item.get("stage_id") or "unknown")
    return WorkflowStageContextApplicationProjection(
        stage_id=stage_id,
        stage_label=str(item.get("stage_label") or stage_labels.get(stage_id) or ""),
        summary=item,
    )


def _execution_result_fact_refs(
    execution_result: WorkflowTemplateExecutionResult,
) -> tuple[str, ...]:
    refs: list[str] = []
    for stage_result in execution_result.stage_results:
        refs.extend(stage_result.produced_fact_refs)
    return tuple(refs)


def _prompt_character_count(prompt_values: Mapping[str, Any]) -> int:
    total = 0
    for value in prompt_values.values():
        if isinstance(value, str):
            total += len(value)
        elif isinstance(value, list | tuple):
            total += sum(len(item) for item in value if isinstance(item, str))
    return total


def _validation_capture_failure_projection(
) -> AgentConfigurationValidationCaptureError:
    return AgentConfigurationValidationCaptureError(
        code="VALIDATION_CAPTURE_REJECTED",
        message=(
            "Validation capture artifact was not created because the v2 safety "
            "gate rejected unsafe fields."
        ),
        retryable=False,
    )
