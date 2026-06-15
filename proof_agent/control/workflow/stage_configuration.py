from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml  # type: ignore[import-untyped]

from proof_agent.contracts import (
    EffectiveWorkflowStageConfiguration,
    EffectiveWorkflowStageConfigurationStage,
    ResolvedWorkflowStageRuntimeConfiguration,
    WorkflowStageAvailability,
    WorkflowStageAvailabilityReason,
    WorkflowStageAvailabilitySet,
    WorkflowStageConfigurationRuntimeSource,
    WorkflowStageConfigurationTraceStageSummary,
    WorkflowStageConfigurationTraceSummary,
)
from proof_agent.control.workflow.templates import resolve_workflow_template


TOOL_CONTEXT_OPTIONS = frozenset(
    {
        "include_bound_tools",
        "include_tool_proposal",
        "include_tool_contract_summary",
        "include_approval_requirements",
        "include_approval_state",
        "include_parameter_bounds",
    }
)
MEMORY_CONTEXT_OPTIONS = frozenset(
    {
        "include_memory_scope",
        "include_memory_denylist_summary",
    }
)


def resolve_workflow_stage_runtime_configuration(
    agent_yaml: str,
    *,
    source: WorkflowStageConfigurationRuntimeSource,
) -> ResolvedWorkflowStageRuntimeConfiguration | None:
    """Resolve Workflow Stage runtime configuration from the latest Agent Contract YAML."""

    raw = yaml.safe_load(agent_yaml)
    if not isinstance(raw, Mapping):
        return None
    workflow = raw.get("workflow")
    capabilities = raw.get("capabilities")
    if not isinstance(workflow, Mapping) or not isinstance(capabilities, Mapping):
        return None
    template_name = workflow.get("template")
    if not isinstance(template_name, str) or not template_name:
        return None

    template = resolve_workflow_template(template_name)
    template_descriptor_version = _template_descriptor_version(workflow, template.descriptor_version)
    capability_summary = _effective_capability_summary(capabilities)
    configured_stages = _configured_stage_overrides(workflow)
    availability = WorkflowStageAvailabilitySet(
        template_name=template.name,
        template_descriptor_version=template_descriptor_version,
        stages=tuple(
            _workflow_stage_availability(
                stage.id,
                stage.availability_capability,
                capability_summary,
            )
            for stage in template.stages
        ),
    )
    effective_stages: list[EffectiveWorkflowStageConfigurationStage] = []
    for descriptor in template.stages:
        if not availability.is_available(descriptor.id):
            continue
        override = configured_stages.get(descriptor.id, {})
        available_context_options = tuple(
            option
            for option in descriptor.context_options
            if _context_option_available(option, capability_summary)
        )
        effective_stages.append(
            EffectiveWorkflowStageConfigurationStage(
                id=descriptor.id,
                label=descriptor.label,
                description=descriptor.description,
                required=descriptor.required,
                model_bearing=descriptor.model_bearing,
                editable_prompt_fields=descriptor.editable_prompt_fields,
                available_context_options=available_context_options,
                prompt=_effective_stage_prompt(override),
                context=_effective_stage_context(override, available_context_options),
                source_override={"configured": bool(override)},
            )
        )
    effective_configuration = EffectiveWorkflowStageConfiguration(
        template_name=template.name,
        template_descriptor_version=template_descriptor_version,
        stages=tuple(effective_stages),
        capabilities=capability_summary,
    )
    trace_summary = summarize_workflow_stage_configuration(
        effective_configuration,
        source=source,
    )
    return ResolvedWorkflowStageRuntimeConfiguration(
        workflow_stage_availability=availability,
        effective_stage_configuration=effective_configuration,
        configuration_source=source,
        trace_summary=trace_summary,
    )


def summarize_workflow_stage_configuration(
    effective_configuration: EffectiveWorkflowStageConfiguration,
    *,
    source: WorkflowStageConfigurationRuntimeSource,
) -> WorkflowStageConfigurationTraceSummary:
    """Build a trace-safe summary for an Effective Workflow Stage Configuration."""

    return WorkflowStageConfigurationTraceSummary(
        source=source,
        template_name=effective_configuration.template_name,
        template_descriptor_version=(
            effective_configuration.template_descriptor_version
        ),
        stages=tuple(_trace_stage_summary(stage) for stage in effective_configuration.stages),
    )


def _template_descriptor_version(
    workflow: Mapping[str, Any],
    default: str,
) -> str:
    descriptor_version = workflow.get("template_descriptor_version")
    return (
        descriptor_version
        if isinstance(descriptor_version, str) and descriptor_version
        else default
    )


