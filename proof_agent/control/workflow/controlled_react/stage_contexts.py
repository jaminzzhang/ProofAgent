from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from proof_agent.bootstrap.composition import HarnessInvocation
from proof_agent.contracts import (
    ContextAdmission,
    WorkflowStagePromptConfig,
    WorkflowTemplateExecutionInput,
)
from proof_agent.control.workflow.stage_context import (
    build_workflow_stage_context_preview,
    workflow_stage_context_summary,
)


def build_controlled_react_stage_contexts(
    *,
    invocation: HarnessInvocation,
    execution_input: WorkflowTemplateExecutionInput,
    conversation_context: ContextAdmission | None,
    selected_business_flow_skill_pack_id: str | None = None,
) -> tuple[dict[str, dict[str, Any]], tuple[dict[str, Any], ...]]:
    """Resolve configured V3 stage context before model-bearing execution."""

    contexts: dict[str, dict[str, Any]] = {}
    applications: list[dict[str, Any]] = []
    sample_context = _runtime_sample_context(
        invocation=invocation,
        conversation_context=conversation_context,
    )
    for config in execution_input.effective_stage_configuration.stages:
        prompt = _stage_prompt_config(config.prompt)
        business_flow_addendum_applied = False
        if selected_business_flow_skill_pack_id is not None:
            prompt, business_flow_addendum_applied = _prompt_with_business_flow_addendum(
                invocation=invocation,
                stage_id=config.id,
                prompt=prompt,
                selected_pack_id=selected_business_flow_skill_pack_id,
            )
        preview = build_workflow_stage_context_preview(
            descriptor=invocation.template,
            stage_id=config.id,
            prompt=prompt,
            context_options=config.context,
            sample_context=sample_context,
        )
        summary = workflow_stage_context_summary(preview)
        descriptor_stage = invocation.template.stage(config.id)
        context = {
            "business_context_addendum": preview["business_context_addendum"],
            "structured_control_context": preview["structured_control_context"],
            "summary": summary,
        }
        contexts[config.id] = context
        if _summary_has_context(summary):
            application = {
                **summary,
                "stage_label": descriptor_stage.label,
                "model_bearing": descriptor_stage.model_bearing,
                "template_descriptor_version": execution_input.template_descriptor_version,
            }
            if business_flow_addendum_applied:
                application["context_source"] = "business_flow_skill_pack"
                application["business_flow_skill_pack_id"] = selected_business_flow_skill_pack_id
            applications.append(application)
    return contexts, tuple(applications)


def _runtime_sample_context(
    *,
    invocation: HarnessInvocation,
    conversation_context: ContextAdmission | None,
) -> dict[str, Any]:
    manifest = invocation.manifest
    recent_conversation_summary = (
        conversation_context.summary
        if conversation_context is not None and conversation_context.admitted
        else ""
    )
    return {
        "agent_purpose": manifest.purpose,
        "intent_resolution": {},
        "recent_conversation_summary": recent_conversation_summary,
        "bound_knowledge_sources": [
            binding.source_ref.source_id for binding in manifest.knowledge_bindings
        ],
        "bound_tools": "",
        "policy_outline": str(manifest.policy.file),
        "missing_field_schema": [],
        "retrieval_intent": "",
        "source_routing_metadata": [],
        "evidence_summary": [],
        "citation_requirements": "Final answers require accepted evidence citations.",
        "response_disclosure_policy": (
            manifest.response.model_dump(mode="json") if manifest.response else {}
        ),
        "tool_proposal": {},
        "tool_contract_summary": "",
        "approval_requirements": "",
        "approval_state": "",
        "parameter_bounds": {},
        "memory_scope": {
            "enabled": manifest.capabilities.memory.enabled,
            "provider": manifest.capabilities.memory.provider,
            "scopes": dict(manifest.capabilities.memory.scopes),
        },
        "memory_denylist_summary": sorted(invocation.memory_deny_fields),
        "outcome": "",
        "governance_summary": [],
    }


def _summary_has_context(summary: Mapping[str, Any]) -> bool:
    return bool(
        summary.get("prompt_fields")
        or summary.get("context_options")
        or summary.get("business_context_length", 0)
        or summary.get("task_instruction_count", 0)
        or summary.get("output_preference_count", 0)
    )


def _prompt_with_business_flow_addendum(
    *,
    invocation: HarnessInvocation,
    stage_id: str,
    prompt: WorkflowStagePromptConfig,
    selected_pack_id: str,
) -> tuple[WorkflowStagePromptConfig, bool]:
    pack = next(
        (item for item in invocation.business_flow_skill_packs if item.id == selected_pack_id),
        None,
    )
    if pack is None:
        return prompt, False
    addendum = pack.stage_prompt_addenda.get(stage_id)
    if addendum is None:
        return prompt, False
    base_config = _stage_prompt_config(prompt)
    addendum_config = _stage_prompt_config(addendum)
    return WorkflowStagePromptConfig(
        business_context="\n\n".join(
            item
            for item in (base_config.business_context, addendum_config.business_context)
            if item
        ),
        task_instructions=(*base_config.task_instructions, *addendum_config.task_instructions),
        output_preferences=(
            *base_config.output_preferences,
            *addendum_config.output_preferences,
        ),
    ), True


def _stage_prompt_config(
    prompt: Mapping[str, Any] | WorkflowStagePromptConfig,
) -> WorkflowStagePromptConfig:
    if isinstance(prompt, WorkflowStagePromptConfig):
        return prompt
    return WorkflowStagePromptConfig(
        business_context=str(prompt.get("business_context", "") or ""),
        task_instructions=tuple(str(item) for item in prompt.get("task_instructions", ()) or ()),
        output_preferences=tuple(str(item) for item in prompt.get("output_preferences", ()) or ()),
    )
