from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from proof_agent.contracts import (
    AgentManifest,
    ContextAdmission,
    InstitutionAuthorizationContext,
    PublishedAgentRuntimeFacts,
    ResolvedWorkflowStageRuntimeConfiguration,
    RunStartContextAssembly,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationRuntimeSourceType,
    WorkflowTemplateExecutionInput,
)
from proof_agent.contracts.conversation import context_admission_payload
from proof_agent.control.workflow.stage_configuration import (
    resolve_workflow_stage_runtime_configuration as resolve_stage_configuration,
    summarize_workflow_stage_configuration,
)
from proof_agent.errors import ProofAgentError


def resolve_workflow_stage_runtime_configuration(
    *,
    agent_yaml: Path,
    manifest: AgentManifest,
    agent_id: str | None,
    agent_version_id: str | None,
    published_agent_runtime_facts: PublishedAgentRuntimeFacts | None,
) -> ResolvedWorkflowStageRuntimeConfiguration:
    """Resolve immutable run-start stage facts for any workflow runtime adapter."""

    source = _workflow_stage_configuration_source(
        manifest=manifest,
        agent_version_id=agent_version_id,
    )
    if published_agent_runtime_facts is not None:
        _require_matching_published_agent_runtime_facts(
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            facts=published_agent_runtime_facts,
            artifact_path=agent_yaml,
        )
        return ResolvedWorkflowStageRuntimeConfiguration(
            workflow_stage_availability=(
                published_agent_runtime_facts.workflow_stage_availability
            ),
            effective_stage_configuration=(
                published_agent_runtime_facts.effective_stage_configuration
            ),
            configuration_source=source,
            trace_summary=summarize_workflow_stage_configuration(
                published_agent_runtime_facts.effective_stage_configuration,
                source=source,
            ),
        )
    resolved = resolve_stage_configuration(
        agent_yaml.read_text(encoding="utf-8"),
        source=source,
    )
    if resolved is None:
        raise ProofAgentError(
            "PA_CONFIG_002",
            "workflow stage runtime configuration could not be resolved",
            "Use Agent Contract YAML with workflow.template and capabilities.",
            artifact_path=agent_yaml,
        )
    return resolved


def build_workflow_template_execution_input(
    *,
    run_id: str,
    question: str,
    agent_id: str | None,
    agent_version_id: str | None,
    draft_id: str | None,
    stage_runtime_configuration: ResolvedWorkflowStageRuntimeConfiguration,
    conversation_context: ContextAdmission | None,
    run_start_context: RunStartContextAssembly | None = None,
    institution_authorization: InstitutionAuthorizationContext | None = None,
) -> WorkflowTemplateExecutionInput:
    """Build the typed, trace-safe execution input from resolved run-start facts."""

    return WorkflowTemplateExecutionInput(
        run_id=run_id,
        template_name=(
            stage_runtime_configuration.effective_stage_configuration.template_name
        ),
        template_descriptor_version=(
            stage_runtime_configuration.effective_stage_configuration.template_descriptor_version
        ),
        question=question,
        institution_authorization=(
            institution_authorization or InstitutionAuthorizationContext()
        ),
        agent_id=agent_id,
        agent_version_id=agent_version_id,
        draft_id=draft_id,
        effective_stage_configuration_ref=(
            stage_runtime_configuration.configuration_source.reference
        ),
        workflow_stage_availability=(
            stage_runtime_configuration.workflow_stage_availability
        ),
        effective_stage_configuration=(
            stage_runtime_configuration.effective_stage_configuration
        ),
        stage_configuration_source=(stage_runtime_configuration.configuration_source),
        conversation_context_summary=_conversation_context_summary(
            conversation_context
        ),
        controlled_run_context_summary=_controlled_run_context_summary(
            run_start_context
        ),
    )


def _require_matching_published_agent_runtime_facts(
    *,
    agent_id: str | None,
    agent_version_id: str | None,
    facts: PublishedAgentRuntimeFacts,
    artifact_path: Path,
) -> None:
    if agent_id is not None and facts.agent_id != agent_id:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "Published Agent runtime facts do not match the requested Agent",
            "Use runtime facts captured from the selected Published Agent Version.",
            artifact_path=artifact_path,
        )
    if agent_version_id is not None and facts.agent_version_id != agent_version_id:
        raise ProofAgentError(
            "PA_RUNTIME_001",
            "Published Agent runtime facts do not match the requested Agent Version",
            "Use runtime facts captured from the selected Published Agent Version.",
            artifact_path=artifact_path,
        )


def _workflow_stage_configuration_source(
    *,
    manifest: AgentManifest,
    agent_version_id: str | None,
) -> WorkflowStageConfigurationRuntimeSource:
    if agent_version_id:
        return WorkflowStageConfigurationRuntimeSource(
            source_type=(
                WorkflowStageConfigurationRuntimeSourceType.PUBLISHED_AGENT_VERSION
            ),
            reference=(
                f"published_version:{agent_version_id}:"
                "effective_workflow_stage_configuration"
            ),
        )
    return WorkflowStageConfigurationRuntimeSource(
        source_type=WorkflowStageConfigurationRuntimeSourceType.PACKAGE_LOCAL_LATEST,
        reference=f"package_local:{manifest.name}",
    )


def _conversation_context_summary(
    conversation_context: ContextAdmission | None,
) -> Mapping[str, Any]:
    if conversation_context is None:
        return {}
    return context_admission_payload(conversation_context)


def _controlled_run_context_summary(
    run_start_context: RunStartContextAssembly | None,
) -> Mapping[str, Any]:
    if run_start_context is None:
        return {}
    return run_start_context.trace_safe_summary.model_dump(mode="json")