def _workflow_stage_availability(
    stage_id: str,
    capability: str | None,
    capability_summary: Mapping[str, Mapping[str, Any]],
) -> WorkflowStageAvailability:
    if capability is None:
        return WorkflowStageAvailability(
            stage_id=stage_id,
            available=True,
            reason=WorkflowStageAvailabilityReason.ALWAYS_AVAILABLE,
        )
    available = _workflow_stage_available(capability, capability_summary)
    return WorkflowStageAvailability(
        stage_id=stage_id,
        available=available,
        reason=(
            WorkflowStageAvailabilityReason.CAPABILITY_ENABLED
            if available
            else WorkflowStageAvailabilityReason.CAPABILITY_DISABLED
        ),
        capability=capability,
    )


def _workflow_stage_available(
    capability: str | None,
    capability_summary: Mapping[str, Mapping[str, Any]],
) -> bool:
    if capability is None:
        return True
    return bool(capability_summary.get(capability, {}).get("enabled"))


def _effective_capability_summary(capabilities: Mapping[str, Any]) -> dict[str, Any]:
    tools = capabilities.get("tools")
    memory = capabilities.get("memory")
    tools_mapping = tools if isinstance(tools, Mapping) else {}
    memory_mapping = memory if isinstance(memory, Mapping) else {}
    return {
        "tools": {
            "enabled": bool(tools_mapping.get("enabled")),
            "file": (
                str(tools_mapping["file"])
                if tools_mapping.get("file") is not None
                else None
            ),
        },
        "memory": {
            "enabled": bool(memory_mapping.get("enabled")),
            "provider": (
                str(memory_mapping["provider"])
                if memory_mapping.get("provider") is not None
                else None
            ),
            "scopes": (
                _jsonable(memory_mapping.get("scopes"))
                if isinstance(memory_mapping.get("scopes"), Mapping)
                else {}
            ),
        },
    }


def _configured_stage_overrides(workflow: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    configured: dict[str, Mapping[str, Any]] = {}
    stages = workflow.get("stages")
    if not isinstance(stages, list | tuple):
        return configured
    for item in stages:
        if not isinstance(item, Mapping):
            continue
        stage_id = item.get("id")
        if isinstance(stage_id, str) and stage_id:
            configured[stage_id] = item
    return configured


def _effective_stage_prompt(stage_override: Mapping[str, Any]) -> dict[str, Any]:
    prompt = stage_override.get("prompt")
    prompt_mapping = prompt if isinstance(prompt, Mapping) else {}
    return {
        "business_context": str(prompt_mapping.get("business_context", "") or ""),
        "task_instructions": [
            str(item) for item in prompt_mapping.get("task_instructions", ()) or ()
        ],
        "output_preferences": [
            str(item) for item in prompt_mapping.get("output_preferences", ()) or ()
        ],
    }


def _effective_stage_context(
    stage_override: Mapping[str, Any],
    available_context_options: tuple[str, ...],
) -> dict[str, bool]:
    context = stage_override.get("context")
    context_mapping = context if isinstance(context, Mapping) else {}
    return {
        option: True for option in available_context_options if bool(context_mapping.get(option))
    }


def _context_option_available(
    option: str,
    capability_summary: Mapping[str, Mapping[str, Any]],
) -> bool:
    if option in TOOL_CONTEXT_OPTIONS:
        return bool(capability_summary["tools"].get("enabled"))
    if option in MEMORY_CONTEXT_OPTIONS:
        return bool(capability_summary["memory"].get("enabled"))
    return True


def _trace_stage_summary(
    stage: EffectiveWorkflowStageConfigurationStage,
) -> WorkflowStageConfigurationTraceStageSummary:
    return WorkflowStageConfigurationTraceStageSummary(
        stage_id=stage.id,
        prompt_field_names=_configured_prompt_field_names(stage.prompt),
        prompt_character_count=_prompt_character_count(stage.prompt),
        context_option_names=tuple(sorted(stage.context)),
        redacted=True,
    )


def _configured_prompt_field_names(prompt: Mapping[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    if prompt.get("business_context"):
        names.append("business_context")
    if prompt.get("task_instructions"):
        names.append("task_instructions")
    if prompt.get("output_preferences"):
        names.append("output_preferences")
    return tuple(names)


def _prompt_character_count(prompt: Mapping[str, Any]) -> int:
    count = len(str(prompt.get("business_context", "") or ""))
    count += sum(len(str(item)) for item in prompt.get("task_instructions", ()) or ())
    count += sum(len(str(item)) for item in prompt.get("output_preferences", ()) or ())
    return count


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
